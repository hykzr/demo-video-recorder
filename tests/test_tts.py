from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from demo_video_recorder import (
    DemoVideoRecorder,
    EdgeTTSBackend,
    MacOSTTSBackend,
    NativeTTSBackend,
    SubtitleStyle,
    TTSBackend,
    WindowsTTSBackend,
)
from demo_video_recorder.errors import DependencyMissingError, RecordingError
from demo_video_recorder.subtitles import CueDisplay
from demo_video_recorder.tts import (
    NarrationClip,
    SynthesizedAudio,
    SynthesizedExplanation,
)


def test_recorder_passes_subtitle_style_to_capture(tmp_path) -> None:
    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4",
        subtitle_style=SubtitleStyle(font_size=12, alignment="bottom_center"),
    )
    called: dict[str, object] = {}

    recorder.capture.burn_subtitles = lambda subtitle_path, output_path, **kwargs: called.update(  # type: ignore[method-assign]
        {
            "subtitle_path": Path(subtitle_path),
            "output_path": Path(output_path),
            **kwargs,
        }
    ) or Path(
        output_path
    )

    recorder.burn_subtitles()

    assert called["subtitle_path"] == recorder.subtitle_path
    assert called["output_path"] == recorder.output_path
    assert called["subtitle_style"] == "Fontsize=12,Alignment=2"


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


def test_synthesize_if_tts_enabled_async_prepares_audio(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "Prepared line"
            audio_path = self.save_dir / "clip-0001.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"mp3")
            return audio_path

        async def synthesize_async(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(self.save_audio(text), 2.25)

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )

    result = asyncio.run(recorder.synthesize_if_tts_enabled_async("  Prepared line  "))

    assert result == (
        SynthesizedExplanation(
            text="Prepared line",
            audio=SynthesizedAudio(tmp_path / "tts" / "clip-0001.mp3", 2.25),
        )
    )


def test_prepare_cues_uses_recorder_sync_preparation(tmp_path) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4")

    assert recorder.prepare_cues(
        {"intro": "  First cue  ", "finish": "Second cue"}
    ) == {
        "intro": "First cue",
        "finish": "Second cue",
    }


def test_prepare_cues_async_uses_recorder_async_preparation(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        async def synthesize_async(self, text: str) -> SynthesizedAudio:
            path = self.save_dir / f"{text}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")
            return SynthesizedAudio(path, 1.0)

        def save_audio(self, text: str) -> Path:
            raise AssertionError(f"unexpected sync synthesis: {text}")

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )

    result = asyncio.run(
        recorder.prepare_cues_async({"intro": "First cue", "finish": "Second cue"})
    )

    assert result == {
        "intro": SynthesizedExplanation(
            "First cue",
            SynthesizedAudio(tmp_path / "tts" / "First cue.mp3", 1.0),
        ),
        "finish": SynthesizedExplanation(
            "Second cue",
            SynthesizedAudio(tmp_path / "tts" / "Second cue.mp3", 1.0),
        ),
    }


def test_prepare_cues_can_run_async_preparation_from_sync_code(tmp_path) -> None:
    class FakeTTS(TTSBackend):
        async def synthesize_async(self, text: str) -> SynthesizedAudio:
            path = self.save_dir / f"{text}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp3")
            return SynthesizedAudio(path, 1.0)

        def save_audio(self, text: str) -> Path:
            raise AssertionError(f"unexpected sync synthesis: {text}")

    recorder = DemoVideoRecorder(
        tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts")
    )

    result = recorder.prepare_cues({"intro": "First cue"}, async_tts=True)

    assert result == {
        "intro": SynthesizedExplanation(
            "First cue",
            SynthesizedAudio(tmp_path / "tts" / "First cue.mp3", 1.0),
        )
    }


def test_prepare_cues_rejects_positional_lists(tmp_path) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4")

    with pytest.raises(TypeError, match="mapping of cue names"):
        recorder.prepare_cues(["First cue"])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="mapping of cue names"):
        asyncio.run(recorder.prepare_cues_async(["First cue"]))  # type: ignore[arg-type]


def test_explain_during_runs_action_and_waits_out_cue(tmp_path, monkeypatch) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4", min_pause_seconds=2.0)
    waits: list[float] = []
    actions: list[str] = []
    elapsed = {"value": 10.0}

    monkeypatch.setattr(recorder.subtitles, "elapsed_seconds", lambda: elapsed["value"])
    monkeypatch.setattr(
        recorder, "wait", lambda seconds: waits.append(seconds) or recorder
    )

    def action() -> None:
        actions.append("ran")
        elapsed["value"] = 10.75

    recorder.explain_during("Short cue", action, tail_seconds=0.25)

    assert actions == ["ran"]
    assert waits == [1.5]


def test_explain_during_accepts_multiple_cues(tmp_path, monkeypatch) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4", min_pause_seconds=1.0)
    explained: list[tuple[str, bool]] = []
    completed = 0

    def fake_explain(text, *, wait=True):
        explained.append((str(text), wait))
        return recorder

    monkeypatch.setattr(recorder, "explain", fake_explain)
    monkeypatch.setattr(recorder, "wait", lambda seconds: recorder)

    def fake_complete() -> DemoVideoRecorder:
        nonlocal completed
        completed += 1
        return recorder

    monkeypatch.setattr(recorder, "complete_explanation", fake_complete)

    recorder.explain_during(["First cue", "Second cue"], lambda: None)

    assert explained == [("First cue", False), ("Second cue", True)]
    assert completed == 2


def test_edge_tts_cache_reuses_existing_clip(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeCommunicate:
        def __init__(self, text: str, speaker: str, *, rate: str, volume: str) -> None:
            calls.append(text)

        def save_sync(self, output_path: str) -> None:
            Path(output_path).write_bytes(b"mp3")

    monkeypatch.setattr(
        "demo_video_recorder.tts.shutil.which", lambda _: "/bin/ffprobe"
    )
    monkeypatch.setattr("demo_video_recorder.tts.edge_tts.Communicate", FakeCommunicate)
    monkeypatch.setattr(
        "demo_video_recorder.tts.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.0\n", ""),
    )

    tts = EdgeTTSBackend(save_dir=tmp_path / "tts", cache=True)

    first = tts.synthesize("Reuse this line")
    second = tts.synthesize("Reuse this line")
    tts.cleanup()

    assert calls == ["Reuse this line"]
    assert first == second
    assert first.path.exists()


def test_edge_tts_failure_reports_backend_context(tmp_path, monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, speaker: str, *, rate: str, volume: str) -> None:
            pass

        def save_sync(self, output_path: str) -> None:
            raise RuntimeError("NoAudioReceived")

    monkeypatch.setattr(
        "demo_video_recorder.tts.shutil.which", lambda _: "/bin/ffprobe"
    )
    monkeypatch.setattr("demo_video_recorder.tts.edge_tts.Communicate", FakeCommunicate)
    tts = EdgeTTSBackend(
        save_dir=tmp_path / "tts",
        speaker="en-US-AvaMultilingualNeural",
        speed="+0%",
        volume="+0%",
    )

    with pytest.raises(RecordingError) as exc_info:
        tts.synthesize("This should fail")

    message = str(exc_info.value)
    assert "Edge TTS synthesis failed" in message
    assert "error_type=RuntimeError" in message
    assert "NoAudioReceived" in message
    assert "speaker='en-US-AvaMultilingualNeural'" in message


def test_macos_tts_backend_uses_say_command(tmp_path, monkeypatch) -> None:
    run_calls: list[list[str]] = []

    monkeypatch.setattr(
        "demo_video_recorder.tts.shutil.which", lambda _: "/usr/bin/say"
    )

    def fake_run(command, **kwargs):
        run_calls.append(command)
        Path(command[command.index("-o") + 1]).write_bytes(b"aiff")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("demo_video_recorder.tts.subprocess.run", fake_run)

    backend = MacOSTTSBackend(
        save_dir=tmp_path / "tts",
        speaker="Samantha",
        words_per_minute=170,
    )

    path = backend.save_audio("Hello from macOS")

    assert path.suffix == ".aiff"
    assert path.read_bytes() == b"aiff"
    assert run_calls[0] == [
        "say",
        "-v",
        "Samantha",
        "-r",
        "170",
        "-o",
        str(path),
        "--",
        "Hello from macOS",
    ]


def test_windows_tts_backend_uses_powershell_sapi(tmp_path, monkeypatch) -> None:
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        "demo_video_recorder.tts.shutil.which",
        lambda _: r"C:\Windows\System32\powershell.exe",
    )

    def fake_run(command, **kwargs):
        recorded["command"] = command
        recorded["env"] = kwargs["env"]
        output_path = Path(kwargs["env"]["DEMO_TTS_OUTPUT"])
        output_path.write_bytes(b"wav")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("demo_video_recorder.tts.subprocess.run", fake_run)

    backend = WindowsTTSBackend(
        save_dir=tmp_path / "tts",
        speaker="Microsoft Zira Desktop",
        rate=1,
        volume=90,
    )

    path = backend.save_audio("Hello from Windows")

    assert path.suffix == ".wav"
    assert path.read_bytes() == b"wav"
    assert recorded["command"][:5] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
    ]
    env = recorded["env"]
    assert env["DEMO_TTS_TEXT"] == "Hello from Windows"
    assert env["DEMO_TTS_VOICE"] == "Microsoft Zira Desktop"
    assert env["DEMO_TTS_RATE"] == "1"
    assert env["DEMO_TTS_VOLUME"] == "90"


def test_native_tts_backend_selects_platform_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("demo_video_recorder.tts.platform.system", lambda: "Darwin")
    assert isinstance(NativeTTSBackend(save_dir=tmp_path / "mac"), MacOSTTSBackend)

    monkeypatch.setattr("demo_video_recorder.tts.platform.system", lambda: "Windows")
    assert isinstance(NativeTTSBackend(save_dir=tmp_path / "win"), WindowsTTSBackend)

    monkeypatch.setattr("demo_video_recorder.tts.platform.system", lambda: "Linux")
    with pytest.raises(DependencyMissingError):
        NativeTTSBackend(save_dir=tmp_path / "linux")


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


def test_stop_recording_burn_false_muxes_audio_without_burning_subtitles(
    tmp_path,
    monkeypatch,
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
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        encoding="utf-8",
    )
    recorder.raw_video_path.write_bytes(b"raw")
    recorder._narration_clips = [
        NarrationClip(
            text="hello",
            path=tmp_path / "tts" / "clip-0001.mp3",
            start_seconds=0.0,
            duration_seconds=1.0,
        )
    ]
    called: dict[str, object] = {}

    def fake_render_narration_audio(clips, output_path):
        del clips
        Path(output_path).write_bytes(b"mix")
        return Path(output_path)

    monkeypatch.setattr(recorder.subtitles, "elapsed_seconds", lambda: 1.0)
    recorder.capture.probe_duration_seconds = lambda media_path=None: 1.0  # type: ignore[method-assign]
    recorder.capture.render_narration_audio = fake_render_narration_audio  # type: ignore[method-assign]
    recorder.capture.mux_audio = lambda audio_path, output_path: called.update(  # type: ignore[method-assign]
        {"audio_path": Path(audio_path), "output_path": Path(output_path)}
    ) or Path(
        output_path
    )
    recorder.capture.burn_subtitles = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("unexpected subtitle burn")
    )

    final_path = recorder.stop_recording(burn=False)

    assert final_path == tmp_path / "demo.mp4"
    assert called == {
        "audio_path": recorder.narration_audio_path,
        "output_path": tmp_path / "demo.mp4",
    }
    assert recorder.raw_video_path.exists() is False
    assert recorder.narration_audio_path.exists() is False
    assert tts.cleaned is True


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
