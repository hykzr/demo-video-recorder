"""Record a demo video for the bundled Web UI example."""

from __future__ import annotations

import argparse
from pathlib import Path
import pyrootutils

root = pyrootutils.setup_root(__file__, dotenv=True, pythonpath=True, cwd=False)

from demo_video_recorder import (
    DEFAULTS,
    EdgeTTSBackend,
    FAST_SMOKE_TEST_DEFAULTS,
    NativeTTSBackend,
    SubtitleStyle,
    WebUIRecorder,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_APP = Path(__file__).with_name("webui_app")
INTAKE_NOTES = (
    "Prefers a morning call and wants a practical plan before the end of the week."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / "out" / "webui-demo.mp4"),
        help="Final output path.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Localhost port for the static example app.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while recording instead of running headless.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use shorter pauses for quick local smoke tests.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Run the scripted browser demo without screen capture.",
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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = FAST_SMOKE_TEST_DEFAULTS if args.fast else DEFAULTS
    output_path = Path(args.output)
    tts_save_dir = (
        Path(args.tts_save_dir)
        if args.tts_save_dir is not None
        else output_path.with_name(f"{output_path.stem}.tts")
    )
    tts_backend = (
        build_tts_backend(args, tts_save_dir)
        if args.tts or args.list_speakers
        else None
    )
    if args.list_speakers:
        assert tts_backend is not None
        for speaker in tts_backend.list_speakers():
            print(speaker)
        return 0

    recorder = WebUIRecorder(
        output_path,
        headless=not args.headed,
        viewport=(1280, 720),
        slow_mo_ms=0 if args.fast else 80,
        scroll_duration_ms=0 if args.fast else 520,
        action_pause_seconds=0.08 if args.fast else 0.28,
        keep_raw=False,
        keep_tts_audio=args.keep_tts_audio,
        subtitle_style=SubtitleStyle(
            font_name="Arial",
            font_size=12,
            primary_color="#ffffff",
            outline_color="#000000",
            border_style=1,
            outline=0.7,
            shadow=0,
            alignment="bottom_center",
            margin_vertical=20,
        ),
        tts=tts_backend,
        **settings.recorder_kwargs(),  # type: ignore[arg-type]
    )
    final_path: Path | None = None

    cues = recorder.prepare_cues(
        {
            "intro": "Let's fill out this member intake form.",
            "contact_details": "I'll start with name, email, phone, and address.",
            "profile_details": "Next, I'll choose a birthday and a preferred color.",
            "preferences": "Now come gender, salary tier, and travel readiness.",
            "finish": "Finally, I'll add notes, accept terms, and review.",
            "conclusion": "The review panel confirms the submitted intake details.",
            "corrections": "If a detail is wrong, the form can be edited and submitted again.",
            "resubmitted": "The review panel now reflects the corrected intake details.",
        },
        async_tts=args.async_tts,
    )

    try:
        recorder.serve(WEB_APP, args.port)
        recorder.open_web("/", start_recording=not args.no_record)
        recorder.explain(cues["intro"])
        recorder.pause(0.08 if args.fast else 0.4)

        def enter_contact_details() -> None:
            recorder.find_input(label="Full name", _class="contact-input").fill(
                "Maya Chen"
            )
            recorder.find_input(label="Email address", type="email").fill(
                "maya.chen@example.com"
            )
            recorder.find_input(label="Telephone", type="tel").fill("+1 415 555 0198")
            recorder.find_input(label="Street address", _class="address-input").fill(
                "212 Market Street"
            )
            recorder.find_input(label="City", _class="address-input").fill(
                "San Francisco"
            )
            recorder.find_input(label="Postal code", _class="address-input").fill(
                "94105"
            )

        recorder.explain_during(cues["contact_details"], enter_contact_details)

        def enter_profile_details() -> None:
            recorder.find_input(label="Date of birth", type="date").set_date(
                "1991-08-14"
            )
            recorder.find_input(label="Preferred color", type="color").set_color(
                "#146348"
            )

        recorder.explain_during(cues["profile_details"], enter_profile_details)

        def enter_preferences() -> None:
            recorder.find_input("input", {"name": "gender", "value": "Female"}).check()
            recorder.find_select(label="Salary tier").select_option(
                label="$100,000 to $150,000"
            )
            recorder.find_input("input", type="range").set_range(8)
            recorder.find("output", id="travel-output", text="8").highlight()

        recorder.explain_during(cues["preferences"], enter_preferences)

        def finish_submission() -> None:
            recorder.find_input(label="Notes").fill(INTAKE_NOTES)
            recorder.find_input("input", id="terms").check()
            recorder.find("button", text="Review intake details").click()
            recorder.pause(0.08 if args.fast else 0.45)
            recorder.find("aside", text="Maya Chen").highlight()
            recorder.find("aside", text="1991-08-14")
            recorder.find("aside", text="Accepted")

        recorder.explain_during(cues["finish"], finish_submission)
        recorder.explain(cues["conclusion"])

        def correct_submission() -> None:
            recorder.find_input(label="Date of birth", type="date").set_date(
                "1990-08-14"
            )
            recorder.find_input(label="Preferred color", type="color").set_color(
                "#725ac1"
            )
            recorder.find_select(label="Salary tier").select_option(
                label="$150,000 or more"
            )
            email = recorder.find_input(label="Email address", type="email")
            email.select_text("maya.chen")
            email.edit_text("maya.chen+intake@example.com")
            notes = recorder.find_input(label="Notes")
            notes.select_clear_paste(0.5 if not args.fast else 0.08, INTAKE_NOTES)
            recorder.find("button", text="Review intake details").click()
            recorder.pause(0.08 if args.fast else 0.45)
            recorder.find("aside", text="maya.chen+intake@example.com").highlight()
            recorder.find("aside", text="1990-08-14")
            recorder.find("aside", text="#725ac1")
            recorder.find("aside", text="$150,000 or more")
            recorder.find("aside", text="Prefers a morning call")

        recorder.explain_during(cues["corrections"], correct_submission)
        recorder.explain(cues["resubmitted"])

        if args.no_record and args.tts:
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
