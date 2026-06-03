"""Check macOS Screen Recording access for the current host app."""

from __future__ import annotations

import argparse
from pathlib import Path

from demo_video_recorder import CLIDemoRecorder, check_screen_recording_access


ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--new-window",
        action="store_true",
        help="Run the permission check inside a new Terminal.app window first.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait after prompting for access.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    recorder = CLIDemoRecorder(ROOT / "out" / "_access_check.mp4")

    if args.new_window:
        recorder.open_terminal(
            title="Screen Recording Access",
            new_window=True,
            start_recording=False,
            check_access=False,
        )

    result = check_screen_recording_access(
        prompt=True,
        timeout_seconds=args.timeout,
    )
    print(f"Screen recording access status: {result.status}")
    return 0 if result.granted else 1


if __name__ == "__main__":
    raise SystemExit(main())
