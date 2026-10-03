from __future__ import annotations

import threading
import time

from douyin_bili_recorder.bandwidth import BandwidthScheduler, configure_from_state


def test_bilibili_priority_throttles_cloud_only_while_uploading() -> None:
    scheduler = BandwidthScheduler(cloud_limit_kbps=0, bilibili_priority=True)

    assert scheduler.cloud_limit_kbps() == 0
    with scheduler.bilibili_upload():
        assert scheduler.cloud_limit_kbps() == 2048
        assert scheduler.snapshot().bilibili_active == 1
    assert scheduler.cloud_limit_kbps() == 0


def test_explicit_limit_always_applies() -> None:
    scheduler = BandwidthScheduler(cloud_limit_kbps=5000)

    assert scheduler.cloud_limit_kbps() == 5000
    with scheduler.bilibili_upload():
        assert scheduler.cloud_limit_kbps() == 5000


def test_priority_can_be_disabled() -> None:
    scheduler = BandwidthScheduler(bilibili_priority=False)

    with scheduler.bilibili_upload():
        assert scheduler.cloud_limit_kbps() == 0


def test_cloud_slot_serialises_uploads() -> None:
    scheduler = BandwidthScheduler(cloud_max_concurrency=1)
    order: list[str] = []
    first_entered = threading.Event()
    release = threading.Event()

    def worker(name: str) -> None:
        with scheduler.cloud_slot():
            order.append(f"enter-{name}")
            if name == "a":
                first_entered.set()
                release.wait(timeout=5)
            order.append(f"exit-{name}")

    first = threading.Thread(target=worker, args=("a",))
    second = threading.Thread(target=worker, args=("b",))
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    time.sleep(0.2)
    assert order == ["enter-a"]
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert order == ["enter-a", "exit-a", "enter-b", "exit-b"]


def test_configure_from_state_applies_runtime_settings() -> None:
    scheduler = BandwidthScheduler()

    previous_limit = scheduler.cloud_limit_kbps()
    previous_concurrency = scheduler.snapshot().cloud_max_concurrency
    try:
        from douyin_bili_recorder import bandwidth

        original = bandwidth.BANDWIDTH
        bandwidth.BANDWIDTH = scheduler
        configure_from_state(
            {
                "cloud_bandwidth_limit_kbps": 1234,
                "cloud_max_concurrency": 3,
                "bilibili_priority": False,
            }
        )
        snapshot = scheduler.snapshot()
        assert snapshot.cloud_limit_kbps == 1234
        assert snapshot.cloud_max_concurrency == 3
        assert snapshot.bilibili_priority is False
    finally:
        from douyin_bili_recorder import bandwidth

        bandwidth.BANDWIDTH = original
        scheduler.configure(
            cloud_limit_kbps=previous_limit,
            cloud_max_concurrency=previous_concurrency,
            bilibili_priority=True,
        )
