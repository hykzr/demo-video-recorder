"""Public API for demo-video-recorder."""

from demo_video_recorder.cli import CLIDemoRecorder
from demo_video_recorder.core import DemoVideoRecorder
from demo_video_recorder.errors import (
    DemoVideoRecorderError,
    DependencyMissingError,
    ProcessError,
    RecordingError,
    WindowNotFoundError,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo

__all__ = [
    "CLIDemoRecorder",
    "CaptureRegion",
    "DemoVideoRecorder",
    "DemoVideoRecorderError",
    "DependencyMissingError",
    "ProcessError",
    "RecordingError",
    "WindowInfo",
    "WindowNotFoundError",
]
