"""Record a demo video for the example guessing game."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pyrootutils

root = pyrootutils.setup_root(__file__, dotenv=True, pythonpath=True, cwd=False)

from demo_video_recorder import (
    CLIDemoRecorder,
    DEFAULTS,
    EdgeTTSBackend,
    FAST_SMOKE_TEST_DEFAULTS,
    NativeTTSBackend,
    ProcessError,
    SynthesizedExplanation,
)

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(__file__).with_name("guessing_game.py")
OUTCOME_PATTERN = (
    r"(?P<low>Too low\. Try a bigger number\.)|"
    r"(?P<high>Too high\. Try a smaller number\.)|"
    r"(?P<won>You got it in (?P<attempts>\d+) guesses\.)"
)
MAX_REOPEN_ATTEMPTS = 10
DEFAULT_WINDOW_SIZE = (1400, 1000)


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
        "--window-size",
        type=parse_window_size,
        default=DEFAULT_WINDOW_SIZE,
        metavar="WIDTHxHEIGHT",
        help="Terminal window size in pixels. Defaults to 1400x1000.",
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
        help="Use TTS so explain() also produces narration audio.",
    )
    parser.add_argument(
        "--backend",
        choices=("edge", "native"),
        default="edge",
        help="TTS backend to use when narration audio is enabled.",
    )
    parser.add_argument(
        "--tts-speaker",
        default=None,
        help="TTS speaker/voice name. Defaults to the selected backend default.",
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
        "--cache-tts",
        action="store_true",
        dest="cache_tts",
        default=True,
        help="Reuse generated TTS clips between runs.",
    )
    parser.add_argument(
        "--async",
        action="store_true",
        dest="async_tts",
        help="Pre-synthesize known narration clips concurrently before recording.",
    )
    parser.add_argument(
        "--keep-tts-audio",
        action="store_true",
        help="Keep the generated per-line TTS clips and mixed narration track.",
    )
    parser.add_argument(
        "--list-speakers",
        action="store_true",
        help="Print available speakers for the selected TTS backend and exit.",
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


def parse_window_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "window size must look like WIDTHxHEIGHT, for example 1200x1200"
        ) from exc

    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("window size values must be positive integers")
    return (width, height)


def build_tts_backend(args: argparse.Namespace, save_dir: Path):
    if args.backend == "native":
        return NativeTTSBackend(
            save_dir=save_dir,
            speaker=args.tts_speaker,
            cache=args.cache_tts,
        )

    return EdgeTTSBackend(
        save_dir=save_dir,
        speaker=args.tts_speaker or "en-US-AvaMultilingualNeural",
        speed=args.tts_speed,
        volume=args.tts_volume,
        cache=args.cache_tts,
    )


def open_game(
    recorder: CLIDemoRecorder, *, label: str | SynthesizedExplanation
) -> tuple[int, int]:
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
            recorder.explain(f"I'm starting in the middle with {guess}.")
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
        recorder.explain(f"And there we go: it was {guess}.")
        recorder.stop_app()
        return guess

    raise ProcessError(
        f"The game hints contradicted the displayed range {original_low}..{original_high}."
    )


def play_one_game(
    recorder: CLIDemoRecorder, *, launch_message: str | SynthesizedExplanation
) -> int:
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
    tts_backend = build_tts_backend(args, tts_save_dir) if tts_enabled else None
    if args.list_speakers:
        speaker_backend = tts_backend or build_tts_backend(args, tts_save_dir)
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

    (
        intro_msg,
        first_run_msg,
        new_run_msg,
        subsequent_run_msg,
        same_number_msg,
        conclusion_msg,
    ) = recorder.prepare_cues(
        [
            "I'm going to demonstrate the CLI guessing game.",
            "First run. I'll open the game and start guessing.",
            "Now I'll reopen it to prove each run picks randomly.",
            "Let's try the game again.",
            "It rolled the same number again. Unlikely, but possible.",
            "This demo reacts to real app output and narrates each step.",
        ],
        async_tts=args.async_tts,
    )

    try:
        if not audio_only:
            recorder.open_terminal(
                title="Guessing Game Demo",
                top=True,
                window_size=args.window_size,
                start_recording=not args.no_record,
                clear=True,
                new_window=args.new_window,
                check_access=args.check_access and not args.no_record,
            )

        recorder.explain(intro_msg)
        first_answer = play_one_game(
            recorder,
            launch_message=first_run_msg,
        )

        recorder.explain(new_run_msg)
        for attempt in range(1, args.max_reopen_attempts + 1):
            second_answer = play_one_game(
                recorder,
                launch_message=subsequent_run_msg,
            )
            if second_answer != first_answer:
                recorder.explain(
                    f"Nice, this time it picked {second_answer} instead of {first_answer}. It works!"
                )
                break

            recorder.explain(same_number_msg)
        else:
            raise ProcessError(
                f"The game repeated {first_answer} for {args.max_reopen_attempts} reopen attempts."
            )
        recorder.explain(conclusion_msg)

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
