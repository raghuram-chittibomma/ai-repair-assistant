"""Load static LLM prompt text from ``repair_assistant/prompts/*.txt``.

User-message assembly (evidence blocks, transcript, criteria) stays in code;
only reusable system / safety directive text lives in these files.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Return prompt body for ``name`` (without ``.txt``), stripped of edges."""
    resource = files("repair_assistant.prompts").joinpath(f"{name}.txt")
    return resource.read_text(encoding="utf-8").strip()


def ask_system() -> str:
    return load_prompt("ask_system")


def diagnose_system() -> str:
    return load_prompt("diagnose_system")


def judge_system() -> str:
    return load_prompt("judge_system")


def safety_escalate() -> str:
    return load_prompt("safety_escalate")


def safety_warn() -> str:
    return load_prompt("safety_warn")


def safety_technician() -> str:
    return load_prompt("safety_technician")
