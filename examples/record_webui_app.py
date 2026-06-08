"""Record a demo video for the bundled Web UI example."""

from __future__ import annotations

import argparse
from pathlib import Path
import pyrootutils

root = pyrootutils.setup_root(__file__, dotenv=True, pythonpath=True, cwd=False)

from demo_video_recorder import DEFAULTS, FAST_SMOKE_TEST_DEFAULTS, WebUIRecorder

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = FAST_SMOKE_TEST_DEFAULTS if args.fast else DEFAULTS
    recorder = WebUIRecorder(
        args.output,
        headless=not args.headed,
        viewport=(1280, 720),
        **settings.recorder_kwargs(),  # type: ignore[arg-type]
    )

    try:
        recorder.serve(WEB_APP, args.port)
        recorder.open_web("/")
        recorder.explain("This is a tiny web app running from a local folder.")
        recorder.find("input", placeholder="Ada Lovelace").fill("Grace Hopper")
        recorder.explain("The recorder can select inputs and fill them directly.")
        recorder.find("button", text="Greet").click()
        recorder.find("output", id="result", text="Grace Hopper")
        recorder.explain(
            "After clicking the button, it waits until the result appears."
        )
    finally:
        recorder.close()
        if recorder.is_recording:
            final_path = recorder.stop_recording()
            print(f"Wrote {final_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
