from __future__ import annotations

import unittest

from cover_letter import generate_cover_letter_result


class CoverLetterTemplateTests(unittest.TestCase):
    def test_letter_uses_profile_based_template_with_links(self) -> None:
        vacancy = {
            "name": "Product Analyst",
            "employer": {"name": "Example Brand"},
            "description": "Ищем аналитика с SQL, Python и опытом работы с продуктовыми метриками.",
        }
        profile = {
            "name": "Анна Петрова",
            "target_roles": ["Product Analyst"],
            "experience_years": 3,
            "experience_summary": "Провожу продуктовые исследования и помогаю командам принимать решения на основе данных",
            "skills": ["SQL", "Python", "Product metrics"],
            "projects": [
                {
                    "name": "Анализ воронки",
                    "description": "исследовала причины потери пользователей в воронке",
                    "stack": ["SQL", "Python"],
                }
            ],
            "links": {
                "resume": "https://example.org/resume",
                "portfolio": "https://example.org/portfolio",
            },
            "cover_letter": {"tone": "concise"},
        }

        result = generate_cover_letter_result(vacancy, profile)

        self.assertIn("Пишу по вакансии «Product Analyst» в Example Brand.", result.letter)
        self.assertIn("Последние 3 года", result.letter)
        self.assertIn("SQL, Python, Product metrics", result.letter)
        self.assertIn("Анализ воронки", result.letter)
        self.assertIn("резюме: https://example.org/resume", result.letter)
        self.assertIn("портфолио: https://example.org/portfolio", result.letter)
        self.assertIn("Буду рад(а) пообщаться по вакансии!", result.letter)
        self.assertNotIn("числовое утверждение", " ".join(result.quality["warnings"]))

    def test_letter_does_not_invent_experience_years(self) -> None:
        vacancy = {"name": "Data Analyst", "employer": {"name": "Company"}, "description": "Нужны SQL и Python."}
        profile = {
            "name": "Иван",
            "target_roles": ["Data Analyst"],
            "experience_summary": "Работал с аналитическими задачами и отчетностью",
            "skills": ["SQL", "Python"],
        }

        result = generate_cover_letter_result(vacancy, profile)

        self.assertNotRegex(result.letter, r"Последн(?:ие|ий) \d+")
        self.assertIn("Мой релевантный опыт", result.letter)

    def test_custom_greeting_replaces_default_greeting(self) -> None:
        vacancy = {"name": "Data Analyst", "employer": {"name": "Company"}, "description": "Нужны SQL и Python."}
        profile = {
            "name": "Иван",
            "target_roles": ["Data Analyst"],
            "skills": ["SQL", "Python"],
            "experience_summary": "Работал с аналитическими задачами",
            "cover_letter": {"custom_intro": "Анна, добрый день!"},
        }

        result = generate_cover_letter_result(vacancy, profile)

        self.assertTrue(result.letter.startswith("Анна, добрый день!"))
        self.assertNotIn("Здравствуйте!", result.letter)


if __name__ == "__main__":
    unittest.main()
