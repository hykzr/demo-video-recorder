from __future__ import annotations

from pathlib import Path
import subprocess
import types

import pytest

from demo_video_recorder import DemoVideoRecorder, EdgeTTSBackend, TTSBackend
from demo_video_recorder.subtitles import CueDisplay
from demo_video_recorder.tts import (
    NarrationClip,
    SynthesizedAudio,
    SynthesizedExplanation,
)


def test_tts_backend_synthesize_uses_save_audio_and_probes_duration(
    tmp_path, monkeypatch
) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "hello there"
            path = self.save_dir / "clip-0001.mp3"
            path.write_bytes(b"mp3")
            return path

    monkeypatch.setattr(
        "demo_video_recorder.tts.shutil.which", lambda _: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "demo_video_recorder.tts.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.25\n", ""),
    )

    backend = FakeTTS(save_dir=tmp_path / "tts")
    result = backend.synthesize("hello there")

    assert result.duration_seconds == 1.25
    assert result.path == tmp_path / "tts" / "clip-0001.mp3"
    assert result.path.read_bytes() == b"mp3"


def test_demo_recorder_explain_uses_tts_duration_for_wait(
    tmp_path, monkeypatch
) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "Narrate this"
            audio_path = self.save_dir / "clip-0001.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"mp3")
            return audio_path

        def synthesize(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(self.save_audio(text), 3.5)

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )
    waited: list[CueDisplay] = []

    monkeypatch.setattr(recorder.subtitles, "open_cue", lambda text: 1.25)
    monkeypatch.setattr(recorder.subtitles, "wait_for_display", waited.append)

    recorder.explain("Narrate this")

    assert waited == [CueDisplay(4.75)]
    assert recorder._narration_clips == [
        NarrationClip(
            text="Narrate this",
            path=tmp_path / "tts" / "clip-0001.mp3",
            start_seconds=1.25,
            duration_seconds=3.5,
        )
    ]


def test_synthesize_explanation_audio_returns_text_and_audio(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "Prepared line"
            audio_path = self.save_dir / "clip-0001.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"mp3")
            return audio_path

        def synthesize(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(self.save_audio(text), 1.75)

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )

    prepared = recorder.synthesize_explanation_audio("  Prepared line  ")

    assert prepared == SynthesizedExplanation(
        text="Prepared line",
        audio=SynthesizedAudio(tmp_path / "tts" / "clip-0001.mp3", 1.75),
    )


def test_synthesize_if_tts_enabled_returns_text_without_backend(tmp_path) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4")

    assert recorder.synthesize_if_tts_enabled("  Plain line  ") == "Plain line"


def test_synthesize_if_tts_enabled_prepares_audio_with_backend(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "Prepared line"
            audio_path = self.save_dir / "clip-0001.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"mp3")
            return audio_path

        def synthesize(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(self.save_audio(text), 2.25)

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )

    assert recorder.synthesize_if_tts_enabled("  Prepared line  ") == (
        SynthesizedExplanation(
            text="Prepared line",
            audio=SynthesizedAudio(tmp_path / "tts" / "clip-0001.mp3", 2.25),
        )
    )


def test_demo_recorder_explain_accepts_pre_synthesized_audio(
    tmp_path, monkeypatch
) -> None:
    prepared = SynthesizedExplanation(
        text="Prepared line",
        audio=SynthesizedAudio(tmp_path / "prepared.mp3", 1.75),
    )
    prepared.audio.path.write_bytes(b"prepared")
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4")
    waited: list[CueDisplay] = []

    opened: list[str] = []

    def fake_open_cue(text: str) -> float:
        opened.append(text)
        return 2.0

    monkeypatch.setattr(recorder.subtitles, "open_cue", fake_open_cue)
    monkeypatch.setattr(recorder.subtitles, "wait_for_display", waited.append)

    recorder.explain(prepared)

    assert opened == ["Prepared line"]
    assert waited == [CueDisplay(3.75)]
    assert recorder._narration_clips == [
        NarrationClip(
            text="Prepared line",
            path=prepared.audio.path,
            start_seconds=2.0,
            duration_seconds=1.75,
        )
    ]


def test_stop_recording_renders_and_cleans_up_tts_audio(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        def __init__(self) -> None:
            super().__init__(save_dir=tmp_path / "tts")
            self.cleaned = False

        def save_audio(self, text: str) -> Path:
            raise AssertionError(f"unexpected save_audio call: {text}")

        def cleanup(self) -> None:
            self.cleaned = True

    tts = FakeTTS()
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4", tts=tts)
    recorder._narration_clips = [
        NarrationClip(
            text="hello",
            path=tmp_path / "tts" / "clip-0001.mp3",
            start_seconds=0.0,
            duration_seconds=1.0,
        )
    ]
    recorder.narration_audio_path.write_bytes(b"mix")

    called: dict[str, object] = {}
    recorder.capture.render_narration_audio = lambda clips, output_path: Path(output_path)  # type: ignore[method-assign]
    recorder.capture.burn_subtitles = (
        lambda subtitle_path, output_path, *, audio_path=None: called.update(
            {
                "subtitle_path": subtitle_path,
                "output_path": output_path,
                "audio_path": audio_path,
            }
        )
        or Path(output_path)
    )  # type: ignore[method-assign]

    final_path = recorder.stop_recording()

    assert final_path == tmp_path / "demo.mp4"
    assert called["audio_path"] == recorder.narration_audio_path
    assert tts.cleaned is True
    assert recorder.narration_audio_path.exists() is False


def test_stop_recording_trims_macos_capture_lead_in_to_match_timeline(
    tmp_path, monkeypatch
) -> None:
    class FakeTTS(TTSBackend):
        def __init__(self) -> None:
            super().__init__(save_dir=tmp_path / "tts")
            self.cleaned = False

        def save_audio(self, text: str) -> Path:
            raise AssertionError(f"unexpected save_audio call: {text}")

        def cleanup(self) -> None:
            self.cleaned = True

    tts = FakeTTS()
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4", tts=tts)
    recorder.subtitle_path.write_text(
        "1\n" "00:00:01,000 --> 00:00:02,000\n" "Hello there\n",
        encoding="utf-8",
    )
    clip_path = tmp_path / "tts" / "clip-0001.mp3"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"clip")
    recorder._narration_clips = [
        NarrationClip(
            text="Hello there",
            path=clip_path,
            start_seconds=1.0,
            duration_seconds=1.0,
        )
    ]
    recorder.raw_video_path.write_bytes(b"raw")

    render_calls: dict[str, object] = {}
    burned: dict[str, object] = {}
    trimmed: list[float] = []
    probe_calls = 0

    monkeypatch.setattr("demo_video_recorder.core.platform.system", lambda: "Darwin")
    monkeypatch.setattr(recorder.subtitles, "complete_cue", lambda: None)
    monkeypatch.setattr(recorder.subtitles, "elapsed_seconds", lambda: 5.0)
    recorder.capture.probe_duration_seconds = lambda media_path=None: 5.8 if not trimmed else 5.0  # type: ignore[method-assign]
    recorder.capture.trim_leading_seconds = lambda offset_seconds: trimmed.append(offset_seconds) or recorder.raw_video_path  # type: ignore[method-assign]
    recorder.capture.render_narration_audio = lambda clips, output_path: render_calls.update(  # type: ignore[method-assign]
        {
            "clips": clips,
            "output_path": Path(output_path),
        }
    ) or Path(
        output_path
    )
    recorder.capture.burn_subtitles = lambda subtitle_path, output_path, *, audio_path=None: burned.update(
        {
            "subtitle_path": Path(subtitle_path),
            "output_path": Path(output_path),
            "audio_path": Path(audio_path) if audio_path is not None else None,
        }
    ) or Path(
        output_path
    )  # type: ignore[method-assign]

    final_path = recorder.stop_recording()

    assert final_path == tmp_path / "demo.mp4"
    assert trimmed == [pytest.approx(0.8)]
    assert recorder.subtitle_path.read_text(encoding="utf-8") == (
        "1\n" "00:00:01,000 --> 00:00:02,000\n" "Hello there\n"
    )
    clips = render_calls["clips"]
    assert isinstance(clips, list)
    assert clips[0].text == "Hello there"
    assert clips[0].path == clip_path
    assert clips[0].start_seconds == 1.0
    assert clips[0].duration_seconds == 1.0
    assert burned["audio_path"] == recorder.narration_audio_path
    assert tts.cleaned is True
