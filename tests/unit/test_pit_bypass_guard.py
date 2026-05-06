from __future__ import annotations

from pathlib import Path

from pit.bypass_guard import find_pit_bypasses


def test_guard_flags_direct_parquet_path(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_reader.py"
    bad_file.write_text(
        'pl.read_parquet("research/data/parquet/prices.parquet")\n',
        encoding="utf-8",
    )

    violations = find_pit_bypasses([bad_file], repo_root=tmp_path)

    assert len(violations) == 1
    assert violations[0].line_number == 1


def test_guard_allows_pit_loader_package(tmp_path: Path) -> None:
    loader_file = tmp_path / "research" / "src" / "pit" / "loader.py"
    loader_file.parent.mkdir(parents=True)
    loader_file.write_text('Path("research/data/parquet/prices.parquet")\n', encoding="utf-8")

    violations = find_pit_bypasses([loader_file], repo_root=tmp_path)

    assert violations == []


def test_repository_has_no_direct_parquet_bypasses() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "src",
        repo_root / "research" / "src",
        repo_root / "research" / "notebooks",
        repo_root / "scripts",
        repo_root / "tests",
    ]

    violations = find_pit_bypasses((path for path in paths if path.exists()), repo_root=repo_root)

    assert violations == []
