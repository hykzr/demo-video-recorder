from demo_video_recorder.subtitles import format_srt_time, parse_srt_time, SubtitleWriter


def test_format_and_parse_srt_time() -> None:
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(65.432) == "00:01:05,432"
    assert parse_srt_time("01:02:03,004") == 3723.004


def test_trim_to_duration_clips_and_reindexes(tmp_path) -> None:
    srt = tmp_path / "demo.srt"
    srt.write_text(
        "\n".join(
            [
                "1",
                "00:00:00,000 --> 00:00:02,000",
                "First cue",
                "",
                "2",
                "00:00:03,000 --> 00:00:04,000",
                "Second cue",
                "",
            ]
        ),
        encoding="utf-8",
    )

    writer = SubtitleWriter(srt)
    writer.trim_to_duration(1.25)

    assert srt.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "First cue\n"
    )
