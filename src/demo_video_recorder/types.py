"""Shared value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureRegion:
    """A screen region in physical pixels."""

    left: int
    top: int
    width: int
    height: int

    def validate(self) -> "CaptureRegion":
        if self.width <= 0 or self.height <= 0:
            msg = f"Invalid capture region size: {self.width}x{self.height}"
            raise ValueError(msg)
        return self

    @property
    def size_arg(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class WindowInfo:
    """Metadata for a visible desktop window."""

    hwnd: int
    title: str
    region: CaptureRegion
