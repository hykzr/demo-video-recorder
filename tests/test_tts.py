from __future__ import annotations

from pathlib import Path
import subprocess
import types

from demo_video_recorder import DemoVideoRecorder, EdgeTTSBackend, TTSBackend
from demo_video_recorder.subtitles import CueDisplay
from demo_video_recorder.tts import NarrationClip, SynthesizedAudio


def test_tts_backend_synthesize_uses_save_audio_and_probes_duration(
    tmp_path, monkeypatch
) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "hello there"
            path = self.save_dir / "clip-0001.mp3"
            path.write_bytes(b"mp3")
            return path

    monkeypatch.setattr("demo_video_recorder.tts.shutil.which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        "demo_video_recorder.tts.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.25\n", ""),
    )

    backend = FakeTTS(save_dir=tmp_path / "tts")
    result = backend.synthesize("hello there")

    assert result.duration_seconds == 1.25
    assert result.path == tmp_path / "tts" / "clip-0001.mp3"
    assert result.path.read_bytes() == b"mp3"


def test_edge_tts_backend_save_audio_and_list_speakers(tmp_path, monkeypatch) -> None:
    saved_audio: dict[str, Path] = {}

    class FakeCommunicate:
        def __init__(self, text: str, speaker: str, *, rate: str, volume: str) -> None:
            assert text == "hello there"
            assert speaker == "en-US-AvaNeural"
            assert rate == "+12%"
            assert volume == "-5%"

        def save_sync(self, path: str) -> None:
            saved_audio["path"] = Path(path)
            Path(path).write_bytes(b"mp3")

    async def fake_list_voices() -> list[dict[str, str]]:
        return [
            {"ShortName": "en-US-AvaNeural"},
            {"ShortName": "en-US-JennyNeural"},
        ]

    monkeypatch.setattr("demo_video_recorder.tts.shutil.which", lambda _: "/usr/bin/ffprobe")

    def fake_import_module(name: str):
        assert name == "edge_tts"
        return types.SimpleNamespace(
            Communicate=FakeCommunicate,
            list_voices=fake_list_voices,
        )

    monkeypatch.setattr("demo_video_recorder.tts.import_module", fake_import_module)
    monkeypatch.setattr(
        "demo_video_recorder.tts.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1.25\n", ""),
    )

    backend = EdgeTTSBackend(
        save_dir=tmp_path / "tts",
        speaker="en-US-AvaNeural",
        speed="+12%",
        volume="-5%",
    )

    result = backend.synthesize("hello there")

    assert result.duration_seconds == 1.25
    assert result.path == saved_audio["path"]
    assert backend.list_speaker() == ["en-US-AvaNeural", "en-US-JennyNeural"]


def test_demo_recorder_explain_uses_tts_duration_for_wait(tmp_path, monkeypatch) -> None:
    class FakeTTS(TTSBackend):
        def save_audio(self, text: str) -> Path:
            assert text == "Narrate this"
            audio_path = self.save_dir / "clip-0001.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"mp3")
            return audio_path

        def synthesize(self, text: str) -> SynthesizedAudio:
            return SynthesizedAudio(self.save_audio(text), 3.5)

    recorder = DemoVideoRecorder(tmp_path / "demo.mp4", tts=FakeTTS(save_dir=tmp_path / "tts"))
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


def test_demo_recorder_explain_accepts_pre_synthesized_audio(
    tmp_path, monkeypatch
) -> None:
    recorder = DemoVideoRecorder(tmp_path / "demo.mp4")
    audio_path = tmp_path / "prepared.mp3"
    audio_path.write_bytes(b"prepared")
    waited: list[CueDisplay] = []

    monkeypatch.setattr(recorder.subtitles, "open_cue", lambda text: 2.0)
    monkeypatch.setattr(recorder.subtitles, "wait_for_display", waited.append)
    monkeypatch.setattr(
        recorder.capture,
        "probe_duration_seconds",
        lambda media_path=None: 1.75,
    )

    recorder.explain("Prepared line", audio=audio_path)

    assert waited == [CueDisplay(3.75)]
    assert recorder._narration_clips == [
        NarrationClip(
            text="Prepared line",
            path=audio_path,
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
