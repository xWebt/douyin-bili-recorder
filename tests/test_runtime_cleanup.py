from __future__ import annotations

from pathlib import Path

from douyin_bili_recorder.runtime_cleanup import (
    ProcessInfo,
    cleanup_stale_runtime_processes,
    is_managed_process,
    parse_process_table,
)


def test_parse_process_table_keeps_full_command() -> None:
    parsed = parse_process_table(
        "  10  1 /Applications/DouyinBiliRecorder.app/Contents/MacOS/DouyinBiliRecorder --internal-ui\n"
        "  11 10 /usr/bin/python -m biliup server --config /tmp/data/config.toml\n"
    )
    assert parsed == [
        ProcessInfo(10, 1, "/Applications/DouyinBiliRecorder.app/Contents/MacOS/DouyinBiliRecorder --internal-ui"),
        ProcessInfo(11, 10, "/usr/bin/python -m biliup server --config /tmp/data/config.toml"),
    ]


def test_managed_process_detection_scopes_biliup_to_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    assert is_managed_process(
        "/Applications/DouyinBiliRecorder.app/Contents/MacOS/DouyinBiliRecorder",
        data_dir,
    )
    assert is_managed_process(
        f"/usr/bin/python -m biliup server --config {data_dir}/config.toml",
        data_dir,
    )
    assert not is_managed_process("/usr/bin/python -m biliup server --config /tmp/other/config.toml", data_dir)
    assert not is_managed_process("/opt/homebrew/bin/openlist server", data_dir)


def test_cleanup_reaps_managed_processes_but_keeps_current_tree(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    app = "/Applications/DouyinBiliRecorder.app/Contents/MacOS/DouyinBiliRecorder"
    processes = [
        ProcessInfo(100, 1, f"/bin/zsh script --current {data_dir}"),
        ProcessInfo(101, 100, f"{app} --internal-ui --config {data_dir}/config.toml"),
        ProcessInfo(102, 101, f"{app} --internal-recorder run --config {data_dir}/runtime-config.toml"),
        ProcessInfo(200, 1, f"{app} --internal-ui --config {data_dir}/old.toml"),
        ProcessInfo(201, 200, f"{app} --internal-recorder run --config {data_dir}/old-runtime.toml"),
        ProcessInfo(202, 201, f"/usr/bin/python -m biliup server --config {data_dir}/danmaku.toml"),
        ProcessInfo(300, 1, "/opt/homebrew/bin/openlist server"),
    ]
    killed: list[int] = []

    result = cleanup_stale_runtime_processes(
        data_dir,
        current_pid=100,
        process_provider=lambda: processes,
        terminator=killed.append,
    )

    assert result == [200, 201, 202]
    assert killed == [200, 201, 202]
