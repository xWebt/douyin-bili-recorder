from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, TargetConfig
from .models import SessionRecord
from .process import ProcessRunner
from .timeutil import build_title

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BVID_RE = re.compile(r"\bBV[0-9A-Za-z]{10}\b")


@dataclass(slots=True)
class UploadResult:
    bvid: str | None
    verified: bool
    messages: list[str]


class BiliupUploader:
    def __init__(self, config: AppConfig, runner: ProcessRunner, logger: logging.Logger) -> None:
        self.config = config
        self.runner = runner
        self.logger = logger

    def upload_session(
        self,
        target: TargetConfig,
        session: SessionRecord,
        session_dir: Path,
        title: str | None = None,
    ) -> UploadResult:
        files = session.media_paths(session_dir)
        if not files:
            raise RuntimeError(f"session {session.session_id} has no media to upload")
        if not self.config.cookie_file.exists():
            raise RuntimeError(f"Bilibili cookie file does not exist: {self.config.cookie_file}")

        resolved_title = title or build_title(
            target.title_template,
            target.name,
            target.url,
            session,
            self.config.timezone,
        )
        source = target.source or target.url

        existing = self.find_bvid_by_title(resolved_title)
        if existing:
            self.logger.info("submission already exists for title %s: %s", resolved_title, existing)
            return UploadResult(existing, True, ["submission already exists"])

        first = files[0]
        command = [
            self.config.biliup_bin,
            "-u",
            str(self.config.cookie_file),
            "upload",
            str(first),
            "--line",
            self.config.upload_line,
            "--title",
            resolved_title,
            "--desc",
            self._description(target, session),
            "--copyright",
            str(target.copyright),
            "--source",
            source,
            "--tid",
            str(target.tid),
            "--tag",
            ",".join(target.tags),
        ]
        if not target.public:
            command.extend(["--is-only-self", "1"])

        result = self.runner.run(command)
        messages = list(result.lines)
        if result.returncode != 0:
            raise RuntimeError(f"Bilibili submission command failed with code {result.returncode}")

        bvid = self._wait_for_bvid(resolved_title)
        if not bvid:
            return UploadResult(None, False, messages + ["submission was sent but BVID lookup timed out"])

        for index, media_path in enumerate(files[1:], start=2):
            part_title = f"{target.name}｜{session.detected_start_iso or session.session_id}｜P{index:02d}"
            append_command = [
                self.config.biliup_bin,
                "-u",
                str(self.config.cookie_file),
                "append",
                "--vid",
                bvid,
                "--line",
                self.config.upload_line,
                str(media_path),
                "--title",
                part_title,
                "--desc",
                self._description(target, session),
                "--copyright",
                str(target.copyright),
                "--source",
                source,
                "--tid",
                str(target.tid),
                "--tag",
                ",".join(target.tags),
            ]
            if not target.public:
                append_command.extend(["--is-only-self", "1"])
            append_result = self.runner.run(append_command)
            messages.extend(append_result.lines)
            if append_result.returncode != 0:
                raise RuntimeError(f"failed to append {media_path.name} to {bvid}")

        return UploadResult(bvid, True, messages)

    def upload_part(
        self,
        target: TargetConfig,
        session: SessionRecord,
        media_path: Path,
        *,
        part_index: int,
        title: str,
        bvid: str | None = None,
    ) -> UploadResult:
        if not self.config.cookie_file.exists():
            raise RuntimeError(f"Bilibili cookie file does not exist: {self.config.cookie_file}")
        source = target.source or target.url
        description = self._description(target, session)
        if bvid:
            command = [
                self.config.biliup_bin,
                "-u",
                str(self.config.cookie_file),
                "append",
                "--vid",
                bvid,
                "--line",
                self.config.upload_line,
                str(media_path),
                "--title",
                title,
                "--desc",
                description,
                "--copyright",
                str(target.copyright),
                "--source",
                source,
                "--tid",
                str(target.tid),
                "--tag",
                ",".join(target.tags),
            ]
            if not target.public:
                command.extend(["--is-only-self", "1"])
            result = self.runner.run(command)
            if result.returncode != 0:
                raise RuntimeError(f"Bilibili append command failed with code {result.returncode}")
            return UploadResult(bvid, True, list(result.lines))

        existing = self.find_bvid_by_title(title)
        if existing:
            return UploadResult(existing, True, ["submission already exists"])
        command = [
            self.config.biliup_bin,
            "-u",
            str(self.config.cookie_file),
            "upload",
            str(media_path),
            "--line",
            self.config.upload_line,
            "--title",
            title,
            "--desc",
            description,
            "--copyright",
            str(target.copyright),
            "--source",
            source,
            "--tid",
            str(target.tid),
            "--tag",
            ",".join(target.tags),
        ]
        if not target.public:
            command.extend(["--is-only-self", "1"])
        result = self.runner.run(command)
        if result.returncode != 0:
            raise RuntimeError(f"Bilibili submission command failed with code {result.returncode}")
        found = self._wait_for_bvid(title)
        return UploadResult(found, bool(found), list(result.lines))

    def find_bvid_by_title(self, title: str) -> str | None:
        filters = (["--is-pubing"], ["--not-pubed"], ["--pubed"])
        for extra in filters:
            command = [self.config.biliup_bin, "-u", str(self.config.cookie_file), "list", *extra]
            completed = self.runner.run(command)
            for line in completed.lines:
                clean = ANSI_RE.sub("", line)
                if title in clean:
                    match = BVID_RE.search(clean)
                    if match:
                        return match.group(0)
        return None

    def _wait_for_bvid(self, title: str) -> str | None:
        attempts = 10
        for index in range(attempts):
            bvid = self.find_bvid_by_title(title)
            if bvid:
                return bvid
            if index < attempts - 1:
                time.sleep(3)
        return None

    def _description(self, target: TargetConfig, session: SessionRecord) -> str:
        source = target.source or target.url
        start = session.detected_start_iso or "unknown"
        return (
            f"抖音直播录像\n"
            f"主播：{target.name}\n"
            f"开播检测时间：{start}\n"
            f"来源：{source}"
        )
