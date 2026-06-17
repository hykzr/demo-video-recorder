from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from demo_video_recorder.backends import FfmpegCaptureBackend
from demo_video_recorder.backends import PlaywrightVideoCaptureBackend
from demo_video_recorder.errors import DependencyMissingError
from demo_video_recorder.subtitles import SubtitleStyle
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

    def fake_burn(
        *,
        subtitle_path,
        output_path,
        ffmpeg_binary,
        audio_path=None,
        subtitle_style=None,
    ) -> None:
        called["subtitle_path"] = subtitle_path
        called["output_path"] = output_path
        called["ffmpeg_binary"] = ffmpeg_binary
        called["audio_path"] = audio_path
        called["subtitle_style"] = subtitle_style
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
    assert called["subtitle_style"] is None
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

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
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


def test_trim_leading_seconds_reencodes_and_replaces_raw_video(
    tmp_path, monkeypatch
) -> None:
    raw_video = tmp_path / "demo.raw.mp4"
    raw_video.write_bytes(b"raw")
    backend = FfmpegCaptureBackend(raw_video, ffmpeg="ffmpeg-test")
    captured: dict[str, object] = {}

    monkeypatch.setattr(backend, "ensure_available", lambda: None)

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        trimmed_output = Path(command[-1])
        trimmed_output.write_bytes(b"trimmed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("demo_video_recorder.backends.subprocess.run", fake_run)

    output_path = backend.trim_leading_seconds(0.8)

    assert output_path == raw_video
    assert raw_video.read_bytes() == b"trimmed"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:5] == ["ffmpeg-test", "-y", "-hide_banner", "-loglevel", "error"]
    assert command[command.index("-ss") + 1] == "0.800000"
    assert command[command.index("-map") + 1] == "0:v:0"
    assert str(raw_video.resolve()) in command


def test_subtitles_filter_value_quotes_filename(tmp_path) -> None:
    backend = FfmpegCaptureBackend(tmp_path / "demo.raw.mp4")
    subtitle_path = tmp_path / "name:with'quotes.srt"

    value = backend._subtitles_filter_value(subtitle_path)

    assert value.startswith("subtitles=filename='")
    assert "\\:" in value
    assert "\\'" in value


def test_subtitles_filter_value_includes_style(tmp_path) -> None:
    backend = FfmpegCaptureBackend(
        tmp_path / "demo.raw.mp4",
        subtitle_style=SubtitleStyle(
            font_name="Arial",
            font_size=12,
            primary_color="#ffffff",
            outline_color="#000000",
            outline=0.7,
            shadow=0,
            alignment="bottom_center",
            margin_vertical=20,
        ),
    )
    subtitle_path = tmp_path / "demo.srt"

    value = backend._subtitles_filter_value(subtitle_path)

    assert value.startswith("subtitles=filename='")
    assert (
        ":force_style='Fontname=Arial,"
        "Fontsize=12,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "Outline=0.7,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=20'"
    ) in value


def test_playwright_video_backend_saves_page_video(tmp_path) -> None:
    backend = PlaywrightVideoCaptureBackend(tmp_path / "demo.raw.mp4")
    events: list[str] = []

    class FakeContext:
        def close(self) -> None:
            events.append("context.close")

    class FakeVideo:
        def save_as(self, path: Path) -> None:
            events.append(f"save_as:{path.name}")
            path.write_bytes(b"video")

        def delete(self) -> None:
            events.append("video.delete")

    class FakePage:
        video = FakeVideo()
        context = FakeContext()

    backend.attach_page(FakePage())  # type: ignore[arg-type]
    backend.start()
    backend.stop()

    assert events == ["context.close", "save_as:demo.raw.mp4", "video.delete"]
    assert backend.raw_video_path.read_bytes() == b"video"
    assert backend.is_recording is False


def test_playwright_video_backend_builds_context_video_options(tmp_path) -> None:
    backend = PlaywrightVideoCaptureBackend(tmp_path / "demo.raw.mp4")

    options = backend.context_video_options(width=1024, height=768)

    assert options["record_video_dir"] == backend.video_dir
    assert options["record_video_size"] == {"width": 1024, "height": 768}
    assert backend.video_dir.exists()
