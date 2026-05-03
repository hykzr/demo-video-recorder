"""Default recorder settings.

These values come from the original PowerShell demo script so agents and
recording scripts can omit timing knobs unless the user asked for a different
speed or style.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecorderDefaults:
    words_per_minute: int = 170
    min_pause_seconds: float = 2.0
    command_lead_seconds: float = 0.0
    typed_character_delay: float = 0.018
    capture_framerate: int = 15
    video_scale_width: int = 1280

    def recorder_kwargs(self) -> dict[str, int | float]:
        """Return keyword arguments accepted by ``CLIDemoRecorder``."""

        return {
            "words_per_minute": self.words_per_minute,
            "min_pause_seconds": self.min_pause_seconds,
            "command_lead_seconds": self.command_lead_seconds,
            "typed_character_delay": self.typed_character_delay,
            "capture_framerate": self.capture_framerate,
            "video_scale_width": self.video_scale_width,
        }


DEFAULTS = RecorderDefaults()

FAST_SMOKE_TEST_DEFAULTS = RecorderDefaults(
    words_per_minute=900,
    min_pause_seconds=0.75,
    typed_character_delay=0.004,
)
