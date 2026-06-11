import os
from core.incident import IncidentPath

_SKILLS_DIR = os.path.dirname(__file__)

_SKILL_MAP = {
    IncidentPath.CODE:  "code-healer.md",
    IncidentPath.INFRA: "infra-healer.md",
    IncidentPath.BOTH:  "both-healer.md",
}


def load_skill(path: IncidentPath) -> str:
    filename = _SKILL_MAP.get(path)
    if not filename:
        raise ValueError(f"No skill defined for path: {path}")
    with open(os.path.join(_SKILLS_DIR, filename)) as f:
        return f.read()


def skill_name(path: IncidentPath) -> str:
    return _SKILL_MAP.get(path, "unknown-skill")
