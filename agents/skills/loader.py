import os
from core.incident import IncidentCategory

_SKILLS_DIR = os.path.dirname(__file__)

_SKILL_MAP = {
    IncidentCategory.CODE: "code-healer.md",
    IncidentCategory.INFRA: "infra-healer.md",
    IncidentCategory.BOTH: "both-healer.md",
}


def load_skill(category: IncidentCategory) -> str:
    filename = _SKILL_MAP.get(category)
    if not filename:
        raise ValueError(f"No skill defined for category: {category}")
    path = os.path.join(_SKILLS_DIR, filename)
    with open(path) as f:
        return f.read()


def skill_name(category: IncidentCategory) -> str:
    return _SKILL_MAP.get(category, "unknown-skill")
