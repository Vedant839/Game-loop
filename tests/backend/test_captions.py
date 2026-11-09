import pytest

from backend.utils.captions import (
    CaptionParseError,
    TranscriptGapWarning,
    TranscriptValidationError,
    parse_srt,
    parse_vtt,
    validate_transcript,
)
from backend.schemas.lecture import TranscriptSegment


def test_srt_handles_bom_crlf_comma_dot_and_hour_timestamps():
    content = (
        "\ufeff1\r\n00:00:01,5 --> 00:00:02,500\r\nFirst cue\r\n\r\n"
        "2\r\n01:00:00.000 --> 01:00:01.25\r\nSecond cue"
    )

    segments = parse_srt(content, gap_warning_seconds=None)

    assert [(segment.start_time, segment.end_time, segment.text) for segment in segments] == [
        (1.5, 2.5, "First cue"),
        (3600.0, 3601.25, "Second cue"),
    ]


def test_vtt_drops_tags_and_cue_settings_and_unescapes_text():
    content = (
        "WEBVTT - Example\n\n"
        "cue-1\n00:01.000 --> 00:03.000 align:start position:10%\n"
        "<v Speaker><b>Hello</b> &amp; welcome</v>\n"
    )

    segments = parse_vtt(content)

    assert len(segments) == 1
    assert segments[0].start_time == 1.0
    assert segments[0].text == "Hello & welcome"


def test_empty_caption_cues_are_skipped():
    content = """WEBVTT

00:00.000 --> 00:01.000

00:01.000 --> 00:02.000
Visible cue
"""

    segments = parse_vtt(content)

    assert len(segments) == 1
    assert segments[0].text == "Visible cue"


def test_overlapping_caption_cues_are_rejected():
    content = """1
00:01,000 --> 00:03,000
First

2
00:02,500 --> 00:04,000
Overlap
"""

    with pytest.raises(TranscriptValidationError, match="overlap"):
        parse_srt(content)


def test_transcript_requires_monotonic_start_times():
    segments = [
        TranscriptSegment(start_time=5, end_time=6, text="later"),
        TranscriptSegment(start_time=1, end_time=2, text="earlier"),
    ]

    with pytest.raises(TranscriptValidationError, match="starts before"):
        validate_transcript(segments)


def test_large_gaps_emit_warnings_and_return_messages():
    segments = [
        TranscriptSegment(start_time=0, end_time=1, text="one"),
        TranscriptSegment(start_time=5, end_time=6, text="two"),
    ]

    with pytest.warns(TranscriptGapWarning, match="gap of 4.000s"):
        messages = validate_transcript(segments)

    assert len(messages) == 1


@pytest.mark.parametrize(
    "content, message",
    [
        ("1\nnot a timestamp\nText", "missing timing line"),
        ("1\n00:99:00,000 --> 00:99:01,000\nText", "below 60"),
        ("1\n00:00:02,000 --> 00:00:01,000\nText", "start time must be before end time"),
    ],
)
def test_malformed_srt_has_clear_errors(content: str, message: str):
    with pytest.raises(CaptionParseError, match=message):
        parse_srt(content)
