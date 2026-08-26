"""Prune timestamped Q&A bench JSON run logs (manual; E9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from repair_assistant.corpus import manifest as manifest_mod

# Filename groups under evals/qa/results/runs/
_PREFIXES = ("candidates-", "")  # candidates-* then bare smoke stamps


@dataclass
class PrunePlan:
    keep: list[Path]
    delete: list[Path]


def runs_dir(root: Path | None = None) -> Path:
    root = root or manifest_mod.load().root
    return root / "evals" / "qa" / "results" / "runs"


def _mtime(path: Path) -> float:
    return path.stat().st_mtime


def _group_key(path: Path) -> str:
    name = path.name
    if name.startswith("candidates-"):
        return "candidates-"
    return ""


def plan_prune(
    directory: Path | None = None,
    *,
    keep: int | None = None,
    older_than_days: int | None = None,
) -> PrunePlan:
    """Decide which ``*.json`` run logs to keep vs delete.

    ``keep``: retain the newest N files **per prefix** (smoke vs candidates).
    ``older_than_days``: delete files whose mtime is older than D days.
    Both may combine (delete if either rule says so). At least one must be set.
    """
    if keep is None and older_than_days is None:
        raise ValueError("pass --keep and/or --older-than-days")

    directory = directory or runs_dir()
    files = sorted(directory.glob("*.json"), key=_mtime, reverse=True)
    delete: set[Path] = set()

    if older_than_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        cutoff_ts = cutoff.timestamp()
        for path in files:
            if _mtime(path) < cutoff_ts:
                delete.add(path)

    if keep is not None:
        by_prefix: dict[str, list[Path]] = {p: [] for p in _PREFIXES}
        for path in files:
            by_prefix[_group_key(path)].append(path)
        for group in by_prefix.values():
            for path in group[keep:]:
                delete.add(path)

    keep_list = [p for p in files if p not in delete]
    return PrunePlan(keep=keep_list, delete=sorted(delete, key=_mtime))


def apply_prune(plan: PrunePlan, *, dry_run: bool = True) -> list[Path]:
    """Delete planned files unless ``dry_run``. Returns paths removed (or would be)."""
    removed: list[Path] = []
    for path in plan.delete:
        removed.append(path)
        if not dry_run:
            path.unlink(missing_ok=True)
    return removed
