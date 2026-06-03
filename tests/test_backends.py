from __future__ import annotations

import subprocess

import pytest

from demo_video_recorder.backends import FfmpegCaptureBackend
from demo_video_recorder.errors import DependencyMissingError
from demo_video_recorder.tts import NarrationClip
from demo_video_recorder.types import CaptureRegion


def test_build_windows_capture_command_uses_gdigrab(tmp_path) -> None:
    backend = FfmpegCaptureBackend(tmp_path / "demo.raw.mp4", scale_width=1280)

    command = backend._build_start_command(
        system="Windows",
        region=CaptureRegion(10, 20, 800, 600),
    )

    assert "gdigrab" in command
    assert "desktop" in command
    assert command[command.index("-offset_x") + 1] == "10"
    assert command[command.index("-offset_y") + 1] == "20"
    assert command[command.index("-video_size") + 1] == "800x600"
    assert command[command.index("-vf") + 1] == "scale=1280:-2,format=yuv420p"


def test_build_macos_capture_command_uses_avfoundation(tmp_path, monkeypatch) -> None:
    backend = FfmpegCaptureBackend(
        tmp_path / "demo.raw.mp4",
        scale_width=1440,
        draw_mouse=True,
    )
    monkeypatch.setattr(backend, "_resolve_macos_screen_device", lambda: "2")

    command = backend._build_start_command(
        system="Darwin",
        region=CaptureRegion(30, 40, 1280, 720),
    )

    assert "avfoundation" in command
    assert command[command.index("-capture_cursor") + 1] == "1"
    assert command[command.index("-capture_mouse_clicks") + 1] == "1"
    assert command[command.index("-i") + 1] == "2:none"
    assert (
        command[command.index("-vf") + 1]
        == "crop=1280:720:30:40,scale=1440:-2,format=yuv420p"
    )


def test_resolve_macos_screen_device_parses_ffmpeg_listing(
    tmp_path, monkeypatch
) -> None:
    backend = FfmpegCaptureBackend(tmp_path / "demo.raw.mp4")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            ["ffmpeg"],
            251,
            "",
            "[AVFoundation indev @ 0x1] [0] FaceTime HD Camera\n"
            "[AVFoundation indev @ 0x1] [2] Capture screen 0\n",
        )

    monkeypatch.setattr("demo_video_recorder.backends.subprocess.run", fake_run)

    assert backend._resolve_macos_screen_device() == "2"


def test_burn_subtitles_uses_homebrew_ffmpeg_full_when_available(
    tmp_path, monkeypatch
) -> None:
    raw_video = tmp_path / "demo.raw.mp4"
    subtitle_path = tmp_path / "demo.srt"
    output_path = tmp_path / "demo.mp4"
    raw_video.write_bytes(b"raw")
    subtitle_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        encoding="utf-8",
    )
    backend = FfmpegCaptureBackend(raw_video)
    called: dict[str, object] = {}

    monkeypatch.setattr(backend, "ensure_available", lambda: None)
    monkeypatch.setattr(
        "demo_video_recorder.backends.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        backend,
        "_macos_subtitle_burn_ffmpeg_candidates",
        lambda: ["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"],
    )

    def fake_has_filter(name: str, *, ffmpeg_binary: str | None = None) -> bool:
        assert name == "subtitles"
        return ffmpeg_binary == "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"

    monkeypatch.setattr(backend, "_ffmpeg_has_filter", fake_has_filter)

    def fake_burn(*, subtitle_path, output_path, ffmpeg_binary, audio_path=None) -> None:
        called["subtitle_path"] = subtitle_path
        called["output_path"] = output_path
        called["ffmpeg_binary"] = ffmpeg_binary
        called["audio_path"] = audio_path
        output_path.write_bytes(b"final")

    monkeypatch.setattr(
        backend,
        "_burn_subtitles_with_ffmpeg_filter",
        fake_burn,
    )

    result = backend.burn_subtitles(subtitle_path, output_path)

    assert result == output_path
    assert called["output_path"] == output_path
    assert called["ffmpeg_binary"] == "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
    assert output_path.read_bytes() == b"final"


def test_burn_subtitles_raises_dependency_error_when_filter_is_missing(
    tmp_path, monkeypatch
) -> None:
    raw_video = tmp_path / "demo.raw.mp4"
    subtitle_path = tmp_path / "demo.srt"
    output_path = tmp_path / "demo.mp4"
    raw_video.write_bytes(b"raw")
    subtitle_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        encoding="utf-8",
    )
    backend = FfmpegCaptureBackend(raw_video)

    monkeypatch.setattr(backend, "ensure_available", lambda: None)
    monkeypatch.setattr(
        "demo_video_recorder.backends.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(backend, "_ffmpeg_has_filter", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        backend,
        "_macos_subtitle_burn_ffmpeg_candidates",
        lambda: [],
    )

    with pytest.raises(DependencyMissingError, match="libass"):
        backend.burn_subtitles(subtitle_path, output_path)


def test_burn_subtitles_without_srt_muxes_audio_when_present(
    tmp_path, monkeypatch
) -> None:
    raw_video = tmp_path / "demo.raw.mp4"
    subtitle_path = tmp_path / "demo.srt"
    audio_path = tmp_path / "demo.m4a"
    output_path = tmp_path / "demo.mp4"
    raw_video.write_bytes(b"raw")
    subtitle_path.write_text("", encoding="utf-8")
    audio_path.write_bytes(b"audio")
    backend = FfmpegCaptureBackend(raw_video)
    called: dict[str, object] = {}

    monkeypatch.setattr(backend, "ensure_available", lambda: None)
    monkeypatch.setattr(
        backend,
        "_mux_audio",
        lambda *, audio_path, output_path: called.update(
            {"audio_path": audio_path, "output_path": output_path}
        ),
    )

    result = backend.burn_subtitles(subtitle_path, output_path, audio_path=audio_path)

    assert result == output_path
    assert called["audio_path"] == audio_path
    assert called["output_path"] == output_path


def test_render_narration_audio_builds_delayed_mix_command(
    tmp_path, monkeypatch
) -> None:
    backend = FfmpegCaptureBackend(tmp_path / "demo.raw.mp4", ffmpeg="ffmpeg-test")
    first = tmp_path / "clip-1.mp3"
    second = tmp_path / "clip-2.mp3"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    clips = [
        NarrationClip("first", first, 0.0, 1.0),
        NarrationClip("second", second, 1.25, 2.0),
    ]
    captured: dict[str, object] = {}

    monkeypatch.setattr(backend, "ensure_available", lambda: None)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("demo_video_recorder.backends.subprocess.run", fake_run)

    output_path = backend.render_narration_audio(clips, tmp_path / "narration.m4a")

    assert output_path == tmp_path / "narration.m4a"
    command = captured["command"]
    assert isinstance(command, list)
    assert "ffmpeg-test" == command[0]
    assert str(first.resolve()) in command
    assert str(second.resolve()) in command
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "[0:a]adelay=0:all=1[a0]" in filter_graph
    assert "[1:a]adelay=1250:all=1[a1]" in filter_graph
    assert "amix=inputs=2:normalize=0[aout]" in filter_graph


def test_subtitles_filter_value_quotes_filename(tmp_path) -> None:
    backend = FfmpegCaptureBackend(tmp_path / "demo.raw.mp4")
    subtitle_path = tmp_path / "name:with'quotes.srt"

    value = backend._subtitles_filter_value(subtitle_path)

    assert value.startswith("subtitles=filename='")
    assert "\\:" in value
    assert "\\'" in value
