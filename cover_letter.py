from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scorer import vacancy_text


# Canonical skills and their common forms in Russian and English vacancies.
SKILL_PATTERNS: dict[str, tuple[str, ...]] = {
    "SQL": ("sql",),
    "Python": ("python",),
    "PostgreSQL": ("postgresql", "postgres"),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "Power BI": ("power bi",),
    "Tableau": ("tableau",),
    "Excel": ("excel",),
    "A/B testing": ("a/b", "ab test", "a/b test", "ab-тест", "а/б"),
    "Product metrics": ("product metrics", "продуктов", "метрик"),
    "Statistics": ("statistics", "статист"),
    "ETL": ("etl",),
    "Airflow": ("airflow",),
    "NLP": ("nlp", "natural language", "текстов"),
    "PyTorch": ("pytorch",),
    "Transformers": ("transformer", "transformers", "bert"),
    "Docker": ("docker",),
    "FastAPI": ("fastapi",),
}


@dataclass(frozen=True)
class LetterResult:
    letter: str
    quality: dict[str, Any]


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _text_has(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    normalized = _norm(text)
    for needle in needles:
        value = _norm(needle)
        if not value:
            continue
        if len(value) <= 2:
            if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", normalized):
                return True
        elif value in normalized:
            return True
    return False


def _clip(value: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip().rstrip(".")
    if len(compact) <= limit:
        return compact
    clipped = compact[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}..."


def _profile_skills(profile: dict[str, Any]) -> list[str]:
    skills = [str(item).strip() for item in profile.get("skills", []) if str(item).strip()]
    known = {name.lower(): name for name in SKILL_PATTERNS}
    normalized: list[str] = []
    for skill in skills:
        canonical = known.get(skill.lower(), skill)
        if canonical.lower() not in {item.lower() for item in normalized}:
            normalized.append(canonical)
    return normalized


def _vacancy_requirements(vacancy: dict[str, Any]) -> list[str]:
    text = vacancy_text(vacancy)
    return [name for name, patterns in SKILL_PATTERNS.items() if _text_has(text, patterns)]


def _matched_requirements(vacancy: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    text = vacancy_text(vacancy)
    profile_skills = _profile_skills(profile)
    result: list[str] = []
    for skill in profile_skills:
        patterns = SKILL_PATTERNS.get(skill, (skill,))
        if _text_has(text, patterns):
            result.append(skill)
    return result[:5]


def _project_text(project: dict[str, Any]) -> str:
    return " ".join(
        [
            str(project.get("name", "")),
            str(project.get("description", "")),
            " ".join(str(item) for item in project.get("stack", []) if item),
        ]
    )


def _project_score(project: dict[str, Any], vacancy: dict[str, Any], matched: list[str]) -> int:
    project_text = _norm(_project_text(project))
    score = sum(4 for skill in matched if _text_has(project_text, SKILL_PATTERNS.get(skill, (skill,))))
    title = _norm(vacancy.get("name"))
    for marker in ("продукт", "product", "финанс", "risk", "nlp", "dashboard", "дашборд", "etl"):
        if marker in title and marker in project_text:
            score += 3
    return score


def _best_project(vacancy: dict[str, Any], profile: dict[str, Any], matched: list[str]) -> dict[str, Any] | None:
    projects = [item for item in profile.get("projects", []) if isinstance(item, dict) and _project_text(item).strip()]
    if not projects:
        return None
    ranked = sorted(projects, key=lambda item: _project_score(item, vacancy, matched), reverse=True)
    return ranked[0] if _project_score(ranked[0], vacancy, matched) > 0 else None


def _best_experience_fact(profile: dict[str, Any]) -> str:
    for item in profile.get("experience", []):
        if not isinstance(item, dict):
            continue
        highlights = item.get("highlights", [])
        if isinstance(highlights, list):
            for highlight in highlights:
                value = _clip(str(highlight), 240)
                if value:
                    return value
    return ""


def _best_cover_fact(profile: dict[str, Any], matched: list[str]) -> str:
    facts = [_clip(str(item), 240) for item in profile.get("cover_letter_facts", []) if str(item).strip()]
    if not facts:
        return ""
    for fact in facts:
        if any(_text_has(fact, SKILL_PATTERNS.get(skill, (skill,))) for skill in matched):
            return fact
    return facts[0]


def _focus_sentence(vacancy: dict[str, Any]) -> str:
    text = vacancy_text(vacancy)
    if _text_has(text, ("a/b", "ab test", "гипотез", "product metrics", "метрик")):
        return "Особенно интересны задачи, где аналитика помогает команде проверять гипотезы и принимать продуктовые решения."
    if _text_has(text, ("dashboard", "дашборд", "tableau", "power bi", "visual")):
        return "Интересны задачи, в которых данные превращаются в понятные для команды метрики и дашборды."
    if _text_has(text, ("nlp", "transformer", "bert", "текстов")):
        return "Интересны задачи с текстовыми данными, качеством моделей и понятной интерпретацией результата."
    return "Интересна возможность работать с данными не изолированно, а в контексте реальных задач команды."


def _tone(profile: dict[str, Any]) -> str:
    value = str((profile.get("cover_letter") or {}).get("tone", "concise")).lower()
    return value if value in {"concise", "standard", "direct"} else "concise"


def generate_cover_letter_result(vacancy: dict[str, Any], profile: dict[str, Any]) -> LetterResult:
    title = str(vacancy.get("name") or "вакансия")
    company = str((vacancy.get("employer") or {}).get("name") or "вашей команде")
    name = str(profile.get("name") or "").strip()
    custom_intro = str((profile.get("cover_letter") or {}).get("custom_intro") or "").strip()
    matched = _matched_requirements(vacancy, profile)
    project = _best_project(vacancy, profile, matched)
    experience_fact = _best_experience_fact(profile)
    cover_fact = _best_cover_fact(profile, matched)
    summary = _clip(str(profile.get("experience_summary") or ""), 260)
    tone = _tone(profile)

    paragraphs = ["Здравствуйте!"]
    if custom_intro:
        paragraphs.append(custom_intro)
    elif name:
        paragraphs.append(f"Меня зовут {name}. Заинтересовала вакансия «{title}» в {company}.")
    else:
        paragraphs.append(f"Заинтересовала вакансия «{title}» в {company}.")

    if matched:
        paragraphs.append(
            "По описанию вижу предметное совпадение: в резюме указаны "
            + ", ".join(matched)
            + ", которые требуются для этой роли."
        )
    elif summary:
        paragraphs.append(f"Мой профиль: {summary}.")

    if project:
        project_name = _clip(str(project.get("name") or "проект"), 90)
        project_description = _clip(str(project.get("description") or ""), 280)
        stack = [str(item).strip() for item in project.get("stack", []) if str(item).strip()]
        evidence = f"В релевантном проекте «{project_name}»"
        if project_description:
            evidence += f" {project_description.lower()}"
        if stack:
            evidence += f". Использовал: {', '.join(stack[:4])}"
        paragraphs.append(evidence.rstrip(".") + ".")
    elif experience_fact:
        paragraphs.append(f"Из опыта: {experience_fact}.")
    elif cover_fact:
        paragraphs.append(f"Релевантный факт из профиля: {cover_fact}.")
    elif summary and matched:
        paragraphs.append(f"Мой профиль: {summary}.")

    if tone == "standard":
        paragraphs.append(_focus_sentence(vacancy))
    elif tone == "direct":
        paragraphs.append("Буду рад обсудить, какие задачи этой роли смогу закрыть в первые месяцы работы.")

    paragraphs.append("Буду рад обсудить, как мой опыт может быть полезен вашей команде.")
    letter = "\n\n".join(item.strip() for item in paragraphs if item.strip())
    return LetterResult(letter=letter, quality=check_cover_letter_quality(letter, vacancy, profile))


def generate_cover_letter(vacancy: dict[str, Any], profile: dict[str, Any]) -> str:
    """Compatibility helper for callers that only need the prepared text."""
    return generate_cover_letter_result(vacancy, profile).letter


def check_cover_letter_quality(letter: str, vacancy: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    text = letter.strip()
    title = _norm(vacancy.get("name"))
    company = _norm((vacancy.get("employer") or {}).get("name"))
    normalized = _norm(text)
    matched = _matched_requirements(vacancy, profile)
    vacancy_requirements = _vacancy_requirements(vacancy)
    profile_skills = _profile_skills(profile)
    used_known_skills = [skill for skill, patterns in SKILL_PATTERNS.items() if _text_has(normalized, patterns)]
    unsupported = [skill for skill in used_known_skills if skill.lower() not in {item.lower() for item in profile_skills}]
    word_count = len(re.findall(r"\S+", text))
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    has_evidence = bool(
        _best_project(vacancy, profile, matched)
        or _best_experience_fact(profile)
        or _best_cover_fact(profile, matched)
        or profile.get("experience_summary")
    )
    personalized = bool(title and title in normalized) and (not company or company in normalized)
    length_ok = 55 <= word_count <= 230 and 350 <= len(text) <= 1800
    checks = [
        {"id": "personalization", "label": "Указаны вакансия и компания", "passed": personalized},
        {"id": "requirements", "label": "Есть совпадение с требованиями вакансии", "passed": bool(matched)},
        {"id": "evidence", "label": "Есть подтверждение опытом, проектом или профилем", "passed": has_evidence},
        {"id": "length", "label": "Длина подходит для сопроводительного письма", "passed": length_ok},
        {"id": "structure", "label": "Письмо разбито на читаемые абзацы", "passed": len(paragraphs) >= 3},
        {"id": "facts", "label": "Не найдены навыки вне профиля", "passed": not unsupported},
    ]
    score = sum((20, 25, 20, 15, 10, 10)[index] for index, check in enumerate(checks) if check["passed"])
    warnings: list[str] = []
    if not personalized:
        warnings.append("Добавь название вакансии и компанию, чтобы письмо не выглядело шаблонным.")
    if vacancy_requirements and not matched:
        warnings.append("Не найдено подтвержденное совпадение навыков с вакансией. Проверь профиль или отредактируй письмо вручную.")
    if not has_evidence:
        warnings.append("Добавь подтверждающий факт из опыта или проекта, указанного в резюме.")
    if not length_ok:
        warnings.append("Рекомендуемая длина: 55-230 слов и 350-1800 символов.")
    if unsupported:
        warnings.append("В письме упомянуты навыки, которых нет в профиле: " + ", ".join(unsupported) + ".")
    if re.search(r"\b\d+\s*(?:лет|года|years?)\b", normalized):
        warnings.append("Письмо содержит числовое утверждение об опыте. Проверь, что оно подтверждено резюме.")

    if score >= 80 and not warnings:
        status, label = "ready", "Готово к отклику"
    elif score >= 55:
        status, label = "review", "Нужна быстрая проверка"
    else:
        status, label = "needs_revision", "Лучше доработать"
    return {
        "score": score,
        "status": status,
        "label": label,
        "checks": checks,
        "warnings": warnings,
        "matched_requirements": matched,
        "vacancy_requirements": vacancy_requirements[:8],
        "word_count": word_count,
        "characters": len(text),
    }
