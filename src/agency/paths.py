from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path


def resolve_repo_root(candidates: Sequence[Path] | None = None) -> Path:
    env_root = os.environ.get("AGENCY_REPO_ROOT")
    probe_roots = list(candidates or [])
    if env_root:
        probe_roots.append(Path(env_root))
    probe_roots.extend([Path.cwd(), Path("/app"), Path(__file__).resolve().parents[2]])
    for root in probe_roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if (resolved / "research" / "scripts").exists() and (resolved / "src").exists():
            return resolved
        if (resolved / "research" / "scripts").exists() and (resolved / "schemas").exists():
            return resolved
    return Path(__file__).resolve().parents[2]


def ensure_research_src_path(repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    research_src = root / "research" / "src"
    if research_src.exists() and str(research_src) not in sys.path:
        sys.path.insert(0, str(research_src))
    return research_src


REPO_ROOT = resolve_repo_root()
RESEARCH_SRC = ensure_research_src_path(REPO_ROOT)
