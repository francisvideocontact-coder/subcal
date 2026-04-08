"""
Calibration rules and format presets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Format presets ────────────────────────────────────────────────────────────

_PRESETS = {
    "16:9": dict(max_cpl=40, max_cps=20, max_lines=2),
    "9:16": dict(max_cpl=22, max_cps=17, max_lines=3),
    "1:1":  dict(max_cpl=30, max_cps=20, max_lines=2),
}

VALID_FORMATS = list(_PRESETS.keys())


@dataclass
class CalibrationRules:
    # Format preset (loads CPL/CPS/max_lines automatically)
    format: Optional[str] = None          # "16:9", "9:16", "1:1"

    # Characters per line
    max_cpl: int = 40

    # Characters per second
    max_cps: float = 20.0

    # Lines per block
    max_lines: int = 2

    # Duration (seconds)
    min_duration: float = 1.0
    max_duration: float = 10.0

    # Gap between consecutive blocks (seconds)
    min_gap: float = 0.120

    # Framerate conversion
    source_fps: Optional[float] = None
    target_fps: Optional[float] = None

    # Semantic segmentation
    semantic_segmentation: bool = True
    orphan_threshold: int = 4             # max orphan words to reattach

    def __post_init__(self) -> None:
        if self.format is not None:
            fmt = self.format
            if fmt not in _PRESETS:
                raise ValueError(
                    f"Unknown format {fmt!r}. Valid: {VALID_FORMATS}"
                )
            preset = _PRESETS[fmt]
            self.max_cpl = preset["max_cpl"]
            self.max_cps = preset["max_cps"]
            self.max_lines = preset["max_lines"]

    @property
    def needs_fps_conversion(self) -> bool:
        return (
            self.source_fps is not None
            and self.target_fps is not None
            and abs(self.source_fps - self.target_fps) > 0.001
        )

    @property
    def fps_ratio(self) -> float:
        if self.needs_fps_conversion:
            return self.target_fps / self.source_fps
        return 1.0
