"""Public API for demo-video-recorder."""

from demo_video_recorder.cli import CLIDemoRecorder, OutputMarker
from demo_video_recorder.core import DemoVideoRecorder
from demo_video_recorder.defaults import DEFAULTS, FAST_SMOKE_TEST_DEFAULTS, RecorderDefaults
from demo_video_recorder.errors import (
    DemoVideoRecorderError,
    DependencyMissingError,
    ProcessError,
    RecordingError,
    WindowNotFoundError,
)
from demo_video_recorder.macos import (
    ScreenRecordingAccessResult,
    check_screen_recording_access,
)
from demo_video_recorder.tts import (
    EdgeTTSBackend,
    NarrationClip,
    SynthesizedAudio,
    TTSBackend,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo

__all__ = [
    "CLIDemoRecorder",
    "CaptureRegion",
    "check_screen_recording_access",
    "DEFAULTS",
    "DemoVideoRecorder",
    "DemoVideoRecorderError",
    "DependencyMissingError",
    "EdgeTTSBackend",
    "FAST_SMOKE_TEST_DEFAULTS",
    "NarrationClip",
    "OutputMarker",
    "ProcessError",
    "RecorderDefaults",
    "RecordingError",
    "ScreenRecordingAccessResult",
    "SynthesizedAudio",
    "TTSBackend",
    "WindowInfo",
    "WindowNotFoundError",
]
