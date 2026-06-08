"""Exceptions raised by demo-video-recorder."""


class DemoVideoRecorderError(RuntimeError):
    """Base error for recorder failures."""


class DependencyMissingError(DemoVideoRecorderError):
    """Raised when an external executable such as ffmpeg is unavailable."""


class RecordingError(DemoVideoRecorderError):
    """Raised when capture, encoding, or subtitle burn-in fails."""


class WindowNotFoundError(DemoVideoRecorderError):
    """Raised when a requested OS window cannot be located."""


class ProcessError(DemoVideoRecorderError):
    """Raised when a managed demo process fails."""


class WebElementNotFoundError(DemoVideoRecorderError):
    """Raised when a requested web UI element cannot be located."""
