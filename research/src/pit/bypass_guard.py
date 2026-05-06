from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_PATTERNS = (
    "research/data/parquet",
    "research\\data\\parquet",
    "data/parquet",
    "data\\parquet",
)
_SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
_ALLOWED_PREFIXES = ("research/src/pit/",)
_ALLOWED_FILES = {"tests/unit/test_pit_bypass_guard.py"}


@dataclass(frozen=True)
class BypassViolation:
    path: Path
    line_number: int
    line: str


def find_pit_bypasses(paths: Iterable[Path], *, repo_root: Path) -> list[BypassViolation]:
    violations: list[BypassViolation] = []
    for file_path in _python_files(paths):
        if _is_allowed(file_path, repo_root):
            continue
        for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern in line for pattern in _PATTERNS):
                violations.append(BypassViolation(file_path, line_number, line.strip()))
    return violations


def format_violations(violations: Iterable[BypassViolation], *, repo_root: Path) -> str:
    lines = [
        "Direct research/data/parquet access is forbidden; use pit.loader.PITLoader instead."
    ]
    for violation in violations:
        path = _display_path(violation.path, repo_root)
        lines.append(f"{path}:{violation.line_number}: {violation.line}")
    return "\n".join(lines)


def _python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            for candidate in path.rglob("*.py"):
                if not _has_skipped_part(candidate):
                    yield candidate


def _has_skipped_part(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


def _is_allowed(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False
    return relative in _ALLOWED_FILES or any(
        relative.startswith(prefix) for prefix in _ALLOWED_PREFIXES
    )


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
