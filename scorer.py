from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.parts)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(value)
    return parser.get_text()


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def field_name(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    return str(item.get("name") or item.get("id") or "")


def list_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names: list[str] = []
    for item in values:
        if isinstance(item, dict):
            value = field_name(item)
            if value:
                names.append(value)
    return names


@dataclass(frozen=True)
class ScoreResult:
    score: int
    reasons: list[str]
    blocked: bool = False

    @property
    def recommendation(self) -> str:
        return "recommended" if self.score >= 80 and not self.blocked else "review"


def vacancy_text(vacancy: dict[str, Any]) -> str:
    parts = [
        vacancy.get("name", ""),
        strip_html(vacancy.get("description")),
        field_name(vacancy.get("experience")),
        field_name(vacancy.get("employment")),
        field_name(vacancy.get("schedule")),
        " ".join(list_names(vacancy.get("work_format"))),
        " ".join(list_names(vacancy.get("professional_roles"))),
        " ".join(item.get("name", "") for item in vacancy.get("key_skills", []) if isinstance(item, dict)),
    ]
    return norm(" ".join(parts))


def contains_any(text: str, keywords: list[str]) -> list[str]:
    hits = []
    for keyword in keywords:
        needle = norm(keyword)
        if not needle:
            continue
        # Short skills such as R or C need word boundaries.
        matched = (
            bool(re.search(rf"(?<!\\w){re.escape(needle)}(?!\\w)", text))
            if len(needle) <= 2
            else needle in text
        )
        if matched:
            hits.append(keyword)
    return hits


def required_years(text: str) -> int | None:
    patterns = [
        r"(?:от|from|at least|minimum|not less than)\s+(\d+)\s+(?:лет|год|years?)",
        r"(\d+)\s*\+\s*(?:лет|years?)",
        r"(\d+)\s*(?:лет|years?)\s*(?:опыта|experience)",
        r"(\d+)\s*-\s*(\d+)\s*(?:лет|years?)",
    ]
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            groups = [int(g) for g in match.groups() if g and g.isdigit()]
            if groups:
                values.append(max(groups))
    return max(values) if values else None


def salary_bounds(vacancy: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    salary = vacancy.get("salary_range") or vacancy.get("salary") or {}
    if not isinstance(salary, dict):
        return None, None, None
    return salary.get("from"), salary.get("to"), salary.get("currency")


def is_remote(vacancy: dict[str, Any], text: str) -> bool:
    schedule = norm(field_name(vacancy.get("schedule")))
    formats = norm(" ".join(list_names(vacancy.get("work_format"))))
    return any(
        marker in " ".join([schedule, formats, text])
        for marker in ["remote", "удален", "удалён", "дистанц", "из дома", "гибрид", "hybrid"]
    )


def has_relocation_signal(text: str) -> bool:
    return any(marker in text for marker in ["релокац", "relocation", "переезд", "relocate"])


def score_vacancy(
    vacancy: dict[str, Any],
    profile: dict[str, Any],
    filters: dict[str, Any],
) -> ScoreResult:
    reasons: list[str] = []
    text = vacancy_text(vacancy)
    title = norm(vacancy.get("name"))
    score = 45

    if filters.get("block_archived", True) and vacancy.get("archived"):
        return ScoreResult(0, ["Исключено: вакансия в архиве."], True)
    if filters.get("block_already_applied", True) and "got_response" in (vacancy.get("relations") or []):
        return ScoreResult(0, ["Исключено: по данным HH отклик уже был."], True)
    if filters.get("block_tests", False) and vacancy.get("has_test"):
        return ScoreResult(0, ["Исключено: в вакансии есть тестовое задание."], True)

    negative_hits = contains_any(text, filters.get("negative_keywords", []))
    if negative_hits:
        return ScoreResult(0, [f"Исключено по стоп-словам: {', '.join(negative_hits[:5])}."], True)

    years = required_years(text)
    max_years = int(filters.get("max_required_years", 4))
    if years and years > max_years:
        return ScoreResult(0, [f"Исключено: требуется около {years}+ лет опыта."], True)

    experience_id = (vacancy.get("experience") or {}).get("id")
    if experience_id == "moreThan6":
        return ScoreResult(0, ["Исключено: HH указывает опыт более 6 лет."], True)
    if experience_id in {"noExperience", "between1And3", "between3And6"}:
        score += 10
        reasons.append("Опыт: диапазон вакансии соответствует заданному уровню.")

    target_hits = contains_any(title, filters.get("target_titles", []))
    if target_hits:
        score += 15
        reasons.append(f"Название совпадает с целевой ролью: {', '.join(target_hits[:3])}.")

    profile_skills = [str(skill) for skill in profile.get("skills", [])]
    skill_hits = contains_any(text, profile_skills)
    if skill_hits:
        score += min(25, len(skill_hits) * 4)
        reasons.append(f"Совпадают навыки: {', '.join(skill_hits[:6])}.")

    positive_hits = contains_any(text, filters.get("positive_keywords", []))
    if positive_hits:
        score += min(15, len(positive_hits) * 3)
        reasons.append(f"Есть приоритетные требования: {', '.join(positive_hits[:6])}.")

    salary_from, salary_to, currency = salary_bounds(vacancy)
    desired = int(profile.get("desired_salary") or 0)
    allow_no_salary = bool(filters.get("allow_no_salary", True))
    if desired and (salary_from or salary_to):
        if salary_to and salary_to < desired * 0.85:
            return ScoreResult(0, [f"Исключено: верхняя граница зарплаты {salary_to} {currency} ниже цели."], True)
        if salary_from and salary_from >= desired * 0.85:
            score += 10
            reasons.append(f"Зарплата выглядит подходящей: от {salary_from} {currency}.")
    elif desired and not allow_no_salary:
        return ScoreResult(0, ["Исключено: в вакансии не указана зарплата."], True)
    else:
        reasons.append("Зарплата не указана, поэтому не учитывалась в оценке.")

    area = vacancy.get("area") or {}
    area_name = field_name(area)
    area_id = str(area.get("id") or "")
    remote = is_remote(vacancy, text)
    relocation = has_relocation_signal(text)
    allowed_area_ids = {str(item) for item in filters.get("allowed_area_ids", [])}
    if allowed_area_ids and area_id not in allowed_area_ids and not remote and not relocation:
        return ScoreResult(0, [f"Исключено: локация «{area_name or area_id}» не входит в разрешенные."], True)

    if area_name:
        reasons.append(f"Локация: {area_name}.")
    if remote:
        if not filters.get("allow_remote", True):
            return ScoreResult(0, ["Исключено: удаленный или гибридный формат отключен в настройках."], True)
        score += 10
        reasons.append("Формат: найден удаленный или гибридный вариант.")
    if relocation and filters.get("allow_relocation", True):
        score += 5
        reasons.append("Формат: есть сигнал о возможности релокации.")

    employer = vacancy.get("employer") or {}
    if employer.get("trusted"):
        score += 3
        reasons.append("Работодатель отмечен HH как проверенный.")

    score = max(0, min(100, score))
    if score < int(filters.get("min_score", 65)):
        reasons.append("Итог ниже минимального score, указанного в настройках.")
    return ScoreResult(score, reasons, False)
