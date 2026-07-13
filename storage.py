from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    provider TEXT PRIMARY KEY,
                    token_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vacancies (
                    vacancy_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT,
                    score INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    alternate_url TEXT,
                    apply_url TEXT,
                    letter TEXT,
                    score_reasons_json TEXT,
                    raw_json TEXT,
                    error_text TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT
                )
                """
            )

    def save_token(self, provider: str, token: dict[str, Any]) -> None:
        payload = json.dumps(token, ensure_ascii=False)
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tokens(provider, token_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    token_json = excluded.token_json,
                    updated_at = excluded.updated_at
                """,
                (provider, payload, now),
            )

    def load_token(self, provider: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT token_json FROM tokens WHERE provider = ?",
                (provider,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["token_json"])

    def get_vacancy(self, vacancy_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM vacancies WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()

    def has_terminal_status(self, vacancy_id: str) -> bool:
        row = self.get_vacancy(vacancy_id)
        return bool(row and row["status"] in {"sent", "skipped", "blocked"})

    def upsert_draft(
        self,
        vacancy: dict[str, Any],
        score: int,
        reasons: list[str],
        letter: str,
    ) -> None:
        vacancy_id = str(vacancy["id"])
        employer = vacancy.get("employer") or {}
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT status FROM vacancies WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()
            if existing and existing["status"] in {"sent", "skipped", "blocked"}:
                return
            conn.execute(
                """
                INSERT INTO vacancies(
                    vacancy_id, title, company, score, status, alternate_url,
                    apply_url, letter, score_reasons_json, raw_json, error_text,
                    created_at, updated_at, sent_at
                )
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                ON CONFLICT(vacancy_id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    score = excluded.score,
                    status = 'draft',
                    alternate_url = excluded.alternate_url,
                    apply_url = excluded.apply_url,
                    letter = excluded.letter,
                    score_reasons_json = excluded.score_reasons_json,
                    raw_json = excluded.raw_json,
                    error_text = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    vacancy_id,
                    vacancy.get("name", ""),
                    employer.get("name", ""),
                    score,
                    vacancy.get("alternate_url"),
                    vacancy.get("apply_alternate_url"),
                    letter,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(vacancy, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def mark_status(self, vacancy_id: str, status: str, error_text: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE vacancies
                SET status = ?, error_text = ?, updated_at = ?
                WHERE vacancy_id = ?
                """,
                (status, error_text, utc_now(), vacancy_id),
            )

    def mark_sent(self, vacancy_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE vacancies
                SET status = 'sent', sent_at = ?, updated_at = ?, error_text = NULL
                WHERE vacancy_id = ?
                """,
                (now, now, vacancy_id),
            )

    def count_sent_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM vacancies
                WHERE status = 'sent' AND substr(sent_at, 1, 10) = ?
                """,
                (today,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def list_drafts(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM vacancies
                WHERE status IN ('draft', 'error')
                ORDER BY score DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def list_recent(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM vacancies
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)
