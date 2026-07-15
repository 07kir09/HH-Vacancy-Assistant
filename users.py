from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent
USERS_ROOT = ROOT / "data" / "users"
DEFAULT_CONFIG = ROOT / "config.yaml"


def slugify_user(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._").lower()
    if not slug:
        raise ValueError("User id must contain at least one latin letter, digit, dot, dash or underscore")
    return slug


def user_dir(user_id: str) -> Path:
    return USERS_ROOT / slugify_user(user_id)


def ensure_user(user_id: str) -> Path:
    path = user_dir(user_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "uploads").mkdir(exist_ok=True)
    return path


def list_users() -> list[str]:
    if not USERS_ROOT.exists():
        return []
    return sorted(path.name for path in USERS_ROOT.iterdir() if path.is_dir())


def delete_user(user_id: str) -> None:
    """Remove one local user and all of that user's private local data."""
    path = user_dir(user_id)
    root = USERS_ROOT.resolve()
    if not path.exists():
        raise ValueError("Пользователь не найден.")
    if path.resolve().parent != root:
        raise ValueError("Небезопасный путь пользователя.")
    shutil.rmtree(path)


def create_user(user_id: str) -> Path:
    path = ensure_user(user_id)
    config_path = path / "config.yaml"
    if not config_path.exists():
        shutil.copyfile(DEFAULT_CONFIG, config_path)
        config = load_user_config(user_id)
        config.setdefault("storage", {})["sqlite_path"] = str(path / "job_apply_bot.db")
        save_user_config(user_id, config)
    profile_path = path / "resume_profile.json"
    if not profile_path.exists():
        profile_path.write_text(
            json.dumps(
                {
                    "name": "",
                    "hh_resume_id": "",
                    "profile_reviewed": False,
                    "target_roles": [],
                    "city": "Moscow",
                    "desired_salary": 100000,
                    "experience_summary": "",
                    "skills": [],
                    "strengths": [],
                    "links": {},
                    "cover_letter": {"language": "ru", "tone": "concise", "custom_intro": ""},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return path


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_user_config(user_id: str) -> dict[str, Any]:
    path = ensure_user(user_id) / "config.yaml"
    if not path.exists():
        create_user(user_id)
    return load_yaml(path)


def save_user_config(user_id: str, config: dict[str, Any]) -> None:
    path = ensure_user(user_id) / "config.yaml"
    save_yaml(path, config)


def load_user_profile(user_id: str) -> dict[str, Any]:
    path = ensure_user(user_id) / "resume_profile.json"
    if not path.exists():
        create_user(user_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_user_profile(user_id: str, profile: dict[str, Any]) -> None:
    path = ensure_user(user_id) / "resume_profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def credentials_path(user_id: str) -> Path:
    return ensure_user(user_id) / "credentials.json"


def save_credentials(user_id: str, client_id: str, client_secret: str, contact_email: str = "") -> None:
    path = credentials_path(user_id)
    contact_email = contact_email.strip()
    data = {
        "HH_CLIENT_ID": client_id.strip(),
        "HH_CLIENT_SECRET": client_secret.strip(),
        "HH_CONTACT_EMAIL": contact_email,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if contact_email:
        config = load_user_config(user_id)
        config.setdefault("hh", {})["user_agent"] = f"HH-Vacancy-Assistant/1.0 ({contact_email})"
        save_user_config(user_id, config)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_credentials(user_id: str) -> dict[str, str]:
    path = credentials_path(user_id)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "HH_CLIENT_ID": str(data.get("HH_CLIENT_ID", "")).strip(),
        "HH_CLIENT_SECRET": str(data.get("HH_CLIENT_SECRET", "")).strip(),
        "HH_CONTACT_EMAIL": str(data.get("HH_CONTACT_EMAIL", "")).strip(),
    }


def runtime_config_for_user(user_id: str) -> dict[str, Any]:
    config = load_user_config(user_id)
    creds = load_credentials(user_id)
    profile = load_user_profile(user_id)
    contact_email = creds.get("HH_CONTACT_EMAIL") or str((profile.get("links") or {}).get("email", "")).strip()
    config.setdefault("hh", {})
    if creds.get("HH_CLIENT_ID"):
        config["hh"]["client_id"] = creds["HH_CLIENT_ID"]
    if creds.get("HH_CLIENT_SECRET"):
        config["hh"]["client_secret"] = creds["HH_CLIENT_SECRET"]
    if contact_email:
        config["hh"]["user_agent"] = f"HH-Vacancy-Assistant/1.0 ({contact_email})"
    config.setdefault("storage", {})["sqlite_path"] = str(user_dir(user_id) / "job_apply_bot.db")
    return config


def save_uploaded_resume(user_id: str, filename: str, content: bytes) -> Path:
    safe_name = Path(filename).name or "resume"
    path = ensure_user(user_id) / "uploads" / safe_name
    path.write_bytes(content)
    return path
