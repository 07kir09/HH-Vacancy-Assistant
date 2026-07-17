from __future__ import annotations

import re
from typing import Any


SKILL_ALIASES = {
    "SQL": ["sql", "postgresql", "postgres"],
    "PostgreSQL": ["postgresql", "postgres"],
    "Python": ["python"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Matplotlib": ["matplotlib"],
    "Plotly": ["plotly"],
    "Power BI": ["power bi"],
    "Tableau": ["tableau"],
    "Excel": ["excel"],
    "Statistics": ["statistics", "статист"],
    "A/B testing": ["a/b", "ab test", "ab-test", "проверка гипотез"],
    "Product metrics": ["product metrics", "метрик"],
    "NLP": ["nlp", "natural language", "текст"],
    "PyTorch": ["pytorch"],
    "Transformers": ["transformer", "transformers", "bert", "finbert"],
    "Hugging Face": ["hugging face"],
    "FastAPI": ["fastapi"],
    "Docker": ["docker"],
    "React": ["react"],
    "JavaScript": ["javascript", "js"],
    "Solidity": ["solidity"],
    "ETL": ["etl"],
    "Data pipelines": ["pipeline", "пайплайн"],
    "Financial analytics": ["финанс", "financial", "portfolio", "risk", "var"],
}


ROLE_KEYWORDS = {
    "Junior Data Analyst": ["junior data analyst", "data analyst", "аналитик данных"],
    "Product Analyst": ["product analyst", "продуктовый аналитик", "product analytics"],
    "BI Analyst": ["bi analyst", "business intelligence", "power bi", "tableau"],
    "FinTech Analyst": ["fintech", "финтех", "financial analyst", "банк"],
    "ML/NLP Analyst": ["nlp", "machine learning", "data science", "ml"],
}


def build_profile_from_text(text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = _extract_name(lines)
    email = _first_match(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone = _first_match(r"(?:\+?\d[\d\s().-]{8,}\d)", text)
    telegram = _first_match(r"(?:tg|telegram|телеграм)[:\s@]*(@?[A-Za-z0-9_]{4,})", text, group=1)
    github = _first_match(r"github[:\s/]*([A-Za-z0-9_.-]+)", text, group=1)
    skills = _extract_skills(normalized)
    target_roles = _extract_roles(normalized)
    projects = _extract_projects(lines)
    education = _extract_education(text)
    summary = _summary(target_roles, skills, projects)

    return {
        "name": name,
        "hh_resume_id": "",
        "target_roles": target_roles,
        "city": "",
        "desired_salary": 0,
        "experience_summary": summary,
        "skills": skills,
        "strengths": _strengths(skills),
        "links": {
            "phone": phone,
            "portfolio": "",
            "telegram": telegram if telegram.startswith("@") or not telegram else f"@{telegram}",
            "email": email,
            "github": github,
        },
        "education": education,
        "experience": _extract_experience(lines),
        "projects": projects,
        "achievements": _extract_achievements(lines),
        "relevant_focus": _relevant_focus(normalized),
        "avoid_roles": ["Senior", "Lead", "QA", "DevOps", "1C", "PHP", "C++", "Java backend"],
        "preferred_industries": ["FinTech", "Banking", "Data Products", "Product analytics", "ML/NLP products"],
        "preferred_keywords": skills[:16],
        "cover_letter_facts": _cover_letter_facts(name, skills, projects, education),
        "search_notes": "Сгенерировано из загруженного резюме. Проверьте целевые роли, навыки и зарплату перед запуском поиска.",
        "cover_letter": {"language": "ru", "tone": "concise", "custom_intro": ""},
    }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _first_match(pattern: str, text: str, group: int = 0) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(group).strip() if match else ""


def _extract_name(lines: list[str]) -> str:
    for line in lines[:8]:
        clean = re.sub(r"\s+", " ", line).strip()
        if "@" in clean or re.search(r"\d", clean):
            continue
        if len(clean.split()) in {2, 3, 4} and len(clean) <= 80:
            return clean
    return ""


def _extract_skills(normalized: str) -> list[str]:
    skills: list[str] = []
    for skill, aliases in SKILL_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            skills.append(skill)
    return skills


def _extract_roles(normalized: str) -> list[str]:
    roles = []
    for role, aliases in ROLE_KEYWORDS.items():
        if any(alias in normalized for alias in aliases):
            roles.append(role)
    if not roles:
        roles = ["Data Analyst", "Product Analyst"]
    return roles


def _extract_section(lines: list[str], headings: list[str], stop_headings: list[str]) -> list[str]:
    result: list[str] = []
    active = False
    for line in lines:
        low = line.lower()
        if any(heading in low for heading in headings):
            active = True
            continue
        if active and any(stop in low for stop in stop_headings):
            break
        if active:
            result.append(line)
    return result


def _extract_projects(lines: list[str]) -> list[dict[str, Any]]:
    section = _extract_section(
        lines,
        ["проекты", "projects", "релевантный опыт"],
        ["образование", "education", "достижения", "achievements", "релевантный фокус"],
    )
    projects: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in section:
        if len(line) < 90 and re.search(r"(20\d{2}|19\d{2}| \| )", line) and not line.startswith(("•", "-", "*")):
            if current:
                projects.append(current)
            name = re.split(r"\s+\|\s+|20\d{2}", line, maxsplit=1)[0].strip(" -|")
            current = {"name": name or line, "period": _first_match(r"20\d{2}(?:[–-]20\d{2})?", line), "description": "", "stack": []}
        elif current:
            if line.lower().startswith(("стек:", "stack:")):
                current["stack"] = [part.strip() for part in re.split(r"[,;]", line.split(":", 1)[-1]) if part.strip()]
            else:
                current["description"] = (current.get("description", "") + " " + line.lstrip("•-* ")).strip()
    if current:
        projects.append(current)
    return projects[:5]


def _extract_experience(lines: list[str]) -> list[dict[str, Any]]:
    section = _extract_section(lines, ["профессиональный опыт", "experience", "work experience"], ["проекты", "projects", "образование"])
    if not section:
        return []
    first = section[0]
    highlights = [line.lstrip("•-* ") for line in section[1:8] if len(line) > 20]
    return [{"company": first, "role": "", "period": _first_match(r"20\d{2}(?:[–-]\S+)?", first), "highlights": highlights}]


def _extract_education(text: str) -> dict[str, str]:
    education: dict[str, str] = {}
    if re.search(r"вшэ|hse", text, re.IGNORECASE):
        education["university"] = "НИУ ВШЭ"
    if re.search(r"фкн", text, re.IGNORECASE):
        education["faculty"] = "ФКН"
    program = _first_match(r"(?:направление|program)[:\s«\"]+([^»\"\n]+)", text, group=1)
    if program:
        education["program"] = program
    gpa = _first_match(r"GPA[:\s]+([0-9.,]+)", text, group=1)
    if gpa:
        education["gpa"] = gpa
    return education


def _extract_achievements(lines: list[str]) -> list[str]:
    section = _extract_section(lines, ["достижения", "achievements"], ["профессиональный опыт", "experience", "проекты", "projects"])
    return [line.lstrip("•-* ") for line in section[:6]]


def _relevant_focus(normalized: str) -> list[str]:
    focus = []
    if any(word in normalized for word in ["fintech", "финтех", "банк", "risk", "portfolio"]):
        focus.append("Финтех-аналитика")
    if any(word in normalized for word in ["product", "продукт", "метрик"]):
        focus.append("Product/Data Analytics")
    if any(word in normalized for word in ["nlp", "machine learning", "transformer", "bert"]):
        focus.append("ML/NLP")
    if any(word in normalized for word in ["dashboard", "дашборд", "bi", "tableau", "power bi"]):
        focus.append("BI и визуализация")
    return focus or ["Data Analytics"]


def _summary(roles: list[str], skills: list[str], projects: list[dict[str, Any]]) -> str:
    role = roles[0] if roles else "Data Analyst"
    skill_part = ", ".join(skills[:8]) if skills else "SQL, Python и аналитика данных"
    project_part = ""
    if projects:
        project_part = f" Есть релевантные проекты: {', '.join(project.get('name', '') for project in projects[:2])}."
    return f"{role} с опытом и навыками в области {skill_part}.{project_part}"


def _strengths(skills: list[str]) -> list[str]:
    strengths = [
        "быстро разбираться в бизнес-задаче и переводить её в метрики, данные и проверяемые гипотезы",
        "работать с данными через SQL/Python и доводить анализ до понятных выводов",
        "строить дашборды, визуализации и аналитические прототипы для принятия решений",
    ]
    if any(skill in skills for skill in ["NLP", "PyTorch", "Transformers"]):
        strengths.append("применять ML/NLP-подходы для анализа текстовых данных и качества моделей")
    return strengths


def _cover_letter_facts(name: str, skills: list[str], projects: list[dict[str, Any]], education: dict[str, str]) -> list[str]:
    facts = []
    if education:
        facts.append("имею профильное образование/обучение, указанное в резюме")
    if skills:
        facts.append("использую в работе " + ", ".join(skills[:6]))
    for project in projects[:2]:
        facts.append(f"делал проект «{project.get('name', '')}»")
    return facts
