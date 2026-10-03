#!/usr/bin/env python3
"""夸克网盘分片并发上传基准测试。

用法示例：

    # 代码路径自检（不需要网络和夸克账号）
    python scripts/quark_benchmark.py --dry-run

    # 真实测试（需要本机已配置 OpenList 或 Quark CLI）
    python scripts/quark_benchmark.py \
        --remote quark:/DouyinBiliRecorder \
        --sizes 1,5,20 --chunk-sizes 4,8,16 --concurrency 2,4,8

结果写入 ``data/benchmarks/``，同时输出 JSON 和 Markdown 报告。
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from douyin_bili_recorder.bandwidth import BandwidthScheduler  # noqa: E402
from douyin_bili_recorder.cloud import create_driver  # noqa: E402
from douyin_bili_recorder.cloud.driver import DriverContext  # noqa: E402
from douyin_bili_recorder.config import load_config  # noqa: E402
from douyin_bili_recorder.process import ProcessRunner  # noqa: E402


@dataclass(slots=True)
class BenchCase:
    size_mb: int
    chunk_mb: int
    concurrency: int


@dataclass(slots=True)
class BenchResult:
    size_mb: int
    chunk_mb: int
    concurrency: int
    seconds: float = 0.0
    mbps: float = 0.0
    ok: bool = False
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "size_mb": self.size_mb,
            "chunk_mb": self.chunk_mb,
            "concurrency": self.concurrency,
            "seconds": round(self.seconds, 3),
            "mbps": round(self.mbps, 3),
            "ok": self.ok,
            "error": self.error,
            "notes": self.notes,
        }


class SyntheticTarget:
    """In-process remote used by --dry-run to validate the harness itself."""

    def __init__(self, per_connection_mbps: float = 12.0) -> None:
        self.per_connection_mbps = per_connection_mbps
        self.lock = threading.Lock()
        self.received_bytes = 0
        self.chunks = 0

    def put_chunk(self, data: bytes, concurrency: int) -> None:
        seconds = len(data) / (self.per_connection_mbps * 1024 * 1024 / 8) * max(1, concurrency / 4)
        time.sleep(min(0.05, seconds))
        with self.lock:
            self.received_bytes += len(data)
            self.chunks += 1


def _write_chunked(
    source: Path,
    target: SyntheticTarget,
    chunk_bytes: int,
    concurrency: int,
    cancel_event: threading.Event,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def send(offset: int, length: int) -> None:
        if cancel_event.is_set():
            return
        with source.open("rb") as handle:
            handle.seek(offset)
            payload = handle.read(length)
        target.put_chunk(payload, concurrency)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = []
        offset = 0
        size = source.stat().st_size
        while offset < size:
            length = min(chunk_bytes, size - offset)
            futures.append(pool.submit(send, offset, length))
            offset += length
        for future in futures:
            future.result()


def _run_synthetic_case(case: BenchCase, tmp_dir: Path, scale: float) -> BenchResult:
    result = BenchResult(case.size_mb, case.chunk_mb, case.concurrency)
    effective_mb = max(1, int(case.size_mb * scale))
    path = tmp_dir / f"bench-{case.size_mb}-{case.chunk_mb}-{case.concurrency}.bin"
    with path.open("wb") as handle:
        remaining = effective_mb * 1024 * 1024
        block = b"\0" * (1024 * 1024)
        while remaining > 0:
            handle.write(block[: min(len(block), remaining)])
            remaining -= len(block)
    target = SyntheticTarget()
    started = time.monotonic()
    try:
        _write_chunked(
            path,
            target,
            case.chunk_mb * 1024 * 1024,
            case.concurrency,
            threading.Event(),
        )
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        return result
    finally:
        path.unlink(missing_ok=True)
    result.seconds = time.monotonic() - started
    result.mbps = (effective_mb * 8) / max(0.001, result.seconds)
    result.ok = True
    result.notes.append(f"合成目标，放大系数 {scale}")
    return result


def _run_remote_case(case: BenchCase, tmp_dir: Path, config_path: Path, remote: str) -> BenchResult:
    result = BenchResult(case.size_mb, case.chunk_mb, case.concurrency)
    config = load_config(config_path)
    config.cloud_chunk_size_mb = case.chunk_mb
    config.cloud_max_concurrency = case.concurrency
    logger = __import__("logging").getLogger("quark-benchmark")
    runner = ProcessRunner(logger, threading.Event())
    scheduler = BandwidthScheduler(cloud_max_concurrency=case.concurrency)
    context = DriverContext(config=config, runner=runner, logger=logger)
    driver = create_driver("quark", remote, context)

    path = tmp_dir / f"bench-{case.size_mb}MB.bin"
    with path.open("wb") as handle:
        remaining = case.size_mb * 1024 * 1024
        block = b"\0" * (1024 * 1024)
        while remaining > 0:
            handle.write(block[: min(len(block), remaining)])
            remaining -= len(block)

    started = time.monotonic()
    try:
        with scheduler.cloud_slot():
            driver.upload(path, f"{remote}/_benchmark/{path.name}", threading.Event())
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        result.notes.append("失败通常意味着触发风控、鉴权失效或并发过高")
        return result
    finally:
        path.unlink(missing_ok=True)
    result.seconds = time.monotonic() - started
    result.mbps = (case.size_mb * 8) / max(0.001, result.seconds)
    result.ok = True
    result.notes.append(f"driver={driver.name}")
    return result


def build_cases(
    sizes: list[int],
    chunk_sizes: list[int],
    concurrency: list[int],
) -> list[BenchCase]:
    return [
        BenchCase(size_mb=size, chunk_mb=chunk, concurrency=workers)
        for size in sizes
        for chunk in chunk_sizes
        for workers in concurrency
    ]


def render_markdown(cases: list[BenchResult], meta: dict[str, object]) -> str:
    lines = [
        "# 夸克分片并发上传基准报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模式：{'合成目标（dry-run）' if meta.get('dry_run') else '真实远端'}",
        f"- 远端：{meta.get('remote') or 'n/a'}",
        "",
        "| 文件(MB) | 分片(MB) | 并发 | 耗时(s) | 吞吐(Mbps) | 结果 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in cases:
        status = "成功" if item.ok else "失败"
        note = item.error or "；".join(item.notes)
        lines.append(
            f"| {item.size_mb} | {item.chunk_mb} | {item.concurrency} | "
            f"{item.seconds:.2f} | {item.mbps:.2f} | {status} | {note} |"
        )
    successful = [item.mbps for item in cases if item.ok]
    if successful:
        lines.extend(
            [
                "",
                "## 结论",
                "",
                f"- 最优吞吐：{max(successful):.2f} Mbps",
                f"- 平均吞吐：{statistics.mean(successful):.2f} Mbps",
                f"- 中位吞吐：{statistics.median(successful):.2f} Mbps",
                "- 并发并非越大越好；请以稳定拐点为准，并观察是否触发风控。",
            ]
        )
    fast = [item for item in cases if item.ok and item.mbps == max(successful or [0])]
    if fast:
        best = fast[0]
        lines.append(
            f"- 推荐配置：分片 {best.chunk_mb} MB，并发 {best.concurrency}（文件 {best.size_mb} MB）"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="夸克网盘分片并发上传基准测试")
    parser.add_argument("--dry-run", action="store_true", help="不访问网络，自检分片/并发逻辑")
    parser.add_argument("--remote", default="quark:/DouyinBiliRecorder", help="rclone 远端")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config.example.toml"),
        help="运行时配置（默认 config.example.toml）",
    )
    parser.add_argument("--sizes", default="1,5,20", help="文件大小 MB，逗号分隔")
    parser.add_argument("--chunk-sizes", default="4,8,16", help="分片大小 MB，逗号分隔")
    parser.add_argument("--concurrency", default="2,4,8", help="并发数，逗号分隔")
    parser.add_argument("--scale", type=float, default=0.05, help="dry-run 时的文件缩放系数")
    parser.add_argument("--output", default=str(ROOT / "data" / "benchmarks"))
    args = parser.parse_args(argv)

    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    chunk_sizes = [int(item) for item in args.chunk_sizes.split(",") if item.strip()]
    concurrency = [int(item) for item in args.concurrency.split(",") if item.strip()]
    cases = build_cases(sizes, chunk_sizes, concurrency)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results: list[BenchResult] = []
    with tempfile.TemporaryDirectory(prefix="quark-bench-") as tmp:
        tmp_dir = Path(tmp)
        for index, case in enumerate(cases, start=1):
            print(f"[{index}/{len(cases)}] {case}", flush=True)
            if args.dry_run:
                results.append(_run_synthetic_case(case, tmp_dir, args.scale))
            else:
                results.append(_run_remote_case(case, tmp_dir, Path(args.config), args.remote))

    payload = {
        "generated_at": stamp,
        "dry_run": bool(args.dry_run),
        "remote": None if args.dry_run else args.remote,
        "results": [item.to_dict() for item in results],
    }
    json_path = output_dir / f"quark-benchmark-{stamp}.json"
    md_path = output_dir / f"quark-benchmark-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        render_markdown(results, {"dry_run": args.dry_run, "remote": args.remote}),
        encoding="utf-8",
    )
    print(f"报告：{md_path}")
    print(f"数据：{json_path}")
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
