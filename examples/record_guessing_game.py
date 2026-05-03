"""Record a demo video for the example guessing game."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from demo_video_recorder import CLIDemoRecorder


ROOT = Path(__file__).resolve().parents[1]
GAME = Path(__file__).with_name("guessing_game.py")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / "out" / "guessing-game-demo.mp4"),
        help="Final MP4 path.",
    )
    parser.add_argument(
        "--new-window",
        default=True,
        help="Rerun this script in a dedicated Windows console before recording.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Run the scripted demo without screen capture.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use shorter pauses for quick local smoke tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    min_pause = 0.75 if args.fast else 1.7
    typing_delay = 0.004 if args.fast else 0.018
    words_per_minute = 900 if args.fast else 165

    recorder = CLIDemoRecorder(
        args.output,
        words_per_minute=words_per_minute,
        min_pause_seconds=min_pause,
        typed_character_delay=typing_delay,
        capture_framerate=15,
        video_scale_width=1280,
        keep_raw=False,
    )

    try:
        recorder.open_terminal(
            title="Guessing Game Demo",
            top=True,
            start_recording=not args.no_record,
            new_window=args.new_window,
        )

        recorder.show_explanation(
            "Today we'll record a quick demo of a small command-line number guessing game."
        )
        recorder.run(
            [sys.executable, str(GAME)],
            interactive=True,
            command_label="python examples/guessing_game.py",
        )
        recorder.wait_for_output("Guess>", timeout_seconds=5)

        recorder.show_explanation(
            "The app introduces the range, then waits for the player to make a guess."
        )
        recorder.input("4")
        recorder.wait_for_output("Too low", timeout_seconds=5)

        recorder.show_explanation(
            "A low guess gets immediate feedback, so the player knows to go higher."
        )
        recorder.wait_for_output("Guess>", timeout_seconds=5)
        recorder.input("9")
        recorder.wait_for_output("Too high", timeout_seconds=5)

        recorder.show_explanation(
            "A high guess gets the opposite hint, keeping the interaction easy to follow."
        )
        recorder.wait_for_output("Guess>", timeout_seconds=5)
        recorder.input("7")
        recorder.wait_for_output("Thanks for playing.", timeout_seconds=5)

        recorder.show_explanation(
            "With the correct answer, the game reports the attempt count and exits cleanly."
        )
        recorder.stop_app()
    finally:
        recorder.close()
        if recorder.is_recording:
            final_path = recorder.stop_recording()
            print(f"\nRecorded demo: {final_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
