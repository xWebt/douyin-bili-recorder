from __future__ import annotations

from enum import StrEnum


class PartState(StrEnum):
    """Canonical per-part lifecycle.

    The flow mirrors ``待录制 → 录制中 → 待渲染 → 渲染中 → 待上传B站 → B站上传中 →
    待网盘 → 网盘上传中 → 可删除 → 已删除`` plus the exception branches from the
    requirements document.
    """

    PENDING = "PENDING"
    RECORDING = "RECORDING"
    RECORDED = "RECORDED"
    RENDERING = "RENDERING"
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    PENDING_CLOUD = "PENDING_CLOUD"
    CLOUD_UPLOADING = "CLOUD_UPLOADING"
    READY_TO_DELETE = "READY_TO_DELETE"
    DELETED = "DELETED"
    RETRY_WAIT = "RETRY_WAIT"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    SPACE_BLOCKED = "SPACE_BLOCKED"
    LOCAL_ONLY = "LOCAL_ONLY"
    CANCELED = "CANCELED"
    DISCARDED = "DISCARDED"


class InvalidPartTransition(RuntimeError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"illegal part state transition: {current} -> {target}")
        self.current = current
        self.target = target


# Legacy status strings written by older versions keep loading unchanged.
LEGACY_ALIASES: dict[str, PartState] = {
    "": PartState.PENDING,
    "UPLOAD_FAILED": PartState.FAILED,
    "CLOUD_FAILED": PartState.FAILED,
    "PREPARING": PartState.RENDERING,
    "DOWNLOADING": PartState.RECORDING,
    "UPLOAD_PENDING": PartState.PENDING_UPLOAD,
    "RENDER_PENDING": PartState.RENDERING,
}

# States that may never move again.
TERMINAL_STATES = frozenset({PartState.DELETED})

# States whose local files must be preserved: cleanup logic keys off this set.
PROTECTED_STATES = frozenset(
    {
        PartState.PENDING,
        PartState.RECORDING,
        PartState.RECORDED,
        PartState.RENDERING,
        PartState.PENDING_UPLOAD,
        PartState.UPLOADING,
        PartState.PENDING_CLOUD,
        PartState.CLOUD_UPLOADING,
        PartState.RETRY_WAIT,
        PartState.PAUSED,
        PartState.SPACE_BLOCKED,
        PartState.FAILED,
    }
)

_RETRYABLE = {
    PartState.PENDING_UPLOAD,
    PartState.UPLOADING,
    PartState.PENDING_CLOUD,
    PartState.CLOUD_UPLOADING,
    PartState.RETRY_WAIT,
    PartState.PAUSED,
    PartState.FAILED,
}

_ALLOWED_TRANSITIONS: dict[PartState, frozenset[PartState]] = {
    PartState.PENDING: frozenset(
        {
            PartState.RECORDING,
            PartState.RENDERING,
            PartState.PENDING_UPLOAD,
            PartState.UPLOADING,
            PartState.LOCAL_ONLY,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
            PartState.FAILED,
            PartState.PAUSED,
            PartState.SPACE_BLOCKED,
        }
    ),
    PartState.RECORDING: frozenset(
        {
            PartState.RECORDED,
            PartState.RENDERING,
            PartState.PENDING_UPLOAD,
            PartState.PENDING,
            PartState.FAILED,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.PAUSED,
            PartState.SPACE_BLOCKED,
        }
    ),
    PartState.RECORDED: frozenset(
        {
            PartState.RENDERING,
            PartState.PENDING_UPLOAD,
            PartState.LOCAL_ONLY,
            PartState.FAILED,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.PAUSED,
            PartState.SPACE_BLOCKED,
        }
    ),
    PartState.RENDERING: frozenset(
        {
            PartState.PENDING_UPLOAD,
            PartState.RECORDED,
            PartState.RETRY_WAIT,
            PartState.FAILED,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.PAUSED,
        }
    ),
    PartState.PENDING_UPLOAD: frozenset(
        _RETRYABLE
        | {
            PartState.UPLOADED,
            PartState.LOCAL_ONLY,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.UPLOADING: frozenset(
        {
            PartState.UPLOADED,
            PartState.PENDING_UPLOAD,
            PartState.RETRY_WAIT,
            PartState.FAILED,
            PartState.PAUSED,
            PartState.CANCELED,
            PartState.DISCARDED,
        }
    ),
    PartState.UPLOADED: frozenset(
        {
            PartState.PENDING_CLOUD,
            PartState.CLOUD_UPLOADING,
            PartState.READY_TO_DELETE,
            PartState.DELETED,
        }
    ),
    PartState.PENDING_CLOUD: frozenset(
        _RETRYABLE
        | {
            PartState.UPLOADED,
            PartState.READY_TO_DELETE,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.CLOUD_UPLOADING: frozenset(
        {
            PartState.UPLOADED,
            PartState.PENDING_CLOUD,
            PartState.RETRY_WAIT,
            PartState.FAILED,
            PartState.PAUSED,
            PartState.CANCELED,
            PartState.DISCARDED,
        }
    ),
    PartState.READY_TO_DELETE: frozenset({PartState.DELETED, PartState.CLOUD_UPLOADING, PartState.PENDING_CLOUD}),
    PartState.RETRY_WAIT: frozenset(
        _RETRYABLE
        | {
            PartState.UPLOADED,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.PAUSED: frozenset(
        {
            PartState.PENDING_UPLOAD,
            PartState.UPLOADING,
            PartState.PENDING_CLOUD,
            PartState.CLOUD_UPLOADING,
            PartState.RETRY_WAIT,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.FAILED: frozenset(
        _RETRYABLE
        | {
            PartState.UPLOADED,
            PartState.CANCELED,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.SPACE_BLOCKED: frozenset(
        {
            PartState.PENDING,
            PartState.RECORDING,
            PartState.FAILED,
            PartState.CANCELED,
            PartState.DISCARDED,
        }
    ),
    PartState.LOCAL_ONLY: frozenset(
        {
            PartState.PENDING_UPLOAD,
            PartState.UPLOADING,
            PartState.PENDING_CLOUD,
            PartState.CLOUD_UPLOADING,
            PartState.DELETED,
            PartState.DISCARDED,
            PartState.CANCELED,
        }
    ),
    PartState.CANCELED: frozenset(
        {
            PartState.PENDING_UPLOAD,
            PartState.UPLOADING,
            PartState.PENDING_CLOUD,
            PartState.CLOUD_UPLOADING,
            PartState.DISCARDED,
            PartState.DELETED,
        }
    ),
    PartState.DISCARDED: frozenset(
        {
            PartState.PENDING_UPLOAD,
            PartState.UPLOADING,
            PartState.DELETED,
        }
    ),
    PartState.DELETED: frozenset(),
}


def normalize_part_state(value: object) -> str:
    """Map any historical status string onto a canonical ``PartState`` value."""

    text = str(value or "").strip()
    if not text:
        return PartState.PENDING.value
    upper = text.upper()
    alias = LEGACY_ALIASES.get(upper)
    if alias is not None:
        return alias.value
    try:
        return PartState(upper).value
    except ValueError:
        return PartState.FAILED.value


def part_state(value: object) -> PartState:
    return PartState(normalize_part_state(value))


def can_transition(current: object, target: object) -> bool:
    source = part_state(current)
    destination = part_state(target)
    if source == destination:
        return True
    return destination in _ALLOWED_TRANSITIONS.get(source, frozenset())


def assert_part_transition(current: object, target: object) -> None:
    if not can_transition(current, target):
        raise InvalidPartTransition(str(current), str(target))


def is_terminal(value: object) -> bool:
    return part_state(value) in TERMINAL_STATES


def protects_local_files(value: object) -> bool:
    return part_state(value) in PROTECTED_STATES


def allowed_targets(current: object) -> frozenset[str]:
    source = part_state(current)
    return frozenset(item.value for item in _ALLOWED_TRANSITIONS.get(source, frozenset()))
