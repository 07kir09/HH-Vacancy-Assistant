from __future__ import annotations

import json
import shutil
import subprocess
import webbrowser
from typing import Any

from hh_api import HHApiClient, HHApiError
from storage import Storage


def _copy_to_clipboard(text: str) -> bool:
    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        return True
    return False


def _print_draft(row: Any) -> None:
    reasons = json.loads(row["score_reasons_json"] or "[]")
    print("=" * 80)
    print(f"{row['title']} | {row['company']} | score {row['score']}")
    if row["alternate_url"]:
        print(f"Vacancy: {row['alternate_url']}")
    if row["apply_url"]:
        print(f"Apply:   {row['apply_url']}")
    if reasons:
        print("Reasons: " + "; ".join(reasons[:8]))
    if row["error_text"]:
        print(f"Last error: {row['error_text']}")
    print("-" * 80)
    print(row["letter"] or "")
    print("-" * 80)


def review_drafts(
    *,
    storage: Storage,
    api: HHApiClient | None,
    resume_id: str | None,
    max_sends_per_day: int,
    send: bool,
    open_pages: bool,
) -> None:
    drafts = storage.list_drafts(limit=100)
    if not drafts:
        print("No draft applications found. Run: python main.py scan")
        return

    sent_today = storage.count_sent_today()
    for row in drafts:
        _print_draft(row)
        if sent_today >= max_sends_per_day:
            print(f"Daily send limit reached: {sent_today}/{max_sends_per_day}")
            break

        prompt = "[o] open page, [c] copy letter, [s] send via API, [k] skip, [enter] next, [q] quit: "
        action = input(prompt).strip().lower()
        if action == "q":
            break
        if action == "k":
            storage.mark_status(row["vacancy_id"], "skipped")
            continue
        if action == "c":
            copied = _copy_to_clipboard(row["letter"] or "")
            print("Copied to clipboard." if copied else "Clipboard helper is not available on this system.")
            continue
        if action == "o":
            url = row["apply_url"] or row["alternate_url"]
            if url and open_pages:
                webbrowser.open(url)
                _copy_to_clipboard(row["letter"] or "")
                print("Opened apply page and copied the letter where clipboard is available.")
            elif url:
                print(url)
            continue
        if action == "s":
            print("HH no longer supports applicant API responses. Use [o] to open apply page and paste the copied letter.")


def agent_apply_loop(
    *,
    storage: Storage,
    limit: int,
    open_pages: bool = True,
) -> None:
    drafts = storage.list_drafts(limit=limit)
    if not drafts:
        print("No draft applications found. Run: python main.py scan")
        return

    for index, row in enumerate(drafts, start=1):
        _print_draft(row)
        url = row["apply_url"] or row["alternate_url"]
        if row["letter"]:
            copied = _copy_to_clipboard(row["letter"])
            print("Letter copied to clipboard." if copied else "Clipboard helper is not available on this system.")
        if url and open_pages:
            webbrowser.open(url)
            print(f"Opened apply page {index}/{len(drafts)}.")
        elif url:
            print(f"Apply URL: {url}")

        prompt = "[a] mark applied, [k] skip, [c] copy again, [enter] next, [q] quit: "
        while True:
            action = input(prompt).strip().lower()
            if action == "q":
                return
            if action == "a":
                storage.mark_sent(row["vacancy_id"])
                print("Marked as applied.")
                break
            if action == "k":
                storage.mark_status(row["vacancy_id"], "skipped")
                print("Skipped.")
                break
            if action == "c":
                copied = _copy_to_clipboard(row["letter"] or "")
                print("Copied to clipboard." if copied else "Clipboard helper is not available on this system.")
                continue
            if action == "":
                break
            print("Unknown action.")
