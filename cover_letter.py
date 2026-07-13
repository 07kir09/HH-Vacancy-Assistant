from __future__ import annotations

from typing import Any

from scorer import strip_html, vacancy_text


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        if value:
            return value
    return ""


def _skill_hits(vacancy: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    text = vacancy_text(vacancy)
    hits: list[str] = []
    for skill in profile.get("skills", []):
        if str(skill).lower() in text:
            hits.append(str(skill))
    return hits


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _vacancy_focus(vacancy: dict[str, Any]) -> list[str]:
    text = vacancy_text(vacancy)
    focus: list[str] = []
    if _contains_any(text, ["fintech", "банк", "bank", "risk", "var", "portfolio", "финанс", "риск"]):
        focus.append("fintech")
    if _contains_any(text, ["product", "продукт", "metric", "метрик", "a/b", "ab test", "гипотез"]):
        focus.append("product")
    if _contains_any(text, ["nlp", "text", "текст", "transformer", "bert", "sentiment", "ml", "machine learning"]):
        focus.append("ml_nlp")
    if _contains_any(text, ["dashboard", "дашборд", "visual", "bi", "tableau", "power bi", "looker"]):
        focus.append("bi")
    if _contains_any(text, ["sql", "etl", "pipeline", "пайплайн", "data warehouse", "dwh"]):
        focus.append("data_engineering")
    return focus


def _project_score(project: dict[str, Any], focus: list[str], text: str) -> int:
    project_text = " ".join(
        [
            str(project.get("name", "")),
            str(project.get("description", "")),
            " ".join(str(item) for item in project.get("stack", [])),
        ]
    ).lower()
    score = 0
    for token in text.lower().split():
        if len(token) > 3 and token.strip(".,:;()") in project_text:
            score += 1
    if "fintech" in focus and _contains_any(project_text, ["risk", "var", "portfolio", "financial", "финанс", "риск"]):
        score += 8
    if "ml_nlp" in focus and _contains_any(project_text, ["nlp", "sentiment", "transformer", "bert", "pytorch"]):
        score += 8
    if "product" in focus and _contains_any(project_text, ["dashboard", "аналит", "метрик", "platform"]):
        score += 4
    if "bi" in focus and _contains_any(project_text, ["dashboard", "visual", "react"]):
        score += 3
    if "data_engineering" in focus and _contains_any(project_text, ["pipeline", "fastapi", "docker", "python"]):
        score += 3
    return score


def _matched_projects(vacancy: dict[str, Any], profile: dict[str, Any], limit: int = 2) -> list[dict[str, Any]]:
    projects = [item for item in profile.get("projects", []) if isinstance(item, dict)]
    if not projects:
        return []
    text = vacancy_text(vacancy)
    focus = _vacancy_focus(vacancy)
    ranked = sorted(projects, key=lambda project: _project_score(project, focus, text), reverse=True)
    return [project for project in ranked[:limit] if _project_score(project, focus, text) > 0]


def _focus_sentence(vacancy: dict[str, Any]) -> str:
    focus = _vacancy_focus(vacancy)
    if "fintech" in focus:
        return "Мне особенно близки задачи на стыке данных, финансовых метрик и продуктовых решений."
    if "ml_nlp" in focus:
        return "Отдельно близки задачи с ML/NLP, текстовыми данными, качеством моделей и понятной интерпретацией результатов."
    if "product" in focus:
        return "Отдельно близки задачи с продуктовой аналитикой, метриками, проверкой гипотез и влиянием аналитики на решения команды."
    if "bi" in focus:
        return "Отдельно близки задачи с дашбордами, визуализацией и превращением сырых данных в понятные управленческие выводы."
    return ""


def _project_line(project: dict[str, Any]) -> str:
    name = project.get("name", "проект")
    description = str(project.get("description", "")).rstrip(".")
    stack = ", ".join(str(item) for item in project.get("stack", [])[:4])
    if stack:
        return f"Из релевантного опыта: «{name}» - {description}. Стек: {stack}."
    return f"Из релевантного опыта: «{name}» - {description}."


def generate_cover_letter(vacancy: dict[str, Any], profile: dict[str, Any]) -> str:
    name = profile.get("name") or ""
    title = vacancy.get("name") or "the role"
    employer = (vacancy.get("employer") or {}).get("name") or "your team"
    intro = (profile.get("cover_letter") or {}).get("custom_intro") or ""
    experience = profile.get("experience_summary") or ""
    strengths = [str(item) for item in profile.get("strengths", []) if item]
    links = profile.get("links") or {}
    contact = _first_non_empty([links.get("telegram", ""), links.get("email", ""), links.get("portfolio", "")])
    hits = _skill_hits(vacancy, profile)
    description = strip_html(vacancy.get("description"))
    projects = _matched_projects(vacancy, profile)
    focus_sentence = _focus_sentence(vacancy)

    lines = ["Здравствуйте!"]
    if intro:
        lines.append(intro)
    elif name:
        lines.append(f"Меня зовут {name}. Заинтересовала вакансия «{title}» в {employer}.")
    else:
        lines.append(f"Заинтересовала вакансия «{title}» в {employer}.")

    if experience:
        lines.append(f"Мой профиль: {experience}")

    if hits:
        lines.append(
            "По описанию вижу хорошее совпадение с моим опытом: "
            + ", ".join(hits[:6])
            + "."
        )

    if projects:
        lines.extend(_project_line(project) for project in projects)

    if strengths:
        lines.append("Буду полезен в задачах, где нужно " + "; ".join(strengths[:2]) + ".")

    if focus_sentence:
        lines.append(focus_sentence)
    elif "a/b" in description.lower() or "ab" in description.lower():
        lines.append("Отдельно близки задачи с продуктовой аналитикой, метриками и проверкой гипотез.")

    lines.append("Готов обсудить, как мой опыт может помочь вашей команде.")
    if contact:
        lines.append(f"Контакт: {contact}")

    return "\n\n".join(lines).strip()
