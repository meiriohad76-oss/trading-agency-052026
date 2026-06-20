from __future__ import annotations

from pathlib import Path

from agency.paths import resolve_repo_root


def test_resolve_repo_root_prefers_runtime_mount_over_installed_package(
    tmp_path: Path,
) -> None:
    installed_root = tmp_path / "usr" / "local" / "lib" / "python3.14" / "site-packages"
    app_root = tmp_path / "app"
    (installed_root / "research" / "scripts").mkdir(parents=True)
    (app_root / "research" / "scripts").mkdir(parents=True)
    (app_root / "schemas").mkdir()

    assert resolve_repo_root([installed_root, app_root]) == app_root.resolve()


def test_resolve_repo_root_accepts_source_checkout(tmp_path: Path) -> None:
    checkout_root = tmp_path / "checkout"
    (checkout_root / "research" / "scripts").mkdir(parents=True)
    (checkout_root / "src").mkdir()

    assert resolve_repo_root([checkout_root]) == checkout_root.resolve()
