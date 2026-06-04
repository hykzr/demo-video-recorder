"""Capture and encoding backends."""

from __future__ import annotations

from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import textwrap
import time

from demo_video_recorder.defaults import DEFAULTS
from demo_video_recorder.errors import DependencyMissingError, RecordingError
from demo_video_recorder.subtitles import parse_srt_time
from demo_video_recorder.tts import NarrationClip
from demo_video_recorder.types import CaptureRegion


class FfmpegCaptureBackend:
    """Record a screen region and burn subtitles using ffmpeg."""

    def __init__(
        self,
        raw_video_path: str | Path,
        *,
        framerate: int = DEFAULTS.capture_framerate,
        scale_width: int | None = DEFAULTS.video_scale_width,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        draw_mouse: bool = False,
        crf: int = 24,
        preset: str = "veryfast",
    ) -> None:
        self.raw_video_path = Path(raw_video_path)
        self.framerate = framerate
        self.scale_width = scale_width
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.draw_mouse = draw_mouse
        self.crf = crf
        self.preset = preset
        self.process: subprocess.Popen[str] | None = None

    @property
    def is_recording(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def ensure_available(self) -> None:
        missing = [
            name for name in (self.ffmpeg, self.ffprobe) if shutil.which(name) is None
        ]
        if missing:
            joined = ", ".join(missing)
            raise DependencyMissingError(f"Missing external dependency: {joined}")

    def start(self, *, region: CaptureRegion | None = None) -> None:
        if self.is_recording:
            raise RecordingError("Capture is already running.")

        self.ensure_available()
        self.raw_video_path.parent.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        command = self._build_start_command(system=system, region=region)

        # print(f"Starting ffmpeg capture with command: {' '.join(command)}")

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.raw_video_path.parent),
        )

    def wait_until_ready(self, *, timeout_seconds: float = 15.0) -> None:
        if self.process is None:
            raise RecordingError("Capture has not been started.")

        deadline = time.monotonic() + timeout_seconds
        started_at = time.monotonic()
        last_size = -1
        saw_growth = False

        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break

            if self.raw_video_path.exists():
                size = self.raw_video_path.stat().st_size
                if size > 65_536:
                    return
                if last_size >= 0 and size > last_size:
                    saw_growth = True
                if size > 0 and (saw_growth or time.monotonic() - started_at >= 0.75):
                    return
                last_size = size

            time.sleep(0.1)

        stdout, stderr = self._process_output_if_exited()
        detail = self._format_start_failure_detail(stderr=stderr, stdout=stdout)
        raise RecordingError(
            f"ffmpeg did not start writing the recording in time.\n{detail}"
        )

    def stop(self, *, timeout_seconds: float = 20.0) -> None:
        if self.process is None:
            return

        process = self.process
        self.process = None

        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                except OSError:
                    process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                raise RecordingError("ffmpeg capture did not stop cleanly.") from exc

        stdout, stderr = process.communicate(timeout=5)
        if process.returncode != 0:
            detail = (stderr + "\n" + stdout).strip()
            raise RecordingError(f"ffmpeg capture failed.\n{detail}")

    def probe_duration_seconds(self, media_path: str | Path | None = None) -> float:
        self.ensure_available()
        target_path = (
            Path(media_path) if media_path is not None else self.raw_video_path
        )
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(target_path),
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
            raise RecordingError(f"ffprobe failed.\n{result.stderr.strip()}")

        try:
            duration = float(result.stdout.strip().splitlines()[0])
        except (IndexError, ValueError) as exc:
            raise RecordingError(
                f"Could not parse ffprobe duration: {result.stdout!r}"
            ) from exc
        if duration < 0:
            raise RecordingError(f"Invalid ffprobe duration: {duration}")
        return duration

    def burn_subtitles(
        self,
        subtitle_path: str | Path,
        output_path: str | Path,
        *,
        audio_path: str | Path | None = None,
    ) -> Path:
        self.ensure_available()
        subtitle_path = Path(subtitle_path)
        output_path = Path(output_path)
        audio_path = Path(audio_path) if audio_path is not None else None
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if (
            not subtitle_path.exists()
            or not subtitle_path.read_text(encoding="utf-8").strip()
        ):
            if audio_path is None:
                shutil.copy2(self.raw_video_path, output_path)
            else:
                self._mux_audio(audio_path=audio_path, output_path=output_path)
            return output_path

        temp_subtitle = (
            self.raw_video_path.parent / "__demo_video_recorder_subtitles.srt"
        )
        shutil.copy2(subtitle_path, temp_subtitle)

        try:
            subtitle_ffmpeg = self._resolve_subtitle_burn_ffmpeg()
            self._burn_subtitles_with_ffmpeg_filter(
                subtitle_path=temp_subtitle,
                output_path=output_path,
                ffmpeg_binary=subtitle_ffmpeg,
                audio_path=audio_path,
            )
        finally:
            temp_subtitle.unlink(missing_ok=True)

        return output_path

    def render_narration_audio(
        self,
        clips: list[NarrationClip],
        output_path: str | Path,
    ) -> Path:
        """Mix all narration clips into a single timeline-aligned audio file."""

        self.ensure_available()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not clips:
            raise RecordingError("No narration clips were generated.")

        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        for clip in clips:
            command.extend(["-i", str(clip.path.resolve())])

        filter_parts: list[str] = []
        input_labels: list[str] = []
        for index, clip in enumerate(clips):
            label = f"a{index}"
            delay_ms = max(0, round(clip.start_seconds * 1000))
            filter_parts.append(f"[{index}:a]adelay={delay_ms}:all=1[{label}]")
            input_labels.append(f"[{label}]")

        if len(input_labels) == 1:
            filter_parts.append(f"{input_labels[0]}acopy[aout]")
        else:
            filter_parts.append(
                f"{''.join(input_labels)}amix=inputs={len(input_labels)}:normalize=0[aout]"
            )

        command.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[aout]",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_path.resolve()),
            ]
        )

        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr + "\n" + result.stdout).strip()
            raise RecordingError(f"ffmpeg narration mix failed.\n{detail}")
        return output_path

    def _resolve_subtitle_burn_ffmpeg(self) -> str:
        if self._ffmpeg_has_filter("subtitles", ffmpeg_binary=self.ffmpeg):
            return self.ffmpeg

        for candidate in self._macos_subtitle_burn_ffmpeg_candidates():
            if self._ffmpeg_has_filter("subtitles", ffmpeg_binary=candidate):
                return candidate

        raise DependencyMissingError(self._missing_subtitle_burn_dependency_message())

    def _macos_subtitle_burn_ffmpeg_candidates(self) -> list[str]:
        if platform.system() != "Darwin":
            return []

        candidates: list[str] = []
        path_candidate = shutil.which("ffmpeg-full")
        if path_candidate:
            candidates.append(path_candidate)

        prefixes = [
            os.environ.get("HOMEBREW_PREFIX"),
            "/opt/homebrew",
            "/usr/local",
        ]
        for prefix in prefixes:
            if not prefix:
                continue
            candidate = Path(prefix) / "opt" / "ffmpeg-full" / "bin" / "ffmpeg"
            if candidate.exists():
                candidates.append(str(candidate))

        deduped: list[str] = []
        seen: set[str] = set()
        current = str(Path(self.ffmpeg).expanduser())
        for candidate in candidates:
            resolved = str(Path(candidate).expanduser())
            if resolved == current or resolved in seen:
                continue
            seen.add(resolved)
            deduped.append(resolved)
        return deduped

    def _missing_subtitle_burn_dependency_message(self) -> str:
        message = (
            "ffmpeg subtitle burn failed.\n"
            "The active ffmpeg build does not include the `subtitles` filter, which requires libass."
        )
        if platform.system() == "Darwin":
            return (
                f"{message}\n"
                "Homebrew's core `ffmpeg` formula omits libass, so subtitle burn-in falls back poorly.\n"
                "Install a libass-enabled build such as `ffmpeg-full`, then put it on PATH, for example:\n"
                "  brew install ffmpeg-full\n"
                '  export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"\n'
                "Verify with:\n"
                "  ffmpeg -hide_banner -filters | rg subtitles"
            )
        return f"{message}\nInstall an ffmpeg build compiled with libass."

    def _process_output_if_exited(self) -> tuple[str, str]:
        if self.process is None:
            return "", ""

        if self.process.poll() is None:
            return "", ""

        stdout, stderr = self.process.communicate(timeout=1)
        return stdout or "", stderr or ""

    def _build_start_command(
        self,
        *,
        system: str,
        region: CaptureRegion | None,
    ) -> list[str]:
        if region is not None:
            region.validate()

        if system == "Windows":
            return self._build_windows_start_command(region)
        if system == "Darwin":
            return self._build_macos_start_command(region)

        raise RecordingError(
            f"The ffmpeg backend currently supports Windows and macOS capture, not {system}."
        )

    def _build_windows_start_command(
        self,
        region: CaptureRegion | None,
    ) -> list[str]:
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "gdigrab",
            "-draw_mouse",
            "1" if self.draw_mouse else "0",
            "-framerate",
            str(self.framerate),
        ]

        if region is not None:
            command.extend(
                [
                    "-offset_x",
                    str(region.left),
                    "-offset_y",
                    str(region.top),
                    "-video_size",
                    region.size_arg,
                ]
            )

        command.extend(
            [
                "-i",
                "desktop",
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(self.crf),
                "-vf",
                self._build_video_filter(region=None),
                str(self.raw_video_path.resolve()),
            ]
        )
        return command

    def _build_macos_start_command(
        self,
        region: CaptureRegion | None,
    ) -> list[str]:
        screen_device = self._resolve_macos_screen_device()
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-capture_cursor",
            "1" if self.draw_mouse else "0",
            "-capture_mouse_clicks",
            "1" if self.draw_mouse else "0",
            "-framerate",
            str(self.framerate),
            "-i",
            f"{screen_device}:none",
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-vf",
            self._build_video_filter(region=region),
            str(self.raw_video_path.resolve()),
        ]
        return command

    def _build_video_filter(self, *, region: CaptureRegion | None) -> str:
        filters: list[str] = []
        if region is not None:
            filters.append(
                f"crop={region.width}:{region.height}:{region.left}:{region.top}"
            )
        if self.scale_width and self.scale_width > 0:
            filters.append(f"scale={self.scale_width}:-2")
        filters.append("format=yuv420p")
        return ",".join(filters)

    def _resolve_macos_screen_device(self) -> str:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        detail = (result.stderr + "\n" + result.stdout).strip()
        match = re.search(r"\[(\d+)\]\s+Capture screen\b", detail)
        if match is not None:
            return match.group(1)

        raise RecordingError(
            "ffmpeg could not find a macOS screen capture device.\n"
            "Make sure your ffmpeg build includes avfoundation input support and that "
            "macOS screen capture is available for this terminal.\n"
            f"{detail}"
        )

    def _format_start_failure_detail(self, *, stderr: str, stdout: str) -> str:
        detail = (stderr + "\n" + stdout).strip()
        if detail:
            return detail

        if platform.system() != "Darwin":
            return detail

        return (
            "macOS may still be blocking screen capture for this terminal or Python host. "
            "Grant Screen Recording permission in System Settings, then retry."
        )

    def _burn_subtitles_with_ffmpeg_filter(
        self,
        *,
        subtitle_path: Path,
        output_path: Path,
        ffmpeg_binary: str,
        audio_path: Path | None = None,
    ) -> None:
        command = [
            ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            self.raw_video_path.name,
        ]
        if audio_path is not None:
            command.extend(["-i", str(audio_path.resolve())])

        command.extend(
            [
                "-vf",
                self._subtitles_filter_value(subtitle_path),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
            ]
        )
        if audio_path is not None:
            command.extend(["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"])
        command.extend(["-movflags", "+faststart", str(output_path.resolve())])
        result = subprocess.run(
            command,
            cwd=str(self.raw_video_path.parent),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr + "\n" + result.stdout).strip()
            raise RecordingError(f"ffmpeg subtitle burn failed.\n{detail}")

    def _mux_audio(self, *, audio_path: Path, output_path: Path) -> None:
        command = [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self.raw_video_path.resolve()),
            "-i",
            str(audio_path.resolve()),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path.resolve()),
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
            detail = (result.stderr + "\n" + result.stdout).strip()
            raise RecordingError(f"ffmpeg audio mux failed.\n{detail}")

    def _burn_subtitles_with_macos_overlay(
        self,
        *,
        subtitle_path: Path,
        output_path: Path,
    ) -> None:
        cues = self._load_srt_cues(subtitle_path)
        if not cues:
            shutil.copy2(self.raw_video_path, output_path)
            return

        width, height = self._probe_video_dimensions()
        if width <= 0 or height <= 0:
            raise RecordingError("Could not determine the raw video dimensions.")

        with tempfile.TemporaryDirectory(
            prefix="demo-video-recorder-subtitles-"
        ) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            renderer = self._write_macos_subtitle_renderer(temp_dir)
            overlay_images: list[Path] = []

            for index, cue in enumerate(cues, start=1):
                text_file = temp_dir / f"cue-{index:04}.txt"
                image_file = temp_dir / f"cue-{index:04}.png"
                text_file.write_text(str(cue["text"]), encoding="utf-8")
                self._render_macos_subtitle_image(
                    renderer=renderer,
                    text_file=text_file,
                    output_path=image_file,
                    width=width,
                    height=max(int(round(height * 0.18)), 120),
                )
                overlay_images.append(image_file)

            command = [
                self.ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(self.raw_video_path.resolve()),
            ]
            for image_file in overlay_images:
                command.extend(["-i", str(image_file)])

            filter_graph_parts: list[str] = []
            last_stream = "[0:v]"
            for index, cue in enumerate(cues, start=1):
                output_stream = f"[v{index}]"
                enable = self._between_expression(
                    cue["start_seconds"], cue["end_seconds"]  # type: ignore
                )
                filter_graph_parts.append(
                    f"{last_stream}[{index}:v]overlay="
                    f"x=(main_w-overlay_w)/2:"
                    f"y=main_h-overlay_h-40:"
                    f"eof_action=repeat:"
                    f"enable='{enable}'"
                    f"{output_stream}"
                )
                last_stream = output_stream

            command.extend(
                [
                    "-filter_complex",
                    ";".join(filter_graph_parts),
                    "-map",
                    last_stream,
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(output_path.resolve()),
                ]
            )
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                detail = (result.stderr + "\n" + result.stdout).strip()
                raise RecordingError(f"ffmpeg subtitle burn failed.\n{detail}")

    def _ffmpeg_has_filter(
        self, filter_name: str, *, ffmpeg_binary: str | None = None
    ) -> bool:
        result = subprocess.run(
            [ffmpeg_binary or self.ffmpeg, "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return False
        pattern = re.compile(rf"\b{re.escape(filter_name)}\b")
        return bool(pattern.search(result.stdout))

    def _subtitles_filter_value(self, subtitle_path: Path) -> str:
        escaped = str(subtitle_path.resolve())
        escaped = escaped.replace("\\", "\\\\")
        escaped = escaped.replace(":", "\\:")
        escaped = escaped.replace("'", "\\'")
        return f"subtitles=filename='{escaped}'"

    def _probe_video_dimensions(self) -> tuple[int, int]:
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(self.raw_video_path),
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
            raise RecordingError(f"ffprobe failed.\n{result.stderr.strip()}")

        line = result.stdout.strip().splitlines()[0]
        width_text, height_text = line.split("x", 1)
        return int(width_text), int(height_text)

    def _load_srt_cues(self, subtitle_path: Path) -> list[dict[str, float | str]]:
        blocks = re.split(
            r"(?:\r?\n){2,}",
            subtitle_path.read_text(encoding="utf-8").strip(),
        )
        cues: list[dict[str, float | str]] = []
        for block in blocks:
            lines = [line.rstrip() for line in block.splitlines() if line.strip()]
            if len(lines) < 3:
                continue

            timing = lines[1]
            if " --> " not in timing:
                continue
            start_text, end_text = timing.split(" --> ", 1)
            cues.append(
                {
                    "start_seconds": parse_srt_time(start_text),
                    "end_seconds": parse_srt_time(end_text),
                    "text": "\n".join(lines[2:]),
                }
            )
        return cues

    def _write_macos_subtitle_renderer(self, temp_dir: Path) -> Path:
        script_path = temp_dir / "render_subtitle.swift"
        script_path.write_text(
            textwrap.dedent("""
                import AppKit
                import Foundation

                func value(_ flag: String) -> String {
                    guard let index = CommandLine.arguments.firstIndex(of: flag),
                          index + 1 < CommandLine.arguments.count else {
                        fputs("Missing argument: \\(flag)\\n", stderr)
                        exit(2)
                    }
                    return CommandLine.arguments[index + 1]
                }

                let text = try String(contentsOfFile: value("--text-file"), encoding: .utf8)
                let output = URL(fileURLWithPath: value("--output"))
                let width = CGFloat(Double(value("--width")) ?? 1280)
                let height = CGFloat(Double(value("--height")) ?? 160)
                let fontSize = CGFloat(Double(value("--font-size")) ?? 42)
                let image = NSImage(size: NSSize(width: width, height: height))

                image.lockFocus()
                NSColor.clear.setFill()
                NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()

                let paragraph = NSMutableParagraphStyle()
                paragraph.alignment = .center
                paragraph.lineBreakMode = .byWordWrapping

                let shadow = NSShadow()
                shadow.shadowColor = NSColor.black.withAlphaComponent(0.85)
                shadow.shadowBlurRadius = 8
                shadow.shadowOffset = NSSize(width: 0, height: -2)

                let attributes: [NSAttributedString.Key: Any] = [
                    .font: NSFont.systemFont(ofSize: fontSize, weight: .semibold),
                    .foregroundColor: NSColor.white,
                    .strokeColor: NSColor.black.withAlphaComponent(0.9),
                    .strokeWidth: -3.0,
                    .paragraphStyle: paragraph,
                    .shadow: shadow,
                ]

                let attributed = NSAttributedString(string: text, attributes: attributes)
                let bounds = NSRect(x: 36, y: 24, width: width - 72, height: height - 48)
                attributed.draw(with: bounds, options: [.usesLineFragmentOrigin, .usesFontLeading])
                image.unlockFocus()

                guard let tiff = image.tiffRepresentation,
                      let bitmap = NSBitmapImageRep(data: tiff),
                      let png = bitmap.representation(using: .png, properties: [:]) else {
                    fputs("Could not render subtitle image\\n", stderr)
                    exit(3)
                }

                try png.write(to: output)
                """).strip() + "\n",
            encoding="utf-8",
        )
        return script_path

    def _render_macos_subtitle_image(
        self,
        *,
        renderer: Path,
        text_file: Path,
        output_path: Path,
        width: int,
        height: int,
    ) -> None:
        font_size = max(int(round(height * 0.28)), 28)
        result = subprocess.run(
            [
                "swift",
                str(renderer),
                "--text-file",
                str(text_file),
                "--output",
                str(output_path),
                "--width",
                str(width),
                "--height",
                str(height),
                "--font-size",
                str(font_size),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr + "\n" + result.stdout).strip()
            raise RecordingError(f"Could not render subtitle overlay.\n{detail}")

    def _between_expression(self, start_seconds: float, end_seconds: float) -> str:
        return f"between(t,{start_seconds:.3f},{end_seconds:.3f})"
