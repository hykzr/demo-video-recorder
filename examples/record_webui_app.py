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
    WebUIRecorder,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_APP = Path(__file__).with_name("webui_app")


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
        keep_raw=False,
        keep_tts_audio=args.keep_tts_audio,
        tts=tts_backend,
        **settings.recorder_kwargs(),  # type: ignore[arg-type]
    )
    final_path: Path | None = None

    (
        intro,
        contact_details,
        profile_details,
        preferences,
        finish,
        conclusion,
    ) = recorder.prepare_cues(
        [
            "Let's fill out this member intake form.",
            "I'll start with name, email, phone, and address.",
            "Next, I'll choose a birthday and a preferred color.",
            "Now come gender, salary tier, and travel readiness.",
            "Finally, I'll add notes, accept terms, and review.",
            "The review panel confirms the submitted intake details.",
        ],
        async_tts=args.async_tts,
    )

    try:
        recorder.serve(WEB_APP, args.port)
        recorder.open_web("/", start_recording=not args.no_record)
        recorder.explain(intro)

        recorder.explain(contact_details)
        recorder.find_input(label="Full name", _class="contact-input").fill("Maya Chen")
        recorder.find_input(label="Email address", type="email").fill(
            "maya.chen@example.com"
        )
        recorder.find_input(label="Telephone", type="tel").fill("+1 415 555 0198")
        recorder.find_input(label="Street address", _class="address-input").fill(
            "212 Market Street"
        )
        recorder.find_input(label="City", _class="address-input").fill("San Francisco")
        recorder.find_input(label="Postal code", _class="address-input").fill("94105")

        recorder.explain(profile_details)
        recorder.find_input(label="Date of birth", type="date").set_date("1991-08-14")
        recorder.find_input(label="Preferred color", type="color").set_color("#146348")

        recorder.explain(preferences)
        recorder.find_input("input", {"name": "gender", "value": "Female"}).check()
        recorder.find_select(label="Salary tier").select_option(
            label="$100,000 to $150,000"
        )
        recorder.find_input("input", type="range").set_range(8)
        recorder.find("output", id="travel-output", text="8").highlight()

        recorder.explain(finish)
        recorder.find_input(label="Notes").fill(
            "Prefers a morning call and wants a practical plan before the end of the week."
        )
        recorder.find_input("input", id="terms").check()
        recorder.find("button", text="Review intake details").click()
        recorder.find("aside", text="Maya Chen").highlight()
        recorder.find("aside", text="1991-08-14")
        recorder.find("aside", text="Accepted")
        recorder.explain(conclusion)

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
