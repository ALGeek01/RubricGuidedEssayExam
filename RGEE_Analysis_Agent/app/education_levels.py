"""Allowed education levels for exams (UI dropdown + LLM guidance)."""

from typing import Any

EDUCATION_LEVELS: list[dict[str, Any]] = [
    {
        "id": "primary",
        "label": "Primary school (K–5)",
        "short": "Primary",
        "guidance": (
            "Use vocabulary, sentence length, and concepts suitable for young learners (roughly ages 5–11). "
            "Avoid jargon; prefer concrete examples and clear, encouraging prompts. "
            "Rubric expectations should reflect age-appropriate writing (ideas and clarity over formal sophistication)."
        ),
    },
    {
        "id": "middle",
        "label": "Middle school (6–8)",
        "short": "Middle school",
        "guidance": (
            "Target early adolescent learners: introduce domain terms with brief explanations. "
            "Questions may ask for short structured reasoning. Grading should reward clear organization and basic use of evidence."
        ),
    },
    {
        "id": "high_school",
        "label": "High school (9–12)",
        "short": "High school",
        "guidance": (
            "Expect secondary-level analysis: thesis-style responses, supporting reasons, and some use of terminology. "
            "Rubric can include nuance and partial credit for incomplete but thoughtful answers."
        ),
    },
    {
        "id": "college",
        "label": "College / undergraduate",
        "short": "College",
        "guidance": (
            "Undergraduate-level depth: integrate concepts, compare trade-offs, and cite reasoning from the background. "
            "Rubric should reflect disciplinary expectations at intro–advanced undergraduate level."
        ),
    },
    {
        "id": "graduate",
        "label": "Graduate / professional",
        "short": "Graduate",
        "guidance": (
            "Expect synthesis, critique, and precision appropriate for graduate or professional study. "
            "Questions may assume prior coursework; grading should be rigorous and specific about gaps in argument."
        ),
    },
]

DEFAULT_EDUCATION_LEVEL_ID = "college"

_LEVEL_BY_ID = {entry["id"]: entry for entry in EDUCATION_LEVELS}
ALLOWED_LEVEL_IDS = frozenset(_LEVEL_BY_ID.keys())


def label_for_level(level_id: str) -> str:
    entry = _LEVEL_BY_ID.get(level_id)
    return entry["label"] if entry else level_id


def guidance_for_level(level_id: str) -> str:
    entry = _LEVEL_BY_ID.get(level_id)
    if not entry:
        return _LEVEL_BY_ID[DEFAULT_EDUCATION_LEVEL_ID]["guidance"]
    return entry["guidance"]
