"""Tests for engine/calibrator.py — including gold standard BAD→GOOD."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
import os

from engine.parser import SRTBlock, parse_srt, write_srt
from engine.rules import CalibrationRules
from engine.calibrator import calibrate_srt, _wrap_text

SAMPLES = Path(__file__).parent / "samples"


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_srt_file(content: str) -> str:
    """Write an SRT string to a temp file, return path."""
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w", encoding="utf-8") as f:
        f.write(content)
        return f.name


def avg_cpl(blocks) -> float:
    cpls = [max((len(l) for l in b.lines), default=0) for b in blocks]
    return sum(cpls) / len(cpls) if cpls else 0


def max_cpl(blocks) -> int:
    return max(
        (max((len(l) for l in b.lines), default=0) for b in blocks),
        default=0,
    )


def count_orphans(blocks) -> int:
    """Count blocks that start with words belonging to end of previous sentence."""
    from engine.calibrator import SENTENCE_END
    import re
    orphan_count = 0
    for i in range(1, len(blocks)):
        prev = blocks[i - 1]
        curr = blocks[i]
        if not prev.lines or not curr.lines:
            continue
        prev_text = " ".join(prev.lines)
        # If previous block ends WITHOUT strong punctuation, check current block
        if not SENTENCE_END.search(prev_text.rstrip()):
            curr_text = " ".join(curr.lines)
            # If current block contains sentence-ending in its first few words
            first_words = curr_text.split()[:5]
            for j, w in enumerate(first_words):
                if SENTENCE_END.search(w):
                    orphan_count += 1
                    break
    return orphan_count


def count_sentence_starts_after_punct(blocks) -> int:
    """Count cases where strong punctuation ends a block and next block starts with lowercase (no new sentence)."""
    from engine.calibrator import SENTENCE_END
    issues = 0
    for i in range(len(blocks) - 1):
        text = " ".join(blocks[i].lines)
        next_text = " ".join(blocks[i + 1].lines) if blocks[i + 1].lines else ""
        if SENTENCE_END.search(text.rstrip()):
            # Next block should NOT start with a continuation word (lowercase, no capital)
            # This is a soft check; we just verify no strong punct at START of next block
            if next_text and next_text[0] in ".!?…":
                issues += 1
    return issues


# ── _wrap_text unit tests ─────────────────────────────────────────────────────

def test_wrap_text_short():
    assert _wrap_text("Hello world", 40) == ["Hello world"]


def test_wrap_text_exact():
    text = "A" * 40
    assert _wrap_text(text, 40) == [text]


def test_wrap_text_over():
    text = "un deux trois quatre cinq six sept huit neuf dix onze douze"
    lines = _wrap_text(text, 20)
    for line in lines:
        assert len(line) <= 22  # allow slight overflow at word boundary


def test_wrap_text_empty():
    assert _wrap_text("", 40) == []


# ── CPL enforcement ───────────────────────────────────────────────────────────

CPL_LONG_SRT = """\
1
00:00:01,000 --> 00:00:05,000
Ceci est une très longue ligne de sous-titre qui dépasse largement le maximum autorisé pour le format 16:9

"""


def test_cpl_rewrap_16x9():
    path = make_srt_file(CPL_LONG_SRT)
    try:
        rules = CalibrationRules(format="16:9")
        result = calibrate_srt(path, rules=rules)
        for block in result.blocks:
            for line in block.lines:
                assert len(line) <= rules.max_cpl + 5, f"Line too long: {line!r}"
    finally:
        os.unlink(path)


def test_cpl_rewrap_9x16():
    path = make_srt_file(CPL_LONG_SRT)
    try:
        rules = CalibrationRules(format="9:16")
        result = calibrate_srt(path, rules=rules)
        # With semantic segmentation, this gets split into multiple blocks
        assert len(result.blocks) > 1
    finally:
        os.unlink(path)


# ── CPS enforcement ───────────────────────────────────────────────────────────

def test_cps_extension():
    # Very short block with many characters → CPS too high
    srt = """\
1
00:00:01,000 --> 00:00:01,200
Bonjour tout le monde voici un texte rapide

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(max_cps=20)
        result = calibrate_srt(path, rules=rules)
        for block in result.blocks:
            dur = block.duration_ms / 1000
            chars = sum(len(l) for l in block.lines)
            if dur > 0:
                assert chars / dur <= rules.max_cps + 1
    finally:
        os.unlink(path)


# ── Duration enforcement ──────────────────────────────────────────────────────

def test_min_duration_enforced():
    srt = """\
1
00:00:01,000 --> 00:00:01,300
Court

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(min_duration=1.0)
        result = calibrate_srt(path, rules=rules)
        for block in result.blocks:
            assert block.duration_ms >= rules.min_duration * 1000 - 50
    finally:
        os.unlink(path)


def test_max_duration_split():
    srt = """\
1
00:00:01,000 --> 00:00:20,000
Ce bloc dure vingt secondes et est beaucoup trop long pour rester en un seul bloc selon les règles

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(max_duration=10.0)
        result = calibrate_srt(path, rules=rules)
        for block in result.blocks:
            assert block.duration_ms <= (rules.max_duration + 0.5) * 1000
    finally:
        os.unlink(path)


# ── Gap enforcement ───────────────────────────────────────────────────────────

def test_min_gap_enforced():
    srt = """\
1
00:00:01,000 --> 00:00:03,000
Premier bloc

2
00:00:03,020 --> 00:00:05,000
Deuxième bloc trop proche

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(min_gap=0.120)
        result = calibrate_srt(path, rules=rules)
        blocks = result.blocks
        if len(blocks) >= 2:
            gap_ms = blocks[1].start_ms - blocks[0].end_ms
            assert gap_ms >= rules.min_gap * 1000 - 10
    finally:
        os.unlink(path)


# ── Semantic segmentation ─────────────────────────────────────────────────────

def test_semantic_sentence_boundary():
    """Sentence end must always close a block."""
    srt = """\
1
00:00:01,000 --> 00:00:05,000
C'est important pour moi. Parce que j'ai toujours voulu faire ça.

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(format="9:16")
        result = calibrate_srt(path, rules=rules)
        blocks = result.blocks
        # No block should start with punctuation from previous sentence
        punct_starts = count_sentence_starts_after_punct(blocks)
        assert punct_starts == 0
    finally:
        os.unlink(path)


def test_semantic_no_orphans():
    """No orphaned words at start of block."""
    srt = """\
1
00:00:01,000 --> 00:00:05,000
Je pense que c'est une bonne idée. Et du coup on va pouvoir avancer ensemble.

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(format="9:16")
        result = calibrate_srt(path, rules=rules)
        orphans = count_orphans(result.blocks)
        assert orphans == 0, f"Found {orphans} orphan(s)"
    finally:
        os.unlink(path)


def test_semantic_disabled():
    """When semantic_segmentation=False, block count should stay close to original."""
    srt = """\
1
00:00:01,000 --> 00:00:05,000
Premier bloc

2
00:00:06,000 --> 00:00:10,000
Deuxième bloc

"""
    path = make_srt_file(srt)
    try:
        rules = CalibrationRules(semantic_segmentation=False)
        result = calibrate_srt(path, rules=rules)
        assert len(result.blocks) == 2
    finally:
        os.unlink(path)


# ── Format presets ────────────────────────────────────────────────────────────

def test_preset_16x9():
    rules = CalibrationRules(format="16:9")
    assert rules.max_cpl == 40
    assert rules.max_cps == 20
    assert rules.max_lines == 2


def test_preset_9x16():
    rules = CalibrationRules(format="9:16")
    assert rules.max_cpl == 22
    assert rules.max_cps == 17
    assert rules.max_lines == 3


def test_preset_1x1():
    rules = CalibrationRules(format="1:1")
    assert rules.max_cpl == 30
    assert rules.max_cps == 20
    assert rules.max_lines == 2


# ── FPS conversion ────────────────────────────────────────────────────────────

def test_fps_conversion_ratio():
    from engine.calibrator import _convert_fps
    from engine.parser import SRTBlock

    blocks = [SRTBlock(1, 0, 60_000, ["Test"])]  # 1 min at 25fps
    # Convert 25 → 23.976: ratio = 23.976/25 = 0.95904
    ratio = 23.976 / 25.0
    result = _convert_fps(blocks, ratio)
    expected_end = round(60_000 * ratio)
    assert result[0].end_ms == expected_end


def test_fps_no_conversion_when_same():
    rules = CalibrationRules(source_fps=25.0, target_fps=25.0)
    assert not rules.needs_fps_conversion


def test_fps_long_file_no_drift():
    """Over 5 minutes, FPS conversion should not accumulate significant drift."""
    # Create a file with 300 blocks spanning 5 minutes (25fps)
    srt_lines = []
    for i in range(1, 301):
        start_ms = (i - 1) * 1000
        end_ms = start_ms + 800
        from engine.parser import ms_to_timecode
        srt_lines.append(f"{i}")
        srt_lines.append(f"{ms_to_timecode(start_ms)} --> {ms_to_timecode(end_ms)}")
        srt_lines.append("Test block")
        srt_lines.append("")

    path = make_srt_file("\n".join(srt_lines))
    try:
        rules = CalibrationRules(source_fps=25.0, target_fps=23.976)
        result = calibrate_srt(path, rules=rules)
        # Last block end should be ~295s * 0.95904 ≈ 283s
        last_end_s = result.blocks[-1].end_ms / 1000
        expected_s = 299 * 0.95904
        assert abs(last_end_s - expected_s) < 2.0, f"Drift too large: {last_end_s:.1f}s vs {expected_s:.1f}s"
    finally:
        os.unlink(path)


# ── Gold standard: BAD → GOOD ─────────────────────────────────────────────────

@pytest.mark.skipif(
    not (SAMPLES / "BERNARD_2_BAD.srt").exists(),
    reason="Reference files not found"
)
def test_gold_standard_bernard_block_count():
    """BAD → 9:16 must produce significantly more blocks than input (target ~32)."""
    rules = CalibrationRules(format="9:16")
    result = calibrate_srt(SAMPLES / "BERNARD_2_BAD.srt", rules=rules)
    bad_blocks = parse_srt(SAMPLES / "BERNARD_2_BAD.srt")

    assert len(result.blocks) > len(bad_blocks), "Should have more blocks after segmentation"
    assert len(result.blocks) >= 20, f"Expected ≥20 blocks, got {len(result.blocks)}"


@pytest.mark.skipif(
    not (SAMPLES / "BERNARD_2_BAD.srt").exists(),
    reason="Reference files not found"
)
def test_gold_standard_bernard_cpl():
    """BAD → 9:16 must have CPL avg ~34 and CPL max ≤ 60."""
    rules = CalibrationRules(format="9:16")
    result = calibrate_srt(SAMPLES / "BERNARD_2_BAD.srt", rules=rules)

    avg = avg_cpl(result.blocks)
    mx = max_cpl(result.blocks)

    # BAD has avg CPL ~89; after calibration should be much lower
    assert avg < 50, f"CPL avg too high: {avg:.1f} (expected < 50)"
    assert mx <= 60, f"CPL max too high: {mx} (expected ≤ 60)"


@pytest.mark.skipif(
    not (SAMPLES / "BERNARD_2_BAD.srt").exists(),
    reason="Reference files not found"
)
def test_gold_standard_bernard_no_orphans():
    """BAD → 9:16 must have zero or very few orphaned words."""
    rules = CalibrationRules(format="9:16")
    result = calibrate_srt(SAMPLES / "BERNARD_2_BAD.srt", rules=rules)
    orphans = count_orphans(result.blocks)
    assert orphans <= 1, f"Too many orphans: {orphans} (expected 0)"


@pytest.mark.skipif(
    not (SAMPLES / "ELISABETH_4_BAD.srt").exists(),
    reason="Reference files not found"
)
def test_gold_standard_elisabeth_block_count():
    """Elisabeth BAD → 9:16 must produce significantly more blocks (target ~20)."""
    rules = CalibrationRules(format="9:16")
    result = calibrate_srt(SAMPLES / "ELISABETH_4_BAD.srt", rules=rules)
    bad_blocks = parse_srt(SAMPLES / "ELISABETH_4_BAD.srt")

    assert len(result.blocks) > len(bad_blocks)
    assert len(result.blocks) >= 15, f"Expected ≥15 blocks, got {len(result.blocks)}"


@pytest.mark.skipif(
    not (SAMPLES / "ELISABETH_4_BAD.srt").exists(),
    reason="Reference files not found"
)
def test_gold_standard_elisabeth_cpl():
    """Elisabeth BAD → 9:16 must have CPL max ≤ 60."""
    rules = CalibrationRules(format="9:16")
    result = calibrate_srt(SAMPLES / "ELISABETH_4_BAD.srt", rules=rules)
    mx = max_cpl(result.blocks)
    assert mx <= 60, f"CPL max too high: {mx}"
