"""Record a demo video for the example guessing game."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from demo_video_recorder import (
    CLIDemoRecorder,
    DEFAULTS,
    EdgeTTSBackend,
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


def default_output_path(*, audio_only: bool) -> Path:
    suffix = ".m4a" if audio_only else ".mp4"
    return ROOT / "out" / f"guessing-game-demo{suffix}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=None,
        help="Final output path. Defaults to MP4, or M4A with --audio-only.",
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
        "--audio-only",
        action="store_true",
        help="Skip terminal/window capture and render only the narration audio timeline.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use shorter pauses for quick local smoke tests.",
    )
    parser.add_argument(
        "--tts",
        action="store_true",
        help="Use Edge TTS so explain() also produces narration audio.",
    )
    parser.add_argument(
        "--tts-speaker",
        default="en-US-JennyNeural",
        help="Edge TTS speaker/voice name.",
    )
    parser.add_argument(
        "--tts-speed",
        default="+0%",
        help="Edge TTS speech rate, for example +10%% or -15%%.",
    )
    parser.add_argument(
        "--tts-volume",
        default="+0%",
        help="Edge TTS volume adjustment, for example +0%% or -20%%.",
    )
    parser.add_argument(
        "--tts-save-dir",
        default=None,
        help="Directory for intermediate per-line TTS clips.",
    )
    parser.add_argument(
        "--keep-tts-audio",
        action="store_true",
        help="Keep the generated per-line TTS clips and mixed narration track.",
    )
    parser.add_argument(
        "--list-speakers",
        action="store_true",
        help="Print available Edge TTS speakers and exit.",
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
    recorder.explain(label)
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
            recorder.explain(
                f"I'm starting in the middle with {guess}. No peeking at the answer, just reading the hints."
            )
        elif low == high:
            recorder.explain(
                f"The hints have narrowed it down to {guess}, so this should be the one."
            )
        else:
            recorder.explain(
                f"That trims the search to {low} through {high}. Best next guess is {guess}."
            )

        marker = recorder.mark_output()
        recorder.input(str(guess))
        outcome = recorder.expect_regex(
            OUTCOME_PATTERN, since=marker, timeout_seconds=5
        )

        if outcome.group("low"):
            low = guess + 1
            recorder.expect_output("Guess>", since=marker, timeout_seconds=5)
            continue

        if outcome.group("high"):
            high = guess - 1
            recorder.expect_output("Guess>", since=marker, timeout_seconds=5)
            continue

        recorder.expect_output("Thanks for playing.", since=marker, timeout_seconds=5)
        recorder.explain(
            f"And there we go: it was {guess}. We got there by reacting to the app output."
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
    audio_only = args.audio_only
    tts_enabled = args.tts or audio_only
    output_path = (
        Path(args.output)
        if args.output is not None
        else default_output_path(audio_only=audio_only)
    )
    tts_save_dir = (
        Path(args.tts_save_dir)
        if args.tts_save_dir is not None
        else output_path.with_name(f"{output_path.stem}.tts")
    )
    tts_backend = (
        EdgeTTSBackend(
            save_dir=tts_save_dir,
            speaker=args.tts_speaker,
            speed=args.tts_speed,
            volume=args.tts_volume,
        )
        if tts_enabled
        else None
    )
    if args.list_speakers:
        speaker_backend = tts_backend or EdgeTTSBackend(
            save_dir=tts_save_dir,
            speaker=args.tts_speaker,
            speed=args.tts_speed,
            volume=args.tts_volume,
        )
        for speaker in speaker_backend.list_speakers():
            print(speaker)
        return 0

    recorder = CLIDemoRecorder(
        output_path,
        **settings.recorder_kwargs(),  # type: ignore
        keep_raw=False,
        keep_tts_audio=args.keep_tts_audio,
        tts=tts_backend,
    )
    final_path: Path | None = None

    try:
        if not audio_only:
            recorder.open_terminal(
                title="Guessing Game Demo",
                top=True,
                start_recording=not args.no_record,
                new_window=args.new_window,
                check_access=args.check_access and not args.no_record,
            )

        recorder.explain(
            "Let's do this like a real little live demo: the game picks randomly, and I'll figure it out from the clues."
        )
        first_answer = play_one_game(
            recorder,
            launch_message="First run. I'll open the game and let it choose whatever number it wants.",
        )

        recorder.explain(
            "Now I'm going to reopen the CLI app. The goal is to prove a new run starts fresh."
        )
        for attempt in range(1, args.max_reopen_attempts + 1):
            second_answer = play_one_game(
                recorder,
                launch_message=f"Reopen attempt {attempt}: fresh process, fresh random pick.",
            )
            if second_answer != first_answer:
                recorder.explain(
                    f"Nice, this time it picked {second_answer} instead of {first_answer}. Reopen behavior checked."
                )
                break

            recorder.explain(
                f"Oops, it rolled {second_answer} again. Randomness is allowed to be boring; I'll reopen once more."
            )
        else:
            raise ProcessError(
                f"The game repeated {first_answer} for {args.max_reopen_attempts} reopen attempts."
            )

        recorder.explain(
            "That's the demo: random app behavior, output-aware guesses, and a clean reopen check."
        )
        if audio_only:
            final_path = recorder.render_narration_audio(output_path)
        elif args.no_record and tts_enabled:
            final_path = recorder.render_narration_audio(
                output_path.with_suffix(".m4a")
            )
    finally:
        recorder.close()
        if recorder.is_recording:
            final_path = recorder.stop_recording()

    if final_path is not None:
        print(f"\nRecorded demo: {final_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
