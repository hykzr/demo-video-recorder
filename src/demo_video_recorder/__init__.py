"""Public API for demo-video-recorder."""

from demo_video_recorder.cli import CLIDemoRecorder, OutputMarker
from demo_video_recorder.core import DemoVideoRecorder, PreparedCue
from demo_video_recorder.defaults import (
    DEFAULTS,
    FAST_SMOKE_TEST_DEFAULTS,
    RecorderDefaults,
)
from demo_video_recorder.errors import (
    DemoVideoRecorderError,
    DependencyMissingError,
    ProcessError,
    RecordingError,
    WebElementNotFoundError,
    WindowNotFoundError,
)
from demo_video_recorder.macos import (
    ScreenRecordingAccessResult,
    check_screen_recording_access,
)
from demo_video_recorder.tts import (
    EdgeTTSBackend,
    MacOSTTSBackend,
    NarrationClip,
    NativeTTSBackend,
    SynthesizedAudio,
    SynthesizedExplanation,
    TTSBackend,
    WindowsTTSBackend,
)
from demo_video_recorder.types import CaptureRegion, WindowInfo
from demo_video_recorder.web import (
    WebElement,
    WebFormElement,
    WebInputElement,
    WebSelectElement,
    WebUIRecorder,
)

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
    "MacOSTTSBackend",
    "NarrationClip",
    "NativeTTSBackend",
    "OutputMarker",
    "ProcessError",
    "PreparedCue",
    "RecorderDefaults",
    "RecordingError",
    "ScreenRecordingAccessResult",
    "SynthesizedAudio",
    "SynthesizedExplanation",
    "TTSBackend",
    "WebElement",
    "WebElementNotFoundError",
    "WebFormElement",
    "WebInputElement",
    "WebSelectElement",
    "WebUIRecorder",
    "WindowsTTSBackend",
    "WindowInfo",
    "WindowNotFoundError",
]
