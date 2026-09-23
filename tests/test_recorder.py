from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.recorder import discover_media


def test_discover_media_sorts_and_filters(tmp_path: Path) -> None:
    first = tmp_path / "part-000.ts"
    second = tmp_path / "part-001.mp4"
    ignored = tmp_path / "note.txt"
    first.write_bytes(b"a" * 1024)
    second.write_bytes(b"b" * 2048)
    ignored.write_bytes(b"c" * 4096)

    files = discover_media(tmp_path, min_file_size_mb=0)
    assert [path.name for path in files] == ["part-000.ts", "part-001.mp4"]

    files = discover_media(tmp_path, min_file_size_mb=1)
    assert files == []


def test_discover_media_keeps_active_partial_below_normal_threshold(tmp_path: Path) -> None:
    initialized = tmp_path / "live.flv"
    initialized.write_bytes(b"a" * 1024)
    active = tmp_path / "live.flv.part"
    active.write_bytes(b"b" * 4096)

    files = discover_media(tmp_path, min_file_size_mb=10, allow_partials=True)

    assert files == [active]
