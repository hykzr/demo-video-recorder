"""Record a demo video for the example guessing game."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from demo_video_recorder import (
    CLIDemoRecorder,
    DEFAULTS,
    FAST_SMOKE_TEST_DEFAULTS,
    ProcessError,
)


ROOT = Path(__file__).resolve().parents[1]
GAME = Path(__file__).with_name("guessing_game.py")
OUTCOME_PATTERN = (
    r"(?P<low>Too low\. Try a bigger number\.)|"
    r"(?P<high>Too high\. Try a smaller number\.)|"
    r"(?P<won>You got it in (?P<attempts>\d+) guesses\.)"
)
MAX_REOPEN_ATTEMPTS = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / "out" / "guessing-game-demo.mp4"),
        help="Final MP4 path.",
    )
    parser.add_argument(
        "--new-window",
        action="store_true",
        help="Rerun this script in a dedicated terminal session before recording.",
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
    parser.add_argument(
        "--check-access",
        action=argparse.BooleanOptionalAction,
        default=sys.platform == "darwin",
        help="Check and request macOS Screen Recording access before capture starts.",
    )
    parser.add_argument(
        "--max-reopen-attempts",
        type=int,
        default=MAX_REOPEN_ATTEMPTS,
        help="Safety cap while waiting for the random second answer to differ.",
    )
    return parser


def open_game(recorder: CLIDemoRecorder, *, label: str) -> tuple[int, int]:
    recorder.show_explanation(label)
    recorder.run(
        [sys.executable, str(GAME)],
        interactive=True,
        command_label="python examples/guessing_game.py",
    )
    range_match = recorder.expect_regex(
        r"between (?P<low>\d+) and (?P<high>\d+)",
        timeout_seconds=5,
    )
    recorder.expect_output("Guess>", timeout_seconds=5)
    return int(range_match.group("low")), int(range_match.group("high"))


def play_by_feedback(recorder: CLIDemoRecorder, low: int, high: int) -> int:
    original_low = low
    original_high = high
    attempts = 0

    while low <= high:
        guess = (low + high) // 2
        attempts += 1
        if attempts == 1:
            recorder.show_explanation(
                f"I'm starting in the middle with {guess}. No peeking at the answer, just reading the hints."
            )
        elif low == high:
            recorder.show_explanation(
                f"The hints have narrowed it down to {guess}, so this should be the one."
            )
        else:
            recorder.show_explanation(
                f"That trims the search to {low} through {high}. Best next guess is {guess}."
            )

        marker = recorder.mark_output()
        recorder.input(str(guess))
        outcome = recorder.expect_regex(OUTCOME_PATTERN, since=marker, timeout_seconds=5)

        if outcome.group("low"):
            low = guess + 1
            recorder.expect_output("Guess>", since=marker, timeout_seconds=5)
            continue

        if outcome.group("high"):
            high = guess - 1
            recorder.expect_output("Guess>", since=marker, timeout_seconds=5)
            continue

        recorder.expect_output("Thanks for playing.", since=marker, timeout_seconds=5)
        recorder.show_explanation(
            f"And there we go: it was {guess}. The recorder got there by reacting to the app output."
        )
        recorder.stop_app()
        return guess

    raise ProcessError(
        f"The game hints contradicted the displayed range {original_low}..{original_high}."
    )


def play_one_game(recorder: CLIDemoRecorder, *, launch_message: str) -> int:
    low, high = open_game(recorder, label=launch_message)
    return play_by_feedback(recorder, low, high)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = FAST_SMOKE_TEST_DEFAULTS if args.fast else DEFAULTS

    recorder = CLIDemoRecorder(
        args.output,
        **settings.recorder_kwargs(), # type: ignore
        keep_raw=False,
    )

    try:
        recorder.open_terminal(
            title="Guessing Game Demo",
            top=True,
            start_recording=not args.no_record,
            new_window=args.new_window,
            check_access=args.check_access and not args.no_record,
        )

        recorder.show_explanation(
            "Let's do this like a real little live demo: the game picks randomly, and I'll figure it out from the clues."
        )
        first_answer = play_one_game(
            recorder,
            launch_message="First run. I'll open the game and let it choose whatever number it wants.",
        )

        recorder.show_explanation(
            "Now I'm going to reopen the CLI app. The goal is to prove a new run starts fresh."
        )
        for attempt in range(1, args.max_reopen_attempts + 1):
            second_answer = play_one_game(
                recorder,
                launch_message=f"Reopen attempt {attempt}: fresh process, fresh random pick.",
            )
            if second_answer != first_answer:
                recorder.show_explanation(
                    f"Nice, this time it picked {second_answer} instead of {first_answer}. Reopen behavior checked."
                )
                break

            recorder.show_explanation(
                f"Oops, it rolled {second_answer} again. Randomness is allowed to be boring; I'll reopen once more."
            )
        else:
            raise ProcessError(
                f"The game repeated {first_answer} for {args.max_reopen_attempts} reopen attempts."
            )

        recorder.show_explanation(
            "That's the demo: random app behavior, output-aware guesses, and a clean reopen check."
        )
    finally:
        recorder.close()
        if recorder.is_recording:
            final_path = recorder.stop_recording()
            print(f"\nRecorded demo: {final_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
