from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from cover_letter import generate_cover_letter_result
from dashboard import agent_apply_loop, review_drafts
from hh_api import HHApiClient, HHApiError
from notifications import send_telegram_digest
from profile_builder import build_profile_from_text
from resume_parser import extract_text
from scorer import score_vacancy
from storage import Storage
from users import (
    create_user,
    load_user_config,
    load_user_profile,
    runtime_config_for_user,
    save_credentials,
    save_uploaded_resume,
    save_user_config,
    save_user_profile,
)


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
PROFILE_PATH = ROOT / "resume_profile.json"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required. Install dependencies: pip install -r requirements.txt") from exc
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def make_storage(config: dict[str, Any]) -> Storage:
    path = config.get("storage", {}).get("sqlite_path", "job_apply_bot.db")
    return Storage(ROOT / path)


def load_context(config_path: str, profile_path: str, user_id: str | None) -> tuple[dict[str, Any], dict[str, Any], Storage]:
    if user_id:
        create_user(user_id)
        config = runtime_config_for_user(user_id)
        profile = load_user_profile(user_id)
    else:
        config = load_config(Path(config_path))
        profile = load_profile(Path(profile_path))
    return config, profile, make_storage(config)


def make_api(config: dict[str, Any], storage: Storage, token_provider: str = "hh_app") -> HHApiClient:
    hh = config.get("hh", {})
    token = storage.load_token(token_provider) or {}
    if token_provider == "hh_user" and not token:
        token = storage.load_token("hh") or {}
    env_token = os.getenv("HH_ACCESS_TOKEN")
    access_token = env_token or token.get("access_token")
    refresh_token = token.get("refresh_token")

    def update_token(new_token: dict[str, Any]) -> None:
        merged = dict(token)
        merged.update(new_token)
        storage.save_token(token_provider, merged)

    return HHApiClient(
        base_url=hh.get("base_url", "https://api.hh.ru"),
        token_url=hh.get("token_url", "https://api.hh.ru/token"),
        auth_url=hh.get("auth_url", "https://hh.ru/oauth/authorize"),
        user_agent=hh.get("user_agent", "HH-Vacancy-Assistant/1.0"),
        client_id=os.getenv("HH_CLIENT_ID") or hh.get("client_id"),
        client_secret=os.getenv("HH_CLIENT_SECRET") or hh.get("client_secret"),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=token.get("expires_at"),
        token_updater=update_token,
    )


def search_params(config: dict[str, Any], keyword: str, page: int) -> dict[str, Any]:
    search = config.get("search", {})
    params: dict[str, Any] = {
        "text": keyword,
        "page": page,
        "per_page": search.get("per_page", 20),
        "area": search.get("areas", []),
        "period": search.get("period_days"),
        "currency": search.get("currency"),
        "salary": search.get("desired_salary"),
        "only_with_salary": search.get("only_with_salary"),
        "experience": search.get("experience", []),
        "employment": search.get("employment", []),
        "schedule": search.get("schedule", []),
        "work_format": search.get("work_format", []),
        "excluded_text": search.get("excluded_text"),
        "order_by": "publication_time",
        "responses_count_enabled": True,
    }
    return params


def search_strategies(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return enabled search strategies, keeping old single-search configs valid."""
    search = config.get("search", {})
    configured = search.get("strategies")
    if not isinstance(configured, list) or not configured:
        return [("Основной поиск", config)]

    result: list[tuple[str, dict[str, Any]]] = []
    for item in configured:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        keywords = item.get("keywords")
        if not isinstance(keywords, list) or not any(str(value).strip() for value in keywords):
            continue
        strategy_config = copy.deepcopy(config)
        strategy_search = strategy_config.setdefault("search", {})
        strategy_search["keywords"] = keywords
        for key in ("areas", "period_days", "per_page", "pages_per_keyword", "currency", "desired_salary", "only_with_salary", "experience", "employment", "schedule", "work_format", "excluded_text"):
            if key in item:
                strategy_search[key] = item[key]
        if isinstance(item.get("filters"), dict):
            strategy_config.setdefault("filters", {}).update(item["filters"])
        result.append((str(item.get("name") or "Поисковая стратегия"), strategy_config))
    return result or [("Основной поиск", config)]


def scan(config: dict[str, Any], profile: dict[str, Any], api: HHApiClient, storage: Storage) -> list[dict[str, Any]]:
    if not api.access_token:
        print("No HH application token found. Requesting one with client_credentials...")
        api.get_application_token()

    limits = config.get("limits", {})
    max_drafts = int(limits.get("max_drafts_per_scan", 20))
    delay = float(limits.get("request_delay_seconds", 0.3))
    seen_ids: set[str] = set()
    created = 0
    recommended: list[dict[str, Any]] = []

    for strategy_name, strategy_config in search_strategies(config):
        search = strategy_config.get("search", {})
        filters = strategy_config.get("filters", {})
        min_score = int(filters.get("min_score", 65))
        pages = int(search.get("pages_per_keyword", 1))
        keywords = search.get("keywords", [])
        print(f"Strategy: {strategy_name}")
        for keyword in keywords:
            for page in range(pages):
                try:
                    result = api.search_vacancies(search_params(strategy_config, keyword, page))
                except HHApiError as exc:
                    if _is_token_revoked(exc):
                        print("HH application token is revoked. Requesting a new one...")
                        api.get_application_token(force=True)
                        try:
                            result = api.search_vacancies(search_params(strategy_config, keyword, page))
                        except HHApiError as retry_exc:
                            print(f"Search failed for {keyword}: {retry_exc.status_code}: {retry_exc.payload}", file=sys.stderr)
                            continue
                    else:
                        print(f"Search failed for {keyword}: {exc.status_code}: {exc.payload}", file=sys.stderr)
                        continue
                for item in result.get("items", []):
                    vacancy_id = str(item.get("id"))
                    if not vacancy_id or vacancy_id in seen_ids or storage.has_terminal_status(vacancy_id):
                        continue
                    seen_ids.add(vacancy_id)
                    time.sleep(delay)
                    try:
                        vacancy = api.get_vacancy(vacancy_id)
                    except HHApiError as exc:
                        print(f"Vacancy {vacancy_id} failed: {exc.status_code}: {exc.payload}", file=sys.stderr)
                        continue
                    score = score_vacancy(vacancy, profile, filters)
                    if score.blocked or score.score < min_score:
                        continue
                    letter_result = generate_cover_letter_result(vacancy, profile)
                    recommended_score = int(filters.get("recommended_score", 80))
                    recommendation = "recommended" if score.score >= recommended_score else "review"
                    is_new = storage.upsert_draft(
                        vacancy,
                        score.score,
                        score.reasons,
                        letter_result.letter,
                        strategy_name=strategy_name,
                        recommendation=recommendation,
                        letter_quality=letter_result.quality,
                    )
                    created += 1
                    print(f"{recommendation}: {score.score} | {vacancy.get('name')} | {vacancy_id}")
                    if recommendation == "recommended" and is_new:
                        recommended.append(
                            {
                                "title": vacancy.get("name"),
                                "company": (vacancy.get("employer") or {}).get("name"),
                                "score": score.score,
                                "url": vacancy.get("alternate_url"),
                            }
                        )
                    if created >= max_drafts:
                        print(f"Reached max_drafts_per_scan={max_drafts}")
                        _send_scan_digest(config, recommended)
                        return recommended
            time.sleep(delay)
    print(f"Scan complete. Drafts created/updated: {created}")
    _send_scan_digest(config, recommended)
    return recommended


def _send_scan_digest(config: dict[str, Any], recommended: list[dict[str, Any]]) -> None:
    try:
        send_telegram_digest(config, recommended)
    except RuntimeError as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)


def _is_token_revoked(exc: HHApiError) -> bool:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    errors = payload.get("errors", [])
    return (
        exc.status_code in {401, 403}
        and (
            payload.get("oauth_error") == "token-revoked"
            or any(isinstance(item, dict) and item.get("value") == "token_revoked" for item in errors)
        )
    )


def cmd_auth_url(config: dict[str, Any], api: HHApiClient) -> None:
    redirect_uri = config.get("hh", {}).get("redirect_uri", "http://localhost:8080/callback")
    print(api.authorization_url(redirect_uri))


def cmd_exchange_code(config: dict[str, Any], api: HHApiClient, code: str) -> None:
    redirect_uri = config.get("hh", {}).get("redirect_uri", "http://localhost:8080/callback")
    token = api.exchange_code(code, redirect_uri)
    print(f"Saved HH OAuth token. expires_in={token.get('expires_in')}")


def cmd_app_token(api: HHApiClient) -> None:
    token = api.get_application_token()
    expires = token.get("expires_in", "not provided")
    print(f"Saved HH application token. expires_in={expires}")


def configure_search_from_profile(config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    target_roles = [str(item) for item in profile.get("target_roles", []) if item]
    preferred = [str(item) for item in profile.get("preferred_keywords", []) if item]
    skills = [str(item) for item in profile.get("skills", []) if item]
    keywords = []
    for item in [*target_roles, *preferred[:6]]:
        if item.lower() not in {existing.lower() for existing in keywords}:
            keywords.append(item)
    if keywords:
        config.setdefault("search", {})["keywords"] = keywords[:12]
    if profile.get("desired_salary"):
        config.setdefault("search", {})["desired_salary"] = profile.get("desired_salary")
    positives = []
    for item in [*preferred, *skills]:
        if item.lower() not in {existing.lower() for existing in positives}:
            positives.append(item)
    if positives:
        config.setdefault("filters", {})["positive_keywords"] = positives[:30]
    if target_roles:
        config.setdefault("filters", {})["target_titles"] = [role.lower() for role in target_roles]
    return config


def cmd_import_resume(user_id: str, resume_path: str) -> None:
    create_user(user_id)
    source = Path(resume_path)
    content = source.read_bytes()
    saved_path = save_uploaded_resume(user_id, source.name, content)
    text = extract_text(saved_path)
    profile = build_profile_from_text(text)
    save_user_profile(user_id, profile)
    config = configure_search_from_profile(load_user_config(user_id), profile)
    save_user_config(user_id, config)
    print(f"Imported resume for user '{user_id}'.")
    print(f"Saved profile: {saved_path.parent.parent / 'resume_profile.json'}")
    print(f"Extracted skills: {', '.join(profile.get('skills', [])[:12])}")


def cmd_set_credentials(user_id: str, client_id: str, client_secret: str, contact_email: str = "") -> None:
    create_user(user_id)
    save_credentials(user_id, client_id, client_secret, contact_email)
    print(f"Saved HH credentials for user '{user_id}'.")


def run_scheduled_scan(
    config: dict[str, Any], profile: dict[str, Any], api: HHApiClient, storage: Storage, interval_minutes: int, once: bool
) -> None:
    if interval_minutes < 5:
        raise ValueError("Schedule interval must be at least 5 minutes")
    while True:
        print(time.strftime("%Y-%m-%d %H:%M:%S") + " Scheduled scan started")
        scan(config, profile, api, storage)
        if once:
            return
        print(f"Next scan in {interval_minutes} minutes. Stop with Ctrl+C.")
        time.sleep(interval_minutes * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HH job apply assistant")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.yaml")
    parser.add_argument("--profile", default=str(PROFILE_PATH), help="Path to resume_profile.json")
    parser.add_argument("--user", default=None, help="User id from data/users")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-url", help="Print OAuth URL")
    exchange = sub.add_parser("exchange-code", help="Exchange OAuth code and store token")
    exchange.add_argument("code")
    sub.add_parser("app-token", help="Get application token for vacancy search")
    sub.add_parser("me", help="Check legacy authorized HH user")
    sub.add_parser("scan", help="Search vacancies, score them, and save draft applications")
    schedule = sub.add_parser("schedule", help="Run vacancy scans repeatedly while this command stays open")
    schedule.add_argument("--interval-minutes", type=int, default=720, help="Interval between scans; minimum 5")
    schedule.add_argument("--once", action="store_true", help="Run one scheduled scan and exit")
    review = sub.add_parser("review", help="Review draft applications")
    review.add_argument("--send", action="store_true", help="Deprecated: applicant API responses are unsupported by HH")
    review.add_argument("--open", action="store_true", help="Open browser for apply URL when choosing [o]")
    run = sub.add_parser("run", help="Scan and then review")
    run.add_argument("--send", action="store_true", help="Deprecated: applicant API responses are unsupported by HH")
    run.add_argument("--open", action="store_true", help="Open browser for apply URL when choosing [o]")
    agent = sub.add_parser("agent", help="Scan, generate letters, open apply pages, and wait for manual submit")
    agent.add_argument("--no-scan", action="store_true", help="Use existing drafts without searching again")
    agent.add_argument("--limit", type=int, default=20, help="Maximum draft applications to process")
    agent.add_argument("--no-open", action="store_true", help="Print apply URLs instead of opening browser")
    web = sub.add_parser("web", help="Start local HTML dashboard")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8787)
    import_resume = sub.add_parser("import-resume", help="Create/update user profile from PDF, DOCX or TXT resume")
    import_resume.add_argument("resume_path")
    import_resume.add_argument("--user", required=True, help="User id to create/update")
    credentials = sub.add_parser("set-credentials", help="Save HH client credentials for a user")
    credentials.add_argument("--user", required=True)
    credentials.add_argument("--client-id", required=True)
    credentials.add_argument("--client-secret", required=True)
    credentials.add_argument("--contact-email", default="", help="Real contact email for HH User-Agent")
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        if args.command == "import-resume":
            cmd_import_resume(args.user, args.resume_path)
            return
        if args.command == "set-credentials":
            cmd_set_credentials(args.user, args.client_id, args.client_secret, args.contact_email)
            return
        if args.command == "web":
            from local_web import run_server

            run_server(args.host, args.port)
            return

        config, profile, storage = load_context(args.config, args.profile, args.user)

        if args.command == "auth-url":
            api = make_api(config, storage, "hh_user")
            cmd_auth_url(config, api)
        elif args.command == "exchange-code":
            api = make_api(config, storage, "hh_user")
            cmd_exchange_code(config, api, args.code)
        elif args.command == "app-token":
            api = make_api(config, storage, "hh_app")
            cmd_app_token(api)
        elif args.command == "me":
            api = make_api(config, storage, "hh_user")
            print(json.dumps(api.me(), ensure_ascii=False, indent=2))
        elif args.command == "scan":
            api = make_api(config, storage, "hh_app")
            scan(config, profile, api, storage)
        elif args.command == "schedule":
            api = make_api(config, storage, "hh_app")
            run_scheduled_scan(config, profile, api, storage, args.interval_minutes, args.once)
        elif args.command == "review":
            api = make_api(config, storage, "hh_app")
            review_drafts(
                storage=storage,
                api=api,
                resume_id=profile.get("hh_resume_id"),
                max_sends_per_day=int(config.get("limits", {}).get("max_sends_per_day", 5)),
                send=args.send,
                open_pages=args.open,
            )
        elif args.command == "run":
            api = make_api(config, storage, "hh_app")
            scan(config, profile, api, storage)
            review_drafts(
                storage=storage,
                api=api,
                resume_id=profile.get("hh_resume_id"),
                max_sends_per_day=int(config.get("limits", {}).get("max_sends_per_day", 5)),
                send=args.send,
                open_pages=args.open,
            )
        elif args.command == "agent":
            api = make_api(config, storage, "hh_app")
            if not args.no_scan:
                scan(config, profile, api, storage)
            agent_apply_loop(
                storage=storage,
                limit=args.limit,
                open_pages=not args.no_open,
            )
    except (HHApiError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
