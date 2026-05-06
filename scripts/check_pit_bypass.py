from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "src"))

from pit.bypass_guard import find_pit_bypasses, format_violations  # noqa: E402


def main() -> int:
    paths = [
        ROOT / "src",
        ROOT / "research" / "src",
        ROOT / "research" / "notebooks",
        ROOT / "scripts",
        ROOT / "tests",
    ]
    violations = find_pit_bypasses((path for path in paths if path.exists()), repo_root=ROOT)
    if violations:
        print(format_violations(violations, repo_root=ROOT), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
