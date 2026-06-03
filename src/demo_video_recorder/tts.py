"""Text-to-speech backends for narration audio."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import asyncio
import shutil
import subprocess
from typing import Protocol

from demo_video_recorder.errors import DependencyMissingError, RecordingError


@dataclass(frozen=True)
class SynthesizedAudio:
    """A generated narration clip and its measured duration."""

    path: Path
    duration_seconds: float


@dataclass(frozen=True)
class NarrationClip:
    """A synthesized narration clip placed on the recording timeline."""

    text: str
    path: Path
    start_seconds: float
    duration_seconds: float


class TTSBackend(Protocol):
    """Interface used by the recorder to synthesize narration clips."""

    save_dir: Path

    def synthesize(self, text: str) -> SynthesizedAudio:
        """Create audio for ``text`` and return its path and duration."""
        return SynthesizedAudio(path=Path(), duration_seconds=0)

    def cleanup(self) -> None:
        """Remove intermediate clip artifacts when they are no longer needed."""


class EdgeTTSBackend:
    """Generate narration clips with the optional ``edge-tts`` package."""

    def __init__(
        self,
        *,
        save_dir: str | Path,
        speaker: str = "en-US-AvaNeural",
        speed: str = "+0%",
        volume: str = "+0%",
        ffprobe: str = "ffprobe",
    ) -> None:
        self.save_dir = Path(save_dir)
        self.speaker = speaker
        self.speed = speed
        self.volume = volume
        self.ffprobe = ffprobe
        self._index = 1

    def synthesize(self, text: str) -> SynthesizedAudio:
        """Render ``text`` to a new MP3 file and measure the real duration."""

        trimmed = text.strip()
        if not trimmed:
            raise RecordingError("Cannot synthesize empty narration text.")

        self._ensure_available()
        self.save_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.save_dir / f"clip-{self._index:04}.mp3"
        self._index += 1

        edge_tts = import_module("edge_tts")
        communicate = edge_tts.Communicate(
            trimmed,
            self.speaker,
            rate=self.speed,
            volume=self.volume,
        )
        save_sync = getattr(communicate, "save_sync", None)
        if callable(save_sync):
            save_sync(str(output_path))
        else:
            asyncio.run(communicate.save(str(output_path)))

        return SynthesizedAudio(
            path=output_path,
            duration_seconds=self._probe_duration_seconds(output_path),
        )

    def cleanup(self) -> None:
        """Remove generated per-cue clips."""

        shutil.rmtree(self.save_dir, ignore_errors=True)

    def _ensure_available(self) -> None:
        if shutil.which(self.ffprobe) is None:
            raise DependencyMissingError(f"Missing external dependency: {self.ffprobe}")

        try:
            import_module("edge_tts")
        except ModuleNotFoundError as exc:
            raise DependencyMissingError(
                "Missing Python dependency: edge-tts. Install it with `uv add edge-tts`."
            ) from exc

    def _probe_duration_seconds(self, media_path: Path) -> float:
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RecordingError(
                f"ffprobe failed while probing generated narration audio.\n{result.stderr.strip()}"
            )

        try:
            duration = float(result.stdout.strip().splitlines()[0])
        except (IndexError, ValueError) as exc:
            raise RecordingError(
                f"Could not parse ffprobe duration for narration clip: {result.stdout!r}"
            ) from exc

        if duration <= 0:
            raise RecordingError(
                f"Generated narration clip has an invalid duration: {duration}"
            )
        return duration
