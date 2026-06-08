"""Text-to-speech backends for narration audio."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import asyncio
import shutil
import subprocess
import edge_tts

from demo_video_recorder.errors import DependencyMissingError, RecordingError


@dataclass(frozen=True)
class SynthesizedAudio:
    """A generated narration clip and its measured duration."""

    path: Path
    duration_seconds: float


@dataclass(frozen=True)
class SynthesizedExplanation:
    """Prepared narration text paired with synthesized audio."""

    text: str
    audio: SynthesizedAudio


@dataclass(frozen=True)
class NarrationClip:
    """A synthesized narration clip placed on the recording timeline."""

    text: str
    path: Path
    start_seconds: float
    duration_seconds: float


class TTSBackend(ABC):
    """Common base class for narration synthesis backends."""

    def __init__(self, *, save_dir: str | Path, ffprobe: str = "ffprobe") -> None:
        self.save_dir = Path(save_dir)
        self.ffprobe = ffprobe

    def synthesize(self, text: str) -> SynthesizedAudio:
        """Create audio for ``text`` and return its path and duration."""

        trimmed = text.strip()
        if not trimmed:
            raise RecordingError("Cannot synthesize empty narration text.")

        if shutil.which(self.ffprobe) is None:
            raise DependencyMissingError(f"Missing external dependency: {self.ffprobe}")

        self.save_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.save_audio(trimmed)
        return SynthesizedAudio(
            path=output_path,
            duration_seconds=self._probe_duration_seconds(output_path),
        )

    def cleanup(self) -> None:
        """Remove intermediate clip artifacts when they are no longer needed."""

        shutil.rmtree(self.save_dir, ignore_errors=True)

    def list_speakers(self) -> list[str]:
        """Return available voice identifiers for this backend."""

        return []

    @abstractmethod
    def save_audio(self, text: str) -> Path:
        """Render ``text`` to disk and return the created audio file."""

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


class EdgeTTSBackend(TTSBackend):
    """Generate narration clips with the optional ``edge-tts`` package."""

    def __init__(
        self,
        *,
        save_dir: str | Path,
        speaker: str = "en-US-AvaMultilingualNeural",
        speed: str = "+0%",
        volume: str = "+0%",
        ffprobe: str = "ffprobe",
    ) -> None:
        super().__init__(save_dir=save_dir, ffprobe=ffprobe)
        self.speaker = speaker
        self.speed = speed
        self.volume = volume
        self._index = 1

    def save_audio(self, text: str) -> Path:
        """Render ``text`` to a new MP3 file and return its path."""

        output_path = self.save_dir / f"clip-{self._index:04}.mp3"
        self._index += 1

        communicate = edge_tts.Communicate(
            text,
            self.speaker,
            rate=self.speed,
            volume=self.volume,
        )
        save_sync = getattr(communicate, "save_sync", None)
        if callable(save_sync):
            save_sync(str(output_path))
        else:
            asyncio.run(communicate.save(str(output_path)))
        return output_path

    def list_speakers(self) -> list[str]:
        """Return all available Edge TTS voice names."""

        voices = edge_tts.list_voices()
        if asyncio.iscoroutine(voices):
            voices = asyncio.run(voices)
        return sorted(
            voice["ShortName"]
            for voice in voices
            if isinstance(voice, dict) and "ShortName" in voice
        )
        return []
