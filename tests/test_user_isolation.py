from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import users
from main import configure_search_from_profile
from storage import Storage


class UserIsolationTests(unittest.TestCase):
    def test_profile_replaces_template_search_preferences(self) -> None:
        config = {
            "search": {"keywords": ["Data Analyst", "Python"], "desired_salary": 180000},
            "filters": {
                "target_titles": ["data analyst"],
                "positive_keywords": ["sql", "python"],
                "negative_keywords": ["qa"],
            },
        }
        profile = {
            "target_roles": ["UX Researcher"],
            "skills": ["Figma", "User Interviews"],
            "desired_salary": 120000,
        }

        result = configure_search_from_profile(config, profile)

        self.assertEqual(result["search"]["keywords"], ["UX Researcher"])
        self.assertEqual(result["search"]["desired_salary"], 120000)
        self.assertEqual(result["filters"]["target_titles"], ["ux researcher"])
        self.assertEqual(result["filters"]["positive_keywords"], ["Figma", "User Interviews"])
        self.assertEqual(result["filters"]["negative_keywords"], ["qa"])

    def test_new_user_starts_without_candidate_specific_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_root = users.USERS_ROOT
            users.USERS_ROOT = Path(directory) / "users"
            try:
                users.create_user("new-person")
                config = users.load_user_config("new-person")
            finally:
                users.USERS_ROOT = original_root

        self.assertEqual(config["search"]["keywords"], [])
        self.assertEqual(config["search"]["areas"], [])
        self.assertIsNone(config["search"]["desired_salary"])
        self.assertEqual(config["filters"]["target_titles"], [])
        self.assertEqual(config["filters"]["positive_keywords"], [])
        self.assertEqual(config["filters"]["negative_keywords"], [])

    def test_legacy_analyst_template_is_migrated_to_empty_preferences(self) -> None:
        legacy = {
            "search": {"keywords": ["Data Analyst", "Product Analyst", "SQL", "Python", "BI"], "areas": ["1"], "desired_salary": 180000},
            "filters": {
                "target_titles": ["data analyst", "product analyst", "analyst", "bi analyst", "sql analyst"],
                "positive_keywords": ["sql", "python", "dashboard", "tableau", "power bi", "looker", "a/b", "ab test", "product metrics", "etl", "airflow", "pandas", "statistics"],
                "allowed_area_ids": ["1"],
                "max_required_years": 4,
            },
        }

        migrated, changed = users._migrate_legacy_user_config(legacy)

        self.assertTrue(changed)
        self.assertEqual(migrated["search"]["keywords"], [])
        self.assertEqual(migrated["search"]["areas"], [])
        self.assertIsNone(migrated["search"]["desired_salary"])
        self.assertEqual(migrated["filters"]["positive_keywords"], [])
        self.assertEqual(migrated["filters"]["target_titles"], [])

    def test_clearing_vacancies_keeps_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "profile.db")
            storage.save_token("hh_app", {"access_token": "token"})
            storage.upsert_draft({"id": "1", "name": "Old vacancy", "employer": {}}, 90, [], "Letter")

            cleared = storage.clear_vacancies()

            self.assertEqual(cleared, 1)
            self.assertEqual(storage.list_drafts(), [])
            self.assertEqual(storage.load_token("hh_app"), {"access_token": "token"})


if __name__ == "__main__":
    unittest.main()
