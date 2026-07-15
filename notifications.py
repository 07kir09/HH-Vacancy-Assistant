from __future__ import annotations

from typing import Any

import requests


def telegram_enabled(config: dict[str, Any]) -> bool:
    telegram = (config.get("notifications") or {}).get("telegram") or {}
    return bool(telegram.get("enabled") and telegram.get("bot_token") and telegram.get("chat_id"))


def send_telegram_digest(config: dict[str, Any], items: list[dict[str, Any]]) -> None:
    """Send only a compact digest. Tokens stay in the local user config."""
    if not telegram_enabled(config) or not items:
        return
    telegram = config["notifications"]["telegram"]
    lines = [f"HH Vacancy Assistant: новых рекомендаций {len(items)}"]
    for item in items[:8]:
        title = str(item.get("title") or "Вакансия")
        company = str(item.get("company") or "")
        score = item.get("score", "?")
        url = str(item.get("url") or "")
        lines.append(f"- {score}/100: {title} | {company}".rstrip())
        if url:
            lines.append(url)
    if len(items) > 8:
        lines.append(f"Еще: {len(items) - 8}")

    response = requests.post(
        f"https://api.telegram.org/bot{telegram['bot_token']}/sendMessage",
        json={"chat_id": str(telegram["chat_id"]), "text": "\n".join(lines), "disable_web_page_preview": True},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram notification failed: {response.status_code} {response.text[:300]}")
