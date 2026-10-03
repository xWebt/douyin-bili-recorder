from __future__ import annotations

import pytest

from douyin_bili_recorder.part_state import (
    InvalidPartTransition,
    PartState,
    allowed_targets,
    assert_part_transition,
    can_transition,
    is_terminal,
    normalize_part_state,
    protects_local_files,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("UPLOAD_FAILED", PartState.FAILED),
        ("upload_failed", PartState.FAILED),
        ("", PartState.PENDING),
        (None, PartState.PENDING),
        ("UPLOADED", PartState.UPLOADED),
        ("unknown-status", PartState.FAILED),
    ],
)
def test_normalize_legacy_statuses(raw: object, expected: PartState) -> None:
    assert normalize_part_state(raw) == expected.value


def test_happy_path_transitions_are_allowed() -> None:
    chain = [
        PartState.PENDING,
        PartState.RECORDING,
        PartState.RENDERING,
        PartState.PENDING_UPLOAD,
        PartState.UPLOADING,
        PartState.UPLOADED,
        PartState.PENDING_CLOUD,
        PartState.CLOUD_UPLOADING,
        PartState.UPLOADED,
        PartState.READY_TO_DELETE,
        PartState.DELETED,
    ]
    for current, target in zip(chain, chain[1:]):
        assert can_transition(current, target), f"{current} -> {target} should be allowed"


def test_illegal_transitions_raise() -> None:
    with pytest.raises(InvalidPartTransition):
        assert_part_transition(PartState.DELETED, PartState.UPLOADING)
    with pytest.raises(InvalidPartTransition):
        assert_part_transition(PartState.UPLOADED, PartState.RECORDING)


def test_self_transition_is_allowed() -> None:
    assert can_transition("UPLOADING", "UPLOADING")


def test_terminal_and_protected_helpers() -> None:
    assert is_terminal(PartState.DELETED)
    assert not is_terminal(PartState.UPLOADED)
    for state in (
        PartState.PENDING,
        PartState.RECORDING,
        PartState.PENDING_UPLOAD,
        PartState.UPLOADING,
        PartState.PENDING_CLOUD,
        PartState.CLOUD_UPLOADING,
        PartState.RETRY_WAIT,
        PartState.PAUSED,
        PartState.FAILED,
    ):
        assert protects_local_files(state)
    assert not protects_local_files(PartState.DELETED)


def test_retry_paths_are_reachable() -> None:
    assert "RETRY_WAIT" in allowed_targets("UPLOADING")
    assert "UPLOADING" in allowed_targets("FAILED")
    assert "UPLOADING" in allowed_targets("CANCELED")
    assert "UPLOADING" in allowed_targets("PAUSED")
