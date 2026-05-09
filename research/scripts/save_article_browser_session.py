from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from subscription_email.article_session import (  # noqa: E402
    PROVIDER_LOGIN_URLS,
    save_browser_session,
)


def main() -> int:
    args = _parse_args()
    state_path = save_browser_session(
        provider=args.provider,
        state_dir=args.state_dir,
        login_url=args.login_url,
    )
    print(f"Saved browser session: {_display_path(state_path)}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save a local authenticated browser session for paid article links."
    )
    parser.add_argument("--provider", choices=sorted(PROVIDER_LOGIN_URLS), required=True)
    parser.add_argument("--login-url", help="Override login URL for the selected provider.")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=ROOT / "research" / "config" / "browser-sessions",
        help="Gitignored directory where provider browser sessions are stored.",
    )
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(ROOT.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
