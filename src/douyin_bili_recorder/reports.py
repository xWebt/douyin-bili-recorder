from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from .analytics import AnalyticsStore
from .paths import anchor_dir, safe_path_name


PAGE_SIZE = (1240, 1754)
MARGIN = 72
INK = "#17211d"
MUTED = "#5f6d67"
LINE = "#d8dfdb"
SURFACE = "#f4f7f5"
SIGNAL = "#2f9e68"
SIGNAL_SOFT = "#dff3e7"
AMBER = "#c4842e"
DANGER = "#c44f49"
WHITE = "#ffffff"

FONT_REGULAR = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
FONT_BOLD = Path("/System/Library/Fonts/STHeiti Medium.ttc")


class ReportGenerator:
    def __init__(self, video_dir: Path, timezone: str = "Asia/Shanghai") -> None:
        self.video_dir = video_dir
        self.timezone = timezone
        self.analytics = AnalyticsStore(video_dir, timezone)

    def generate(
        self,
        target_name: str,
        period: str,
        *,
        anchor_date: date | None = None,
    ) -> Path:
        if period not in {"week", "month"}:
            raise ValueError("period must be week or month")
        base = anchor_date or datetime.now(ZoneInfo(self.timezone)).date()
        if period == "week":
            start = base - timedelta(days=base.isoweekday() - 1)
            end = start + timedelta(days=6)
            label = f"周报 · {start.isoformat()} 至 {end.isoformat()}"
            filename = f"{safe_path_name(target_name)}_周报_{start:%Y%m%d}_{end:%Y%m%d}.pdf"
        else:
            first = base.replace(day=1)
            next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)
            start = first
            label = f"月报 · {start:%Y年%m月}"
            filename = f"{safe_path_name(target_name)}_月报_{start:%Y%m}.pdf"

        sessions = self._load_sessions(target_name, start, end)
        output_dir = anchor_dir(self.video_dir, target_name) / "数据报告"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        pages = self._render_pages(target_name, label, start, end, sessions)
        pages[0].save(
            output_path,
            "PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=150.0,
        )
        return output_path

    def _load_sessions(self, target_name: str, start: date, end: date) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        cursor = start.replace(day=1)
        while cursor <= end:
            month = cursor.strftime("%Y-%m")
            for item in self.analytics.month(target_name, month).get("sessions", []):
                if not isinstance(item, dict):
                    continue
                item_date = self._parse_date(item.get("date"))
                if item_date is None or not (start <= item_date <= end):
                    continue
                session_id = str(item.get("session_id") or "")
                key = session_id or f"{item.get('date')}-{item.get('detected_start_iso')}-{len(records)}"
                records[key] = item
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        return sorted(records.values(), key=lambda item: str(item.get("detected_start_iso") or item.get("date") or ""))

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    def _render_pages(
        self,
        target_name: str,
        label: str,
        start: date,
        end: date,
        sessions: list[dict[str, Any]],
    ) -> list[Image.Image]:
        summary_page = self._summary_page(target_name, label, start, end, sessions)
        pages = [summary_page]
        rows = list(reversed(sessions))
        for offset in range(0, len(rows), 22):
            pages.append(self._table_page(target_name, label, rows[offset : offset + 22], offset + 1))
        return pages

    def _summary_page(
        self,
        target_name: str,
        label: str,
        start: date,
        end: date,
        sessions: list[dict[str, Any]],
    ) -> Image.Image:
        image = Image.new("RGB", PAGE_SIZE, WHITE)
        draw = ImageDraw.Draw(image)
        title_font = self._font(42, bold=True)
        subtitle_font = self._font(20)
        body_font = self._font(20)
        metric_font = self._font(36, bold=True)
        metric_label_font = self._font(17)

        draw.rectangle((0, 0, PAGE_SIZE[0], 210), fill=INK)
        draw.text((MARGIN, 58), f"{target_name} · 直播数据{label.split(' · ', 1)[0]}", fill=WHITE, font=title_font)
        draw.text((MARGIN, 128), f"{label}  |  生成时间 {datetime.now(ZoneInfo(self.timezone)):%Y-%m-%d %H:%M}", fill="#c9d5cf", font=subtitle_font)

        metrics = self._metrics(sessions)
        card_width = (PAGE_SIZE[0] - MARGIN * 2 - 24) // 3
        card_height = 130
        for index, (label_text, value) in enumerate(metrics.items()):
            row, col = divmod(index, 3)
            x = MARGIN + col * (card_width + 12)
            y = 255 + row * (card_height + 14)
            draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=12, fill=SURFACE, outline=LINE, width=2)
            draw.text((x + 22, y + 25), label_text, fill=MUTED, font=metric_label_font)
            draw.text((x + 22, y + 59), value, fill=INK, font=metric_font)

        section_y = 565
        draw.text((MARGIN, section_y), "开播延迟", fill=INK, font=body_font)
        draw.text((PAGE_SIZE[0] // 2 + 20, section_y), "直播时长", fill=INK, font=body_font)
        delay_values = [int(item.get("late_minutes") or 0) for item in sessions]
        duration_hours = [int(item.get("duration_seconds") or 0) / 3600 for item in sessions]
        left_box = (MARGIN, section_y + 42, PAGE_SIZE[0] // 2 - 20, section_y + 430)
        right_box = (PAGE_SIZE[0] // 2 + 20, section_y + 42, PAGE_SIZE[0] - MARGIN, section_y + 430)
        self._draw_bar_chart(draw, left_box, delay_values, AMBER, "分钟")
        self._draw_bar_chart(draw, right_box, duration_hours, SIGNAL, "小时")

        note_y = 1060
        draw.rounded_rectangle((MARGIN, note_y, PAGE_SIZE[0] - MARGIN, note_y + 180), radius=12, fill=SIGNAL_SOFT)
        draw.text((MARGIN + 26, note_y + 26), "统计口径", fill=INK, font=self._font(22, bold=True))
        notes = [
            f"统计区间：{start.isoformat()} 至 {end.isoformat()}",
            "迟到按预计开播时间后超过 5 分钟计算；断流重连不重复计场次。",
            "仅统计有录像或稿件的主播场次；仅数据模式也会计入直播统计。",
        ]
        for index, text in enumerate(notes):
            draw.text((MARGIN + 26, note_y + 68 + index * 34), text, fill=MUTED, font=self._font(17))
        draw.text((MARGIN, PAGE_SIZE[1] - 70), f"{target_name} · DouyinBiliRecorder", fill=MUTED, font=self._font(15))
        return image

    def _table_page(
        self,
        target_name: str,
        label: str,
        sessions: list[dict[str, Any]],
        page_number: int,
    ) -> Image.Image:
        image = Image.new("RGB", PAGE_SIZE, WHITE)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, PAGE_SIZE[0], 130), fill=INK)
        draw.text((MARGIN, 36), f"{target_name} · 场次明细", fill=WHITE, font=self._font(34, bold=True))
        draw.text((MARGIN, 88), f"{label}  |  第 {page_number} 页", fill="#c9d5cf", font=self._font(17))

        columns = [
            ("日期", 60, 150),
            ("开播", 210, 110),
            ("时长", 320, 120),
            ("状态", 440, 260),
            ("重连", 700, 90),
            ("稿件", 790, 320),
        ]
        header_y = 175
        row_height = 54
        draw.rectangle((MARGIN, header_y, PAGE_SIZE[0] - MARGIN, header_y + row_height), fill=SURFACE)
        for title, x, width in columns:
            draw.text((MARGIN + x + 12, header_y + 16), title, fill=MUTED, font=self._font(17, bold=True))
        y = header_y + row_height
        if not sessions:
            draw.text((MARGIN + 20, y + 32), "本区间暂无直播场次。", fill=MUTED, font=self._font(20))
        for index, item in enumerate(sessions):
            if index % 2:
                draw.rectangle((MARGIN, y, PAGE_SIZE[0] - MARGIN, y + row_height), fill="#fafcfb")
            detected = str(item.get("detected_start_iso") or "")
            duration = int(item.get("duration_seconds") or 0)
            status = f"迟到 {item.get('late_minutes') or 0} 分钟" if item.get("late") else "正常"
            values = [
                str(item.get("date") or "-"),
                detected[11:16] if len(detected) >= 16 else "-",
                self._duration_text(duration),
                status,
                str(item.get("reconnect_count") or 0),
                str(item.get("bvid") or item.get("status") or "-"),
            ]
            for (_, x, _width), value in zip(columns, values):
                draw.text((MARGIN + x + 12, y + 15), value, fill=INK, font=self._font(16))
            draw.line((MARGIN, y, PAGE_SIZE[0] - MARGIN, y), fill=LINE, width=1)
            y += row_height
        draw.line((MARGIN, y, PAGE_SIZE[0] - MARGIN, y), fill=LINE, width=1)
        draw.text((MARGIN, PAGE_SIZE[1] - 70), f"{target_name} · DouyinBiliRecorder", fill=MUTED, font=self._font(15))
        return image

    def _metrics(self, sessions: list[dict[str, Any]]) -> dict[str, str]:
        durations = [int(item.get("duration_seconds") or 0) for item in sessions]
        live_dates = {str(item.get("date")) for item in sessions if item.get("date")}
        late_items = [item for item in sessions if item.get("late")]
        late_dates = {str(item.get("date")) for item in late_items if item.get("date")}
        total = sum(durations)
        average = round(total / len(durations)) if durations else 0
        on_time_rate = round((len(sessions) - len(late_items)) / len(sessions) * 100, 1) if sessions else 100.0
        reconnects = sum(int(item.get("reconnect_count") or 0) for item in sessions)
        uploads = len({str(item.get("bvid")) for item in sessions if item.get("bvid")})
        return {
            "直播天数": str(len(live_dates)),
            "直播场次": str(len(sessions)),
            "总时长": self._duration_text(total),
            "平均单场": self._duration_text(average),
            "按时率": f"{on_time_rate:.1f}%",
            "迟到日 / 场": f"{len(late_dates)} / {len(late_items)}",
            "断流重连": str(reconnects),
            "已投稿稿件": str(uploads),
            "有效数据": f"{len(sessions)} 场",
        }

    def _draw_bar_chart(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        values: list[float],
        color: str,
        unit: str,
    ) -> None:
        left, top, right, bottom = box
        draw.rounded_rectangle(box, radius=12, fill="#fbfcfb", outline=LINE, width=2)
        chart = (left + 42, top + 38, right - 28, bottom - 48)
        draw.line((chart[0], chart[3], chart[2], chart[3]), fill=LINE, width=2)
        if not values:
            draw.text((left + 32, top + 30), "暂无数据", fill=MUTED, font=self._font(18))
            return
        maximum = max(1.0, max(values))
        available_width = chart[2] - chart[0]
        bar_width = max(5, min(34, available_width / max(1, len(values)) * 0.62))
        for index, value in enumerate(values):
            x = chart[0] + (index + 0.5) * available_width / len(values) - bar_width / 2
            height = max(2, (float(value) / maximum) * (chart[3] - chart[1]))
            draw.rounded_rectangle(
                (x, chart[3] - height, x + bar_width, chart[3]),
                radius=3,
                fill=color,
            )
        draw.text((left + 18, top + 10), f"最高 {maximum:.1f} {unit}", fill=MUTED, font=self._font(14))

    @staticmethod
    def _duration_text(seconds: int) -> str:
        hours, remainder = divmod(max(0, int(seconds)), 3600)
        minutes = remainder // 60
        return f"{hours}h{minutes:02d}m"

    @staticmethod
    def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        path = FONT_BOLD if bold else FONT_REGULAR
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            return ImageFont.load_default()


def available_report_fonts() -> Iterable[Path]:
    yield FONT_REGULAR
    yield FONT_BOLD
