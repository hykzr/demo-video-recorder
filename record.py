"""Convenience entry point for recording the bundled guessing-game demo."""

from __future__ import annotations

from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "examples" / "record_guessing_game.py"),
        run_name="__main__",
    )
