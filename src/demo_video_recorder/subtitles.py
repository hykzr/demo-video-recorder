"""Subtitle timing and SRT writing utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from collections.abc import Mapping
import re
import time

from demo_video_recorder.defaults import DEFAULTS

_TIMING_RE = re.compile(
    r"^(?P<start>\d{2,}:\d{2}:\d{2},\d{3}) --> " r"(?P<end>\d{2,}:\d{2}:\d{2},\d{3})$"
)


def format_srt_time(value: float | timedelta) -> str:
    """Format seconds or a timedelta as an SRT timestamp."""

    if isinstance(value, timedelta):
        seconds = value.total_seconds()
    else:
        seconds = float(value)

    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def parse_srt_time(value: str) -> float:
    """Parse an SRT timestamp and return seconds."""

    hours_text, minutes_text, rest = value.split(":", 2)
    seconds_text, milliseconds_text = rest.split(",", 1)
    return (
        int(hours_text) * 3600
        + int(minutes_text) * 60
        + int(seconds_text)
        + int(milliseconds_text) / 1000
    )


@dataclass
class _PendingCue:
    text: str
    start_seconds: float


@dataclass(frozen=True)
class CueDisplay:
    """Timing returned for a cue that should remain on-screen."""

    display_until_seconds: float


SubtitleStyleValue = str | int | float | bool

_ASS_STYLE_KEYS = {
    "font_name": "Fontname",
    "fontname": "Fontname",
    "font_size": "Fontsize",
    "fontsize": "Fontsize",
    "primary_color": "PrimaryColour",
    "primary_colour": "PrimaryColour",
    "primarycolour": "PrimaryColour",
    "primarycolor": "PrimaryColour",
    "secondary_color": "SecondaryColour",
    "secondary_colour": "SecondaryColour",
    "secondarycolour": "SecondaryColour",
    "secondarycolor": "SecondaryColour",
    "outline_color": "OutlineColour",
    "outline_colour": "OutlineColour",
    "outlinecolour": "OutlineColour",
    "outlinecolor": "OutlineColour",
    "back_color": "BackColour",
    "back_colour": "BackColour",
    "backcolour": "BackColour",
    "backcolor": "BackColour",
    "bold": "Bold",
    "italic": "Italic",
    "underline": "Underline",
    "strike_out": "StrikeOut",
    "strikeout": "StrikeOut",
    "border_style": "BorderStyle",
    "borderstyle": "BorderStyle",
    "outline": "Outline",
    "shadow": "Shadow",
    "alignment": "Alignment",
    "margin_left": "MarginL",
    "marginl": "MarginL",
    "margin_right": "MarginR",
    "marginr": "MarginR",
    "margin_vertical": "MarginV",
    "marginv": "MarginV",
}
_ASS_COLOR_KEYS = {"PrimaryColour", "SecondaryColour", "OutlineColour", "BackColour"}
_ASS_BOOLEAN_KEYS = {"Bold", "Italic", "Underline", "StrikeOut"}
_ASS_ALIGNMENT_NAMES = {
    "bottom_left": 1,
    "bottom_center": 2,
    "bottom_centre": 2,
    "bottom_right": 3,
    "middle_left": 4,
    "middle_center": 5,
    "middle_centre": 5,
    "middle_right": 6,
    "top_left": 7,
    "top_center": 8,
    "top_centre": 8,
    "top_right": 9,
}


@dataclass(frozen=True)
class SubtitleStyle:
    """Style used when burning SRT subtitles through ffmpeg/libass."""

    font_name: str | None = None
    font_size: int | float | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    outline_color: str | None = None
    back_color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strike_out: bool | None = None
    border_style: int | None = None
    outline: int | float | None = None
    shadow: int | float | None = None
    alignment: int | str | None = None
    margin_left: int | None = None
    margin_right: int | None = None
    margin_vertical: int | None = None
    extra: Mapping[str, SubtitleStyleValue] = field(default_factory=dict)

    def to_force_style(self) -> str:
        """Return this style as an ffmpeg subtitles ``force_style`` value."""

        values: dict[str, SubtitleStyleValue] = {}
        for field_name in (
            "font_name",
            "font_size",
            "primary_color",
            "secondary_color",
            "outline_color",
            "back_color",
            "bold",
            "italic",
            "underline",
            "strike_out",
            "border_style",
            "outline",
            "shadow",
            "alignment",
            "margin_left",
            "margin_right",
            "margin_vertical",
        ):
            value = getattr(self, field_name)
            if value is not None:
                values[field_name] = value
        values.update(self.extra)
        return _style_mapping_to_force_style(values)


SubtitleStyleLike = SubtitleStyle | Mapping[str, SubtitleStyleValue] | str | None


def subtitle_style_to_force_style(style: SubtitleStyleLike) -> str | None:
    """Normalize a subtitle style value for ffmpeg's subtitles filter."""

    if style is None:
        return None
    if isinstance(style, str):
        trimmed = style.strip()
        return trimmed or None
    if isinstance(style, SubtitleStyle):
        return style.to_force_style() or None
    return _style_mapping_to_force_style(style) or None


def _style_mapping_to_force_style(
    style: Mapping[str, SubtitleStyleValue],
) -> str:
    parts: list[str] = []
    for key, value in style.items():
        if value is None:
            continue
        ass_key = _ass_style_key(key)
        parts.append(f"{ass_key}={_format_ass_style_value(ass_key, value)}")
    return ",".join(parts)


def _ass_style_key(key: str) -> str:
    return _ASS_STYLE_KEYS.get(key.replace("-", "_").lower(), key)


def _format_ass_style_value(key: str, value: SubtitleStyleValue) -> str:
    if key in _ASS_COLOR_KEYS:
        return _format_ass_color(str(value))
    if key in _ASS_BOOLEAN_KEYS and isinstance(value, bool):
        return "-1" if value else "0"
    if key == "Alignment" and isinstance(value, str):
        return str(_ASS_ALIGNMENT_NAMES.get(value.replace("-", "_").lower(), value))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_ass_color(value: str) -> str:
    """Convert CSS-style hex colors to ASS ``&HAABBGGRR`` colors."""

    trimmed = value.strip()
    if trimmed.upper().startswith("&H"):
        return trimmed

    hex_value = trimmed[1:] if trimmed.startswith("#") else trimmed
    if len(hex_value) == 3:
        hex_value = "".join(character * 2 for character in hex_value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", hex_value):
        return trimmed

    red = hex_value[0:2]
    green = hex_value[2:4]
    blue = hex_value[4:6]
    alpha = "00"
    if len(hex_value) == 8:
        # CSS #RRGGBBAA alpha is opacity; ASS alpha is transparency.
        alpha = f"{255 - int(hex_value[6:8], 16):02x}"
    return f"&H{alpha}{blue}{green}{red}".upper()


class SubtitleWriter:
    """Writes sequential SRT cues using a monotonic clock."""

    def __init__(
        self,
        path: str | Path,
        *,
        words_per_minute: int = DEFAULTS.words_per_minute,
        min_pause_seconds: float = DEFAULTS.min_pause_seconds,
        manual_pause: bool = False,
    ) -> None:
        self.path = Path(path)
        self.words_per_minute = words_per_minute
        self.min_pause_seconds = min_pause_seconds
        self.manual_pause = manual_pause
        self._index = 1
        self._clock_started_at: float | None = None
        self._pending: _PendingCue | None = None

    @property
    def is_started(self) -> bool:
        return self._clock_started_at is not None

    def reset_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._index = 1
        self._pending = None

    def start_clock(self) -> None:
        self._clock_started_at = time.perf_counter()

    def elapsed_seconds(self) -> float:
        if self._clock_started_at is None:
            return 0.0
        return time.perf_counter() - self._clock_started_at

    def read_delay_seconds(self, text: str) -> float:
        if not text.strip():
            return 0.0
        word_count = len(re.findall(r"\S+", text.strip()))
        words_per_second = max(self.words_per_minute / 60.0, 1.0)
        return max(self.min_pause_seconds, word_count / words_per_second)

    def open_cue(self, text: str) -> float | None:
        trimmed = text.strip()
        if not trimmed:
            return None

        if self._clock_started_at is None:
            self.start_clock()

        start_seconds = self.elapsed_seconds()
        self.complete_cue(end_seconds=start_seconds)
        self._pending = _PendingCue(trimmed, start_seconds)
        return start_seconds

    def start_cue(self, text: str) -> CueDisplay | None:
        start_seconds = self.open_cue(text)
        if start_seconds is None:
            return None
        return CueDisplay(start_seconds + self.read_delay_seconds(text.strip()))

    def wait_for_display(self, cue: CueDisplay | None) -> None:
        if cue is None:
            return

        if self.manual_pause:
            input()
            self.complete_cue()
            return

        remaining = cue.display_until_seconds - self.elapsed_seconds()
        if remaining > 0:
            time.sleep(remaining)

    def add_cue(self, text: str, *, wait: bool = True) -> None:
        cue = self.start_cue(text)
        if wait:
            self.wait_for_display(cue)

    def complete_cue(self, *, end_seconds: float | None = None) -> None:
        if self._pending is None:
            return

        if end_seconds is None:
            end_seconds = self.elapsed_seconds()

        start_seconds = self._pending.start_seconds
        if end_seconds <= start_seconds:
            end_seconds = start_seconds + 0.001

        self._append_entry(self._pending.text, start_seconds, end_seconds)
        self._pending = None

    def trim_to_duration(self, duration_seconds: float) -> None:
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            return

        blocks = re.split(
            r"(?:\r?\n){2,}", self.path.read_text(encoding="utf-8").strip()
        )
        output_lines: list[str] = []
        next_index = 1

        for block in blocks:
            lines = block.splitlines()
            if len(lines) < 2:
                continue

            match = _TIMING_RE.match(lines[1].strip())
            if match is None:
                continue

            start_seconds = parse_srt_time(match.group("start"))
            end_seconds = parse_srt_time(match.group("end"))
            if start_seconds >= duration_seconds:
                continue

            end_seconds = min(end_seconds, duration_seconds)
            if end_seconds <= start_seconds:
                continue

            output_lines.extend(
                [
                    str(next_index),
                    f"{format_srt_time(start_seconds)} --> {format_srt_time(end_seconds)}",
                    *lines[2:],
                    "",
                ]
            )
            next_index += 1

        self.path.write_text("\n".join(output_lines), encoding="utf-8")

    def _append_entry(
        self, text: str, start_seconds: float, end_seconds: float
    ) -> None:
        lines = [
            str(self._index),
            f"{format_srt_time(start_seconds)} --> {format_srt_time(end_seconds)}",
            text,
            "",
        ]
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")
        self._index += 1
