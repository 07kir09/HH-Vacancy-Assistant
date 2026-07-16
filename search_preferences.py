from __future__ import annotations

from copy import deepcopy
from typing import Any


# HH area identifiers for the cities available in the quick-search form.
CITY_OPTIONS = [
    {"id": "1", "name": "Москва"},
    {"id": "2", "name": "Санкт-Петербург"},
    {"id": "3", "name": "Екатеринбург"},
    {"id": "4", "name": "Новосибирск"},
    {"id": "53", "name": "Краснодар"},
    {"id": "66", "name": "Нижний Новгород"},
    {"id": "76", "name": "Ростов-на-Дону"},
    {"id": "78", "name": "Самара"},
    {"id": "88", "name": "Казань"},
]

EXPERIENCE_OPTIONS = [
    {"id": "noExperience", "name": "Без опыта / стажировка"},
    {"id": "between1And3", "name": "1-3 года"},
    {"id": "between3And6", "name": "3-6 лет"},
]

EMPLOYMENT_OPTIONS = [
    {"id": "full", "name": "Полная занятость"},
    {"id": "part", "name": "Частичная занятость"},
    {"id": "project", "name": "Проектная работа"},
    {"id": "probation", "name": "Стажировка"},
]

ENGLISH_OPTIONS = [
    {"id": "", "name": "Не учитывать"},
    {"id": "a1", "name": "A1 - начальный"},
    {"id": "a2", "name": "A2 - базовый"},
    {"id": "b1", "name": "B1 - intermediate"},
    {"id": "b2", "name": "B2 - upper-intermediate"},
    {"id": "c1", "name": "C1 - advanced"},
    {"id": "c2", "name": "C2 - proficiency"},
]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return _strings(value)
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def form_options() -> dict[str, list[dict[str, str]]]:
    return {
        "cities": CITY_OPTIONS,
        "experience": EXPERIENCE_OPTIONS,
        "employment": EMPLOYMENT_OPTIONS,
        "english": ENGLISH_OPTIONS,
    }


def preferences_from_config(config: dict[str, Any]) -> dict[str, Any]:
    search = config.get("search") or {}
    filters = config.get("filters") or {}
    formats = {str(item).upper() for item in _strings(search.get("work_format"))}
    if formats == {"REMOTE", "HYBRID"}:
        work_format = "remote"
    elif formats == {"ON_SITE"}:
        work_format = "office"
    else:
        work_format = "any"

    negative = _strings(filters.get("negative_keywords"))
    if not negative:
        negative = _split_text(search.get("excluded_text"))
    return {
        "roles": _strings(search.get("keywords")),
        "areas": _strings(search.get("areas")),
        "desired_salary": search.get("desired_salary") or "",
        "only_with_salary": bool(search.get("only_with_salary", False)),
        "work_format": work_format,
        "allow_relocation": bool(filters.get("allow_relocation", True)),
        "english_level": str(filters.get("english_level") or "").lower(),
        "experience": _strings(search.get("experience")),
        "employment": _strings(search.get("employment")),
        "blocked_companies": _strings(filters.get("blocked_companies")),
        "negative_keywords": negative,
        "block_recruiting_agencies": bool(filters.get("block_recruiting_agencies", True)),
    }


def apply_preferences(config: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Apply the user-facing search form without removing advanced YAML settings."""
    result = deepcopy(config)
    search = result.setdefault("search", {})
    filters = result.setdefault("filters", {})

    roles = _split_text(preferences.get("roles"))
    if not roles:
        raise ValueError("Добавь хотя бы одну роль или ключевое слово для поиска.")
    search["keywords"] = roles[:20]
    filters["target_titles"] = [role.lower() for role in roles[:20]]

    allowed_city_ids = {item["id"] for item in CITY_OPTIONS}
    areas = [area for area in _strings(preferences.get("areas")) if area in allowed_city_ids]
    search["areas"] = areas
    filters["allowed_area_ids"] = list(areas)

    salary = preferences.get("desired_salary")
    if salary in (None, ""):
        search["desired_salary"] = None
    else:
        try:
            parsed_salary = int(str(salary).replace(" ", ""))
        except ValueError as exc:
            raise ValueError("Зарплата должна быть целым числом в рублях.") from exc
        if parsed_salary < 0:
            raise ValueError("Зарплата не может быть отрицательной.")
        search["desired_salary"] = parsed_salary
    search["only_with_salary"] = bool(preferences.get("only_with_salary", False))

    search["experience"] = [
        item for item in _strings(preferences.get("experience")) if item in {option["id"] for option in EXPERIENCE_OPTIONS}
    ]
    search["employment"] = [
        item for item in _strings(preferences.get("employment")) if item in {option["id"] for option in EMPLOYMENT_OPTIONS}
    ]

    format_value = str(preferences.get("work_format") or "any")
    if format_value == "remote":
        search["work_format"] = ["REMOTE", "HYBRID"]
        filters["allow_remote"] = True
    elif format_value == "office":
        search["work_format"] = ["ON_SITE"]
        filters["allow_remote"] = False
    else:
        search["work_format"] = ["REMOTE", "HYBRID", "ON_SITE"]
        filters["allow_remote"] = True
    filters["allow_relocation"] = bool(preferences.get("allow_relocation", True))

    english_level = str(preferences.get("english_level") or "").lower()
    valid_english = {option["id"] for option in ENGLISH_OPTIONS}
    filters["english_level"] = english_level if english_level in valid_english else ""
    filters["blocked_companies"] = _split_text(preferences.get("blocked_companies"))[:100]
    filters["negative_keywords"] = _split_text(preferences.get("negative_keywords"))[:100]
    search["excluded_text"] = ",".join(filters["negative_keywords"])
    filters["block_recruiting_agencies"] = bool(preferences.get("block_recruiting_agencies", True))
    return result
