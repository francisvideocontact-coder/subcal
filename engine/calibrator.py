"""
SRT recalibration engine — 3-pass algorithm.

Pass 1 — Merge: flatten all blocks into a word stream with interpolated timecodes.
Pass 2 — Semantic segmentation: re-cut by meaning units (sentences, syntactic groups).
Pass 3 — Technical adjustment: enforce CPL, CPS, min/max duration, min gap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .parser import SRTBlock, parse_srt, write_srt, ms_to_timecode
from .rules import CalibrationRules


# ── French linguistic constants ───────────────────────────────────────────────

# Sentence-ending punctuation
SENTENCE_END = re.compile(r"[.!?…]+$")
SENTENCE_END_IN = re.compile(r"[.!?…]+")

# Coordinating conjunctions (cut before these)
COORD_CONJ = {"et", "ou", "mais", "donc", "car", "ni", "or"}

# Subordinating conjunctions (cut before these)
SUB_CONJ = {
    "que", "qui", "quand", "lorsque", "puisque", "parce", "comme",
    "si", "quoique", "bien", "alors", "depuis", "pendant", "avant",
    "après", "jusqu", "pour", "afin",
}

# Prepositions (cut before these)
PREPOSITIONS = {
    "de", "à", "en", "dans", "sur", "pour", "avec", "par", "sans",
    "chez", "entre", "vers", "contre", "depuis", "pendant", "durant",
    "lors", "via", "selon", "malgré",
}

# Articles / determiners — NEVER separate from following noun
ARTICLES = {"le", "la", "les", "un", "une", "des", "l", "d", "du", "aux"}

# Short adjectives that must stay with their noun
SHORT_ADJ = {
    "bon", "bonne", "bons", "bonnes", "grand", "grande", "grands", "grandes",
    "petit", "petite", "petits", "petites", "gros", "grosse", "gros",
    "vieux", "vieille", "vieux", "vieilles", "beau", "belle", "beaux",
    "belles", "nouveau", "nouvelle", "nouveaux", "nouvelles",
    "même", "seul", "seule", "autre", "tel", "telle",
}

# Auxiliaries — NEVER separate from following participle
AUXILIARIES = {"a", "ai", "as", "avons", "avez", "ont", "est", "es",
               "sommes", "êtes", "sont", "était", "avait", "sera",
               "serait", "aurait", "aura"}

# Negation particles
NEGATION = {"ne", "n"}


# ── Word with timecode ────────────────────────────────────────────────────────

@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int


# ── Calibration result ────────────────────────────────────────────────────────

@dataclass
class CalibrationResult:
    blocks: List[SRTBlock]
    original_count: int
    recalibrated_count: int
    split_count: int
    errors: List[str] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        write_srt(self.blocks, path)

    @property
    def report(self) -> str:
        return (
            f"{self.original_count} blocs traités, "
            f"{self.recalibrated_count} recalibrés, "
            f"{self.split_count} splittés, "
            f"{len(self.errors)} erreur(s)"
        )


# ── Main entry point ──────────────────────────────────────────────────────────

def calibrate_srt(
    path: str | Path,
    rules: Optional[CalibrationRules] = None,
) -> CalibrationResult:
    """Calibrate an SRT file and return a CalibrationResult."""
    if rules is None:
        rules = CalibrationRules()

    blocks = parse_srt(path)
    original_count = len(blocks)
    errors: List[str] = []

    if not blocks:
        return CalibrationResult([], 0, 0, 0, ["Empty file"])

    # Pass 0 — FPS conversion
    if rules.needs_fps_conversion:
        blocks = _convert_fps(blocks, rules.fps_ratio)

    # Pass 1 — Merge into word stream
    words = _merge_to_words(blocks)

    # Pass 2 — Semantic segmentation (or keep original segmentation)
    if rules.semantic_segmentation:
        segments = _semantic_segment(words, rules)
    else:
        segments = _words_to_segments_original(words, blocks)

    # Pass 3 — Technical adjustment
    calibrated, recal_count, split_count = _technical_adjust(segments, rules, errors)

    # Renumber
    for i, b in enumerate(calibrated, 1):
        b.index = i

    return CalibrationResult(
        blocks=calibrated,
        original_count=original_count,
        recalibrated_count=recal_count,
        split_count=split_count,
        errors=errors,
    )


# ── Pass 0: FPS conversion ────────────────────────────────────────────────────

def _convert_fps(blocks: List[SRTBlock], ratio: float) -> List[SRTBlock]:
    result = []
    for b in blocks:
        nb = b.copy()
        nb.start_ms = round(b.start_ms * ratio)
        nb.end_ms = round(b.end_ms * ratio)
        result.append(nb)
    return result


# ── Pass 1: Merge to word stream ──────────────────────────────────────────────

def _merge_to_words(blocks: List[SRTBlock]) -> List[Word]:
    """Flatten all blocks into a list of Words with interpolated timecodes."""
    words: List[Word] = []
    for block in blocks:
        text = " ".join(block.lines)
        tokens = text.split()
        if not tokens:
            continue
        duration = block.end_ms - block.start_ms
        n = len(tokens)
        for i, token in enumerate(tokens):
            # Proportional interpolation
            w_start = block.start_ms + round(i * duration / n)
            w_end = block.start_ms + round((i + 1) * duration / n)
            words.append(Word(text=token, start_ms=w_start, end_ms=w_end))
    return words


# ── Pass 2: Semantic segmentation ────────────────────────────────────────────

def _semantic_segment(words: List[Word], rules: CalibrationRules) -> List[SRTBlock]:
    """
    Re-segment the word stream into semantically coherent blocks.

    Strategy:
    1. Detect sentence boundaries (strong punctuation).
    2. Each sentence becomes 1+ blocks.
    3. If a sentence fits in 1 block (CPL & duration), keep as one.
    4. Otherwise, cut at natural articulation points.
    5. Reattach orphaned words (end-of-sentence words stranded at block start).
    """
    if not words:
        return []

    # Step 1: identify sentences (sequences ending with strong punctuation)
    sentences: List[List[Word]] = []
    current: List[Word] = []
    for word in words:
        current.append(word)
        if SENTENCE_END.search(word.text):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)

    # Step 2: segment each sentence into blocks
    raw_blocks: List[List[Word]] = []
    for sentence in sentences:
        raw_blocks.extend(_segment_sentence(sentence, rules))

    # Step 3: orphan reattachment
    raw_blocks = _reattach_orphans(raw_blocks, rules)

    # Step 4: convert word groups → SRTBlocks
    blocks = []
    for idx, group in enumerate(raw_blocks, 1):
        if not group:
            continue
        block_text = " ".join(w.text for w in group)
        lines = _wrap_text(block_text, rules.max_cpl)
        blocks.append(SRTBlock(
            index=idx,
            start_ms=group[0].start_ms,
            end_ms=group[-1].end_ms,
            lines=lines,
        ))

    return blocks


def _segment_sentence(sentence: List[Word], rules: CalibrationRules) -> List[List[Word]]:
    """Split a sentence into 1+ word groups respecting max CPL AND max_lines."""
    if not sentence:
        return []

    text = " ".join(w.text for w in sentence)
    lines = _wrap_text(text, rules.max_cpl)

    # If fits in one block (both CPL and line count), keep it
    if len(lines) <= rules.max_lines:
        return [sentence]

    # Need to split — find best cut point respecting max_lines
    segments: List[List[Word]] = []
    remaining = list(sentence)

    while remaining:
        cut = _find_cut_point(remaining, rules.max_cpl, rules.max_lines)
        segments.append(remaining[:cut])
        remaining = remaining[cut:]

    return segments


def _find_cut_point(words: List[Word], max_cpl: int, max_lines: int = 1) -> int:
    """
    Find the best cut index (exclusive) for a list of words such that the
    resulting text fits in max_lines lines of max_cpl characters each.
    Returns an index between 1 and len(words).
    """
    # Find the maximum number of words whose wrapped text fits in max_lines lines
    max_fit = 0
    for i in range(1, len(words) + 1):
        candidate_text = " ".join(w.text for w in words[:i])
        candidate_lines = _wrap_text(candidate_text, max_cpl)
        if len(candidate_lines) <= max_lines:
            max_fit = i
        else:
            break

    if max_fit == 0:
        # Even a single word needs more lines — keep it anyway
        return 1

    if max_fit >= len(words):
        return len(words)

    # Among words[0:max_fit], find the best semantic cut (rightmost preferred)
    # Priority: punctuation → coord conj → sub conj → preposition → midpoint
    best = _best_semantic_cut(words, max_fit)
    return best


def _best_semantic_cut(words: List[Word], max_fit: int) -> int:
    """
    Find the best cut position in words[0:max_fit].
    Scans from right to left for semantic break points.
    """
    # 1. After punctuation (not sentence-ending — those end blocks)
    for i in range(max_fit - 1, 0, -1):
        if re.search(r"[,;:]$", words[i].text):
            # Don't break if next word is an article or aux
            if i + 1 < len(words) and _is_bound_to_next(words, i + 1):
                continue
            return i + 1

    # 2. Before coordinating conjunction
    for i in range(max_fit - 1, 0, -1):
        w = _clean_word(words[i].text)
        if w in COORD_CONJ:
            if not _is_bound_to_next(words, i):
                return i

    # 3. Before subordinating conjunction
    for i in range(max_fit - 1, 0, -1):
        w = _clean_word(words[i].text)
        if w in SUB_CONJ:
            if not _is_bound_to_next(words, i):
                return i

    # 4. Before preposition
    for i in range(max_fit - 1, 0, -1):
        w = _clean_word(words[i].text)
        if w in PREPOSITIONS:
            if not _is_bound_to_next(words, i):
                return i

    # 5. Balanced midpoint (avoid breaking indissociable groups)
    mid = max_fit // 2
    # Scan around midpoint for a safe cut
    for offset in range(0, mid):
        for candidate in (mid + offset, mid - offset):
            if 1 <= candidate <= max_fit:
                if not _is_bound_to_next(words, candidate):
                    return candidate

    return max_fit


def _is_bound_to_next(words: List[Word], idx: int) -> bool:
    """Return True if words[idx] must not be separated from words[idx-1]."""
    if idx <= 0 or idx >= len(words):
        return False
    prev = _clean_word(words[idx - 1].text)
    curr = _clean_word(words[idx].text)

    # Article/determiner before noun
    if prev in ARTICLES:
        return True
    # Short adjective before noun (keep together)
    if prev in SHORT_ADJ:
        return True
    # Auxiliary before participle
    if prev in AUXILIARIES:
        return True
    # Negation: "ne" before verb/pas
    if prev in NEGATION:
        return True
    return False


def _clean_word(w: str) -> str:
    """Lowercase and strip punctuation for comparison."""
    return re.sub(r"[^a-zàâäéèêëîïôùûüç']", "", w.lower())


def _max_cpl_of_text(text: str, max_cpl: int) -> int:
    """Return the CPL of the longest line if text were wrapped at max_cpl."""
    lines = _wrap_text(text, max_cpl)
    if not lines:
        return 0
    return max(len(l) for l in lines)


def _wrap_text(text: str, max_cpl: int) -> List[str]:
    """
    Wrap text into lines of at most max_cpl characters.
    Respects French cut-point priority: punctuation → conjunctions → prepositions → articles → midpoint.
    Returns a list of line strings.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_cpl:
        return [text]

    words = text.split()
    lines = []
    current = ""

    for i, word in enumerate(words):
        candidate = (current + " " + word).strip()
        if len(candidate) <= max_cpl:
            current = candidate
        else:
            if current:
                lines.append(current)
                current = word
            else:
                # Word alone exceeds max_cpl — keep it
                lines.append(word)
                current = ""

    if current:
        lines.append(current)

    return lines if lines else [text]


def _reattach_orphans(
    raw_blocks: List[List[Word]],
    rules: CalibrationRules,
) -> List[List[Word]]:
    """
    Reattach orphaned words: if a block starts with ≤ orphan_threshold words
    that belong to the END of the previous sentence (i.e., they follow a
    sentence-ending punctuation found in the previous block), move them back.

    Also ensures no strong punctuation appears at the START of a block
    (it should end the previous block).
    """
    if len(raw_blocks) < 2:
        return raw_blocks

    result = [list(raw_blocks[0])]

    for block in raw_blocks[1:]:
        if not block or not result:
            result.append(list(block))
            continue

        prev = result[-1]

        # Check if this block STARTS with the tail of a sentence
        # (i.e., the previous block ended mid-sentence or prev block's last word
        # had no sentence-ending punctuation but current block starts with punctuation)
        orphan_count = _count_orphan_words(block)

        if 0 < orphan_count <= rules.orphan_threshold and len(prev) > 0:
            # Move orphan words from start of current block to end of previous block
            result[-1] = prev + block[:orphan_count]
            result.append(list(block[orphan_count:]))
        else:
            result.append(list(block))

    # Remove empty blocks
    return [b for b in result if b]


def _count_orphan_words(block: List[Word]) -> int:
    """
    Count how many words at the start of this block are orphans from
    the previous sentence: words that precede the first sentence-ending
    punctuation in this block (if any).
    """
    for i, word in enumerate(block):
        if SENTENCE_END.search(word.text):
            return i + 1  # includes the punctuation-bearing word
    return 0  # No sentence end found = this block is all one sentence


def _words_to_segments_original(
    words: List[Word],
    original_blocks: List[SRTBlock],
) -> List[SRTBlock]:
    """Reconstruct blocks from words using original block boundaries (no semantic segmentation)."""
    # Map words back to original blocks by timecode ranges
    result = []
    word_idx = 0
    for block in original_blocks:
        group = []
        while word_idx < len(words) and words[word_idx].start_ms < block.end_ms:
            group.append(words[word_idx])
            word_idx += 1
        if group:
            text = " ".join(w.text for w in group)
            lines = _wrap_text(text, 9999)  # no CPL enforcement here
            result.append(SRTBlock(
                index=block.index,
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                lines=lines,
            ))
    return result


# ── Pass 3: Technical adjustment ─────────────────────────────────────────────

def _technical_adjust(
    blocks: List[SRTBlock],
    rules: CalibrationRules,
    errors: List[str],
) -> Tuple[List[SRTBlock], int, int]:
    """
    Apply CPL, CPS, min/max duration, min gap rules.
    Returns (adjusted_blocks, recalibrated_count, split_count).
    """
    recal = 0
    splits = 0
    result: List[SRTBlock] = []

    for block in blocks:
        modified = False
        text = " ".join(block.lines)

        if not text.strip():
            continue  # drop empty blocks

        # 1. Re-wrap for CPL
        lines = _wrap_text(text, rules.max_cpl)

        # If too many lines: split the block into sub-blocks (never compress)
        if len(lines) > rules.max_lines:
            sub_blocks = _split_block_to_lines(block, rules)
            result.extend(sub_blocks)
            splits += len(sub_blocks) - 1
            recal += 1
            continue

        if lines != block.lines:
            block = SRTBlock(block.index, block.start_ms, block.end_ms, lines)
            modified = True

        # 2. Enforce min duration
        dur_s = block.duration_ms / 1000
        if dur_s < rules.min_duration:
            block = SRTBlock(
                block.index,
                block.start_ms,
                block.start_ms + round(rules.min_duration * 1000),
                block.lines,
            )
            modified = True

        # 3. Enforce max duration → split
        dur_s = block.duration_ms / 1000
        if dur_s > rules.max_duration:
            split_blocks = _split_block(block, rules)
            result.extend(split_blocks)
            splits += len(split_blocks) - 1
            recal += 1
            continue

        # 4. Check CPS
        char_count = sum(len(l) for l in block.lines)
        cps = char_count / (block.duration_ms / 1000) if block.duration_ms > 0 else 0
        if cps > rules.max_cps:
            # Extend duration
            needed_ms = round(char_count / rules.max_cps * 1000)
            block = SRTBlock(block.index, block.start_ms, block.start_ms + needed_ms, block.lines)
            modified = True

        if modified:
            recal += 1

        result.append(block)

    # 5. Enforce min gap and resolve overlaps
    result = _fix_gaps_and_overlaps(result, rules)

    return result, recal, splits


def _split_block_to_lines(block: SRTBlock, rules: CalibrationRules) -> List[SRTBlock]:
    """
    Split a block whose wrapped text exceeds max_lines into multiple blocks,
    each fitting within max_lines lines at max_cpl.
    Timecodes are distributed proportionally by word count.
    """
    text = " ".join(block.lines)
    word_tokens = text.split()
    if not word_tokens:
        return [block]

    total_words = len(word_tokens)
    duration = block.end_ms - block.start_ms
    result_blocks = []
    start_idx = 0

    while start_idx < total_words:
        # Find the maximum words that fit in max_lines at max_cpl
        max_fit = 0
        for i in range(start_idx + 1, total_words + 1):
            candidate = " ".join(word_tokens[start_idx:i])
            if len(_wrap_text(candidate, rules.max_cpl)) <= rules.max_lines:
                max_fit = i - start_idx
            else:
                break
        if max_fit == 0:
            max_fit = 1  # at minimum take one word

        # Avoid creating a tiny orphan tail: if the remaining words after this
        # chunk are ≤ orphan_threshold AND the last word of the block ends a
        # sentence, try to absorb them into the current chunk (strict max_lines).
        remaining_after = total_words - (start_idx + max_fit)
        if 0 < remaining_after <= rules.orphan_threshold:
            last_word = word_tokens[-1]
            if SENTENCE_END.search(last_word):
                all_candidate = " ".join(word_tokens[start_idx:])
                if len(_wrap_text(all_candidate, rules.max_cpl)) <= rules.max_lines:
                    max_fit = total_words - start_idx

        chunk = word_tokens[start_idx:start_idx + max_fit]
        chunk_text = " ".join(chunk)
        chunk_lines = _wrap_text(chunk_text, rules.max_cpl)

        # Proportional timecodes
        chunk_start_ms = block.start_ms + round(start_idx * duration / total_words)
        chunk_end_ms = block.start_ms + round((start_idx + max_fit) * duration / total_words)

        result_blocks.append(SRTBlock(
            index=block.index,
            start_ms=chunk_start_ms,
            end_ms=chunk_end_ms,
            lines=chunk_lines,
        ))
        start_idx += max_fit

    return result_blocks if result_blocks else [block]


def _split_block(block: SRTBlock, rules: CalibrationRules) -> List[SRTBlock]:
    """Split an overly long block (duration) into 2 blocks at the midpoint."""
    text = " ".join(block.lines)
    words_list = text.split()
    if len(words_list) <= 1:
        return [block]

    mid = len(words_list) // 2
    mid_ms = block.start_ms + (block.end_ms - block.start_ms) // 2

    text1 = " ".join(words_list[:mid])
    text2 = " ".join(words_list[mid:])

    return [
        SRTBlock(block.index, block.start_ms, mid_ms, _wrap_text(text1, rules.max_cpl)),
        SRTBlock(block.index + 1, mid_ms, block.end_ms, _wrap_text(text2, rules.max_cpl)),
    ]


def _fix_gaps_and_overlaps(
    blocks: List[SRTBlock],
    rules: CalibrationRules,
) -> List[SRTBlock]:
    """Ensure min gap between consecutive blocks and no overlaps."""
    if len(blocks) < 2:
        return blocks

    min_gap_ms = round(rules.min_gap * 1000)
    result = [blocks[0].copy()]

    for i in range(1, len(blocks)):
        prev = result[-1]
        curr = blocks[i].copy()

        # Resolve overlap
        if curr.start_ms < prev.end_ms:
            # Shrink previous block end
            prev.end_ms = curr.start_ms - min_gap_ms
            if prev.end_ms < prev.start_ms:
                prev.end_ms = prev.start_ms + 100  # minimal 100ms

        # Enforce min gap
        gap_ms = curr.start_ms - prev.end_ms
        if 0 < gap_ms < min_gap_ms:
            prev.end_ms = curr.start_ms - min_gap_ms

        result.append(curr)

    return result
