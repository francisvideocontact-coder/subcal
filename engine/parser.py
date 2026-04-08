"""
SRT parser and writer.
Supports UTF-8 / UTF-8 BOM, CRLF / LF.
Exports UTF-8 without BOM, LF line endings, sequential block numbering.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class SRTBlock:
    index: int
    start_ms: int   # milliseconds
    end_ms: int     # milliseconds
    lines: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def copy(self) -> "SRTBlock":
        return SRTBlock(
            index=self.index,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            lines=list(self.lines),
        )

    def __repr__(self) -> str:
        return (
            f"SRTBlock({self.index}, "
            f"{ms_to_timecode(self.start_ms)} --> {ms_to_timecode(self.end_ms)}, "
            f"{self.lines!r})"
        )


# ── Timecode helpers ──────────────────────────────────────────────────────────

_TC_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def timecode_to_ms(tc: str) -> int:
    """Convert SRT timecode (HH:MM:SS,mmm) to milliseconds."""
    m = _TC_RE.match(tc.strip())
    if not m:
        raise ValueError(f"Invalid timecode: {tc!r}")
    h, mn, s, ms = (int(x) for x in m.groups())
    return h * 3_600_000 + mn * 60_000 + s * 1_000 + ms


def ms_to_timecode(ms: int) -> str:
    """Convert milliseconds to SRT timecode (HH:MM:SS,mmm)."""
    ms = max(0, ms)
    h = ms // 3_600_000
    ms %= 3_600_000
    mn = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{mn:02d}:{s:02d},{ms:03d}"


# ── Parser ────────────────────────────────────────────────────────────────────

_ARROW_RE = re.compile(r"--\s*>")


def parse_srt(path: str | Path) -> List[SRTBlock]:
    """Parse an SRT file and return a list of SRTBlock."""
    raw = Path(path).read_bytes()

    # Decode: try UTF-8 BOM first, then UTF-8, then latin-1 fallback
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1", errors="replace")

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    blocks: List[SRTBlock] = []
    # Split on blank lines separating blocks
    for chunk in re.split(r"\n{2,}", text.strip()):
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        # First non-empty line: block index
        idx_line = lines[0].strip()
        if not idx_line.isdigit():
            continue
        index = int(idx_line)

        if len(lines) < 2:
            continue

        # Second line: timecodes
        tc_line = lines[1].strip()
        parts = _ARROW_RE.split(tc_line)
        if len(parts) != 2:
            continue
        try:
            start_ms = timecode_to_ms(parts[0])
            end_ms = timecode_to_ms(parts[1])
        except ValueError:
            continue

        # Remaining lines: subtitle text (strip HTML-like tags)
        text_lines = [_strip_tags(l.strip()) for l in lines[2:] if l.strip()]

        if end_ms <= start_ms:
            # Attempt to fix incoherent timecodes: set end = start + 1000ms
            end_ms = start_ms + 1000

        blocks.append(SRTBlock(index=index, start_ms=start_ms, end_ms=end_ms, lines=text_lines))

    # Renumber sequentially
    for i, b in enumerate(blocks, 1):
        b.index = i

    return blocks


def _strip_tags(text: str) -> str:
    """Remove basic HTML/SRT formatting tags."""
    return re.sub(r"<[^>]+>", "", text)


# ── Writer ────────────────────────────────────────────────────────────────────

def write_srt(blocks: List[SRTBlock], path: str | Path) -> None:
    """Write blocks to an SRT file (UTF-8 without BOM, LF endings)."""
    lines = []
    for i, block in enumerate(blocks, 1):
        lines.append(str(i))
        lines.append(f"{ms_to_timecode(block.start_ms)} --> {ms_to_timecode(block.end_ms)}")
        for text_line in block.lines:
            lines.append(text_line)
        lines.append("")  # blank line separator
    Path(path).write_text("\n".join(lines), encoding="utf-8")
