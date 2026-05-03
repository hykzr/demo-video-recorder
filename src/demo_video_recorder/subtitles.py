"""Subtitle timing and SRT writing utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import re
import time


_TIMING_RE = re.compile(
    r"^(?P<start>\d{2,}:\d{2}:\d{2},\d{3}) --> "
    r"(?P<end>\d{2,}:\d{2}:\d{2},\d{3})$"
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


class SubtitleWriter:
    """Writes sequential SRT cues using a monotonic clock."""

    def __init__(
        self,
        path: str | Path,
        *,
        words_per_minute: int = 170,
        min_pause_seconds: float = 2.0,
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

    def start_cue(self, text: str) -> CueDisplay | None:
        trimmed = text.strip()
        if not trimmed:
            return None

        if self._clock_started_at is None:
            self.start_clock()

        start_seconds = self.elapsed_seconds()
        self.complete_cue(end_seconds=start_seconds)
        self._pending = _PendingCue(trimmed, start_seconds)
        return CueDisplay(start_seconds + self.read_delay_seconds(trimmed))

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

        blocks = re.split(r"(?:\r?\n){2,}", self.path.read_text(encoding="utf-8").strip())
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

    def _append_entry(self, text: str, start_seconds: float, end_seconds: float) -> None:
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
