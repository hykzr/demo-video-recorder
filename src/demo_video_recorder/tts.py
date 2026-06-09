"""Text-to-speech backends for narration audio."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import asyncio
import hashlib
import os
import platform
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

    def __init__(
        self,
        *,
        save_dir: str | Path,
        ffprobe: str = "ffprobe",
        cache: bool = False,
    ) -> None:
        self.save_dir = Path(save_dir)
        self.ffprobe = ffprobe
        self.cache = cache
        self._index = 1

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

    async def synthesize_async(self, text: str) -> SynthesizedAudio:
        """Async wrapper around ``synthesize()`` for preparing clips ahead of capture."""

        return await asyncio.to_thread(self.synthesize, text)

    def cleanup(self) -> None:
        """Remove intermediate clip artifacts when they are no longer needed."""

        if self.cache:
            return
        shutil.rmtree(self.save_dir, ignore_errors=True)

    def list_speakers(self) -> list[str]:
        """Return available voice identifiers for this backend."""

        return []

    @abstractmethod
    def save_audio(self, text: str) -> Path:
        """Render ``text`` to disk and return the created audio file."""

    def _output_path_for(self, text: str, suffix: str) -> Path:
        if self.cache:
            key = f"{self._cache_key()}\0{text}"
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            output_path = self.save_dir / f"clip-{digest}{suffix}"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            return output_path

        output_path = self.save_dir / f"clip-{self._index:04}{suffix}"
        self._index += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _cache_key(self) -> str:
        return type(self).__name__

    def _can_reuse(self, output_path: Path) -> bool:
        return self.cache and output_path.exists() and output_path.stat().st_size > 0

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
        cache: bool = False,
    ) -> None:
        super().__init__(save_dir=save_dir, ffprobe=ffprobe, cache=cache)
        self.speaker = speaker
        self.speed = speed
        self.volume = volume

    def save_audio(self, text: str) -> Path:
        """Render ``text`` to a new MP3 file and return its path."""

        output_path = self._output_path_for(text, ".mp3")
        if self._can_reuse(output_path):
            return output_path

        try:
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
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            raise RecordingError(
                "Edge TTS synthesis failed. "
                f"backend=edge-tts speaker={self.speaker!r} "
                f"speed={self.speed!r} volume={self.volume!r} "
                f"text_length={len(text)} output={str(output_path)!r} "
                f"error_type={type(exc).__name__} error={exc}"
            ) from exc
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

    def _cache_key(self) -> str:
        return (
            f"{type(self).__name__}:"
            f"speaker={self.speaker}:speed={self.speed}:volume={self.volume}"
        )


class MacOSTTSBackend(TTSBackend):
    """Generate narration clips with the macOS ``say`` command."""

    def __init__(
        self,
        *,
        save_dir: str | Path,
        speaker: str | None = None,
        words_per_minute: int | None = None,
        ffprobe: str = "ffprobe",
        command: str = "say",
        cache: bool = False,
    ) -> None:
        super().__init__(save_dir=save_dir, ffprobe=ffprobe, cache=cache)
        self.speaker = speaker
        self.words_per_minute = words_per_minute
        self.command = command

    def save_audio(self, text: str) -> Path:
        """Render ``text`` to a new AIFF file and return its path."""

        if shutil.which(self.command) is None:
            raise DependencyMissingError(f"Missing external dependency: {self.command}")

        output_path = self._output_path_for(text, ".aiff")
        if self._can_reuse(output_path):
            return output_path

        command = [self.command]
        if self.speaker:
            command.extend(["-v", self.speaker])
        if self.words_per_minute is not None:
            command.extend(["-r", str(self.words_per_minute)])
        command.extend(["-o", str(output_path), "--", text])

        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RecordingError(
                "macOS native TTS synthesis failed. "
                f"backend=say speaker={self.speaker!r} "
                f"words_per_minute={self.words_per_minute!r} "
                f"text_length={len(text)} output={str(output_path)!r} "
                f"returncode={result.returncode} stderr={result.stderr.strip()!r}"
            )
        return output_path

    def list_speakers(self) -> list[str]:
        if shutil.which(self.command) is None:
            return []
        result = subprocess.run(
            [self.command, "-v", "?"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return []
        return sorted(
            line.split(maxsplit=1)[0]
            for line in result.stdout.splitlines()
            if line.strip()
        )

    def _cache_key(self) -> str:
        return (
            f"{type(self).__name__}:"
            f"speaker={self.speaker}:words_per_minute={self.words_per_minute}"
        )


class WindowsTTSBackend(TTSBackend):
    """Generate narration clips with the native Windows SAPI voice engine."""

    def __init__(
        self,
        *,
        save_dir: str | Path,
        speaker: str | None = None,
        rate: int = 0,
        volume: int = 100,
        ffprobe: str = "ffprobe",
        command: str = "powershell.exe",
        cache: bool = False,
    ) -> None:
        super().__init__(save_dir=save_dir, ffprobe=ffprobe, cache=cache)
        self.speaker = speaker
        self.rate = rate
        self.volume = volume
        self.command = command

    def save_audio(self, text: str) -> Path:
        """Render ``text`` to a new WAV file and return its path."""

        if shutil.which(self.command) is None:
            raise DependencyMissingError(f"Missing external dependency: {self.command}")

        output_path = self._output_path_for(text, ".wav")
        if self._can_reuse(output_path):
            return output_path

        script = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($env:DEMO_TTS_VOICE) { $synth.SelectVoice($env:DEMO_TTS_VOICE) }
    $synth.Rate = [int]$env:DEMO_TTS_RATE
    $synth.Volume = [int]$env:DEMO_TTS_VOLUME
    $synth.SetOutputToWaveFile($env:DEMO_TTS_OUTPUT)
    $synth.Speak($env:DEMO_TTS_TEXT)
}
finally {
    $synth.Dispose()
}
"""
        env = os.environ.copy()
        env.update(
            {
                "DEMO_TTS_TEXT": text,
                "DEMO_TTS_OUTPUT": str(output_path),
                "DEMO_TTS_VOICE": self.speaker or "",
                "DEMO_TTS_RATE": str(self.rate),
                "DEMO_TTS_VOLUME": str(self.volume),
            }
        )
        result = subprocess.run(
            [
                self.command,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RecordingError(
                "Windows native TTS synthesis failed. "
                f"backend=sapi speaker={self.speaker!r} rate={self.rate!r} "
                f"volume={self.volume!r} text_length={len(text)} "
                f"output={str(output_path)!r} returncode={result.returncode} "
                f"stderr={result.stderr.strip()!r}"
            )
        return output_path

    def list_speakers(self) -> list[str]:
        if shutil.which(self.command) is None:
            return []
        script = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
}
finally {
    $synth.Dispose()
}
"""
        result = subprocess.run(
            [
                self.command,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return []
        return sorted(
            line.strip() for line in result.stdout.splitlines() if line.strip()
        )

    def _cache_key(self) -> str:
        return (
            f"{type(self).__name__}:"
            f"speaker={self.speaker}:rate={self.rate}:volume={self.volume}"
        )


def NativeTTSBackend(
    *,
    save_dir: str | Path,
    speaker: str | None = None,
    ffprobe: str = "ffprobe",
    cache: bool = False,
    **kwargs: object,
) -> TTSBackend:
    """Return the native TTS backend for the current platform."""

    system = platform.system()
    if system == "Darwin":
        return MacOSTTSBackend(
            save_dir=save_dir,
            speaker=speaker,
            ffprobe=ffprobe,
            cache=cache,
            **kwargs,  # type: ignore
        )
    if system == "Windows":
        return WindowsTTSBackend(
            save_dir=save_dir,
            speaker=speaker,
            ffprobe=ffprobe,
            cache=cache,
            **kwargs,  # type: ignore
        )
    raise DependencyMissingError(
        f"Native TTS is only available on macOS and Windows, not {system or 'unknown'}."
    )
