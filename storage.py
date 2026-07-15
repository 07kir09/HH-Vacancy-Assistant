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
            self._ensure_vacancy_columns(conn)

    @staticmethod
    def _ensure_vacancy_columns(conn: sqlite3.Connection) -> None:
        """Add fields introduced after the first local database version."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(vacancies)").fetchall()}
        additions = {
            "search_strategy": "TEXT",
            "recommendation": "TEXT NOT NULL DEFAULT 'review'",
            "feedback": "TEXT",
            "notes": "TEXT",
            "opened_at": "TEXT",
            "last_seen_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE vacancies ADD COLUMN {name} {definition}")

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
        *,
        strategy_name: str = "Основной поиск",
        recommendation: str = "review",
    ) -> bool:
        vacancy_id = str(vacancy["id"])
        employer = vacancy.get("employer") or {}
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT status, feedback, notes, opened_at FROM vacancies WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()
            if existing and existing["status"] in {"sent", "skipped", "blocked"}:
                return False
            is_new = existing is None
            conn.execute(
                """
                INSERT INTO vacancies(
                    vacancy_id, title, company, score, status, alternate_url,
                    apply_url, letter, score_reasons_json, raw_json, error_text,
                    created_at, updated_at, sent_at, search_strategy, recommendation,
                    feedback, notes, opened_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vacancy_id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    score = excluded.score,
                    status = CASE
                        WHEN vacancies.status IN ('sent', 'skipped', 'blocked') THEN vacancies.status
                        ELSE excluded.status
                    END,
                    alternate_url = excluded.alternate_url,
                    apply_url = excluded.apply_url,
                    letter = excluded.letter,
                    score_reasons_json = excluded.score_reasons_json,
                    raw_json = excluded.raw_json,
                    error_text = NULL,
                    search_strategy = excluded.search_strategy,
                    recommendation = excluded.recommendation,
                    updated_at = excluded.updated_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    vacancy_id,
                    vacancy.get("name", ""),
                    employer.get("name", ""),
                    score,
                    recommendation,
                    vacancy.get("alternate_url"),
                    vacancy.get("apply_alternate_url"),
                    letter,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(vacancy, ensure_ascii=False),
                    now,
                    now,
                    strategy_name,
                    recommendation,
                    existing["feedback"] if existing else None,
                    existing["notes"] if existing else None,
                    existing["opened_at"] if existing else None,
                    now,
                ),
            )
        return is_new

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

    def mark_opened(self, vacancy_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE vacancies SET opened_at = ?, updated_at = ? WHERE vacancy_id = ?",
                (now, now, vacancy_id),
            )

    def update_letter(self, vacancy_id: str, letter: str) -> None:
        if not letter.strip():
            raise ValueError("Cover letter cannot be empty")
        with self.connect() as conn:
            conn.execute(
                "UPDATE vacancies SET letter = ?, updated_at = ? WHERE vacancy_id = ?",
                (letter.strip(), utc_now(), vacancy_id),
            )

    def set_feedback(self, vacancy_id: str, feedback: str, notes: str = "") -> None:
        if feedback not in {"relevant", "not_relevant", "neutral"}:
            raise ValueError("Unsupported feedback")
        with self.connect() as conn:
            conn.execute(
                "UPDATE vacancies SET feedback = ?, notes = ?, updated_at = ? WHERE vacancy_id = ?",
                (feedback, notes.strip()[:1000] or None, utc_now(), vacancy_id),
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
                WHERE status IN ('recommended', 'review', 'draft', 'error')
                ORDER BY CASE status WHEN 'recommended' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,
                         score DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def statistics(self) -> dict[str, Any]:
        with self.connect() as conn:
            counts = {
                row["status"]: int(row["count"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM vacancies GROUP BY status"
                ).fetchall()
            }
            feedback = {
                row["feedback"]: int(row["count"])
                for row in conn.execute(
                    "SELECT feedback, COUNT(*) AS count FROM vacancies WHERE feedback IS NOT NULL GROUP BY feedback"
                ).fetchall()
            }
            average = conn.execute("SELECT AVG(score) AS value FROM vacancies").fetchone()["value"]
            sent_week = conn.execute(
                "SELECT COUNT(*) AS count FROM vacancies WHERE status = 'sent' AND sent_at >= datetime('now', '-7 days')"
            ).fetchone()["count"]
        return {
            "counts": counts,
            "feedback": feedback,
            "average_score": round(float(average or 0), 1),
            "sent_last_7_days": int(sent_week or 0),
        }

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
