from demo_video_recorder.subtitles import (
    SubtitleStyle,
    SubtitleWriter,
    format_srt_time,
    parse_srt_time,
    subtitle_style_to_force_style,
)


def test_format_and_parse_srt_time() -> None:
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(65.432) == "00:01:05,432"
    assert parse_srt_time("01:02:03,004") == 3723.004


def test_subtitle_style_formats_ffmpeg_force_style() -> None:
    style = SubtitleStyle(
        font_name="Arial",
        font_size=12,
        primary_color="#ffffff",
        outline_color="#000000",
        border_style=1,
        outline=0.7,
        shadow=0,
        alignment="bottom_center",
        margin_vertical=20,
    )

    assert style.to_force_style() == (
        "Fontname=Arial,"
        "Fontsize=12,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=0.7,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=20"
    )


def test_subtitle_style_accepts_mapping_and_css_colors() -> None:
    assert (
        subtitle_style_to_force_style(
            {
                "font_size": 18,
                "primary_color": "#146348",
                "Bold": True,
                "alignment": "top_right",
            }
        )
        == "Fontsize=18,PrimaryColour=&H00486314,Bold=-1,Alignment=9"
    )


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
        "1\n" "00:00:00,000 --> 00:00:01,250\n" "First cue\n"
    )
