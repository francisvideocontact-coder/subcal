"""Tests for engine/parser.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
import os

from engine.parser import (
    SRTBlock,
    parse_srt,
    write_srt,
    timecode_to_ms,
    ms_to_timecode,
)

SAMPLES = Path(__file__).parent / "samples"


# ── Timecode helpers ──────────────────────────────────────────────────────────

def test_timecode_to_ms_basic():
    assert timecode_to_ms("00:00:01,000") == 1000
    assert timecode_to_ms("00:01:00,000") == 60_000
    assert timecode_to_ms("01:00:00,000") == 3_600_000
    assert timecode_to_ms("00:00:00,500") == 500


def test_timecode_to_ms_decimal_separator():
    # Some SRT files use '.' instead of ','
    assert timecode_to_ms("00:00:01.500") == 1500


def test_ms_to_timecode_basic():
    assert ms_to_timecode(1000) == "00:00:01,000"
    assert ms_to_timecode(60_000) == "00:01:00,000"
    assert ms_to_timecode(3_600_000) == "01:00:00,000"
    assert ms_to_timecode(500) == "00:00:00,500"


def test_ms_to_timecode_roundtrip():
    for ms in [0, 500, 1234, 59_999, 60_000, 3_599_000, 3_661_234]:
        assert timecode_to_ms(ms_to_timecode(ms)) == ms


def test_ms_to_timecode_negative_clamped():
    assert ms_to_timecode(-100) == "00:00:00,000"


# ── Parse SRT ─────────────────────────────────────────────────────────────────

SRT_SIMPLE = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
Second block

"""

SRT_WITH_HTML = """\
1
00:00:01,000 --> 00:00:03,000
<b>Bold text</b>

"""

SRT_CRLF = "1\r\n00:00:01,000 --> 00:00:03,000\r\nHello\r\n\r\n"

SRT_BOM = b"\xef\xbb\xbf1\n00:00:01,000 --> 00:00:03,000\nBOM test\n\n"

SRT_INCOHERENT = """\
1
00:00:05,000 --> 00:00:02,000
Bad timecodes

"""


def _write_temp_srt(content: str | bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="wb") as f:
        if isinstance(content, str):
            f.write(content.encode("utf-8"))
        else:
            f.write(content)
        return f.name


def test_parse_simple():
    path = _write_temp_srt(SRT_SIMPLE)
    try:
        blocks = parse_srt(path)
        assert len(blocks) == 2
        assert blocks[0].index == 1
        assert blocks[0].start_ms == 1000
        assert blocks[0].end_ms == 3000
        assert blocks[0].lines == ["Hello world"]
        assert blocks[1].lines == ["Second block"]
    finally:
        os.unlink(path)


def test_parse_strips_html_tags():
    path = _write_temp_srt(SRT_WITH_HTML)
    try:
        blocks = parse_srt(path)
        assert blocks[0].lines == ["Bold text"]
    finally:
        os.unlink(path)


def test_parse_crlf():
    path = _write_temp_srt(SRT_CRLF)
    try:
        blocks = parse_srt(path)
        assert len(blocks) == 1
        assert blocks[0].lines == ["Hello"]
    finally:
        os.unlink(path)


def test_parse_utf8_bom():
    path = _write_temp_srt(SRT_BOM)
    try:
        blocks = parse_srt(path)
        assert len(blocks) == 1
        assert blocks[0].lines == ["BOM test"]
    finally:
        os.unlink(path)


def test_parse_incoherent_timecodes():
    """End < start: parser should fix it (end = start + 1000)."""
    path = _write_temp_srt(SRT_INCOHERENT)
    try:
        blocks = parse_srt(path)
        assert len(blocks) == 1
        assert blocks[0].end_ms > blocks[0].start_ms
    finally:
        os.unlink(path)


def test_parse_renumbers_sequentially():
    srt = "5\n00:00:01,000 --> 00:00:02,000\nA\n\n10\n00:00:03,000 --> 00:00:04,000\nB\n\n"
    path = _write_temp_srt(srt)
    try:
        blocks = parse_srt(path)
        assert [b.index for b in blocks] == [1, 2]
    finally:
        os.unlink(path)


def test_parse_empty_file():
    path = _write_temp_srt("")
    try:
        blocks = parse_srt(path)
        assert blocks == []
    finally:
        os.unlink(path)


def test_parse_reference_bad_files():
    """Reference BAD files must be parseable."""
    for name in ["BERNARD_2_BAD.srt", "ELISABETH_4_BAD.srt"]:
        f = SAMPLES / name
        if f.exists():
            blocks = parse_srt(f)
            assert len(blocks) > 0, f"No blocks in {name}"


# ── Write SRT ─────────────────────────────────────────────────────────────────

def test_write_roundtrip():
    blocks = [
        SRTBlock(1, 1000, 3000, ["Hello world"]),
        SRTBlock(2, 4000, 6000, ["Second line"]),
    ]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
        path = f.name
    try:
        write_srt(blocks, path)
        parsed = parse_srt(path)
        assert len(parsed) == 2
        assert parsed[0].lines == ["Hello world"]
        assert parsed[1].start_ms == 4000
    finally:
        os.unlink(path)


def test_write_utf8_no_bom():
    blocks = [SRTBlock(1, 0, 1000, ["café naïf"])]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
        path = f.name
    try:
        write_srt(blocks, path)
        raw = Path(path).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert "café naïf".encode("utf-8") in raw
    finally:
        os.unlink(path)
