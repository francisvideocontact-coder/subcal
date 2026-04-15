"""
SubCal — Interface web locale (Phase 2)
Lancement : python -m subcal.web  →  http://localhost:5000
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Allow running from project root without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.calibrator import calibrate_srt, CalibrationResult
from engine.normalizer import normalize_blocks
from engine.parser import parse_srt, write_srt, ms_to_timecode, SRTBlock
from engine.rules import CalibrationRules, VALID_FORMATS

app = FastAPI(title="SubCal", version="2.0.0")

# Static files
_STATIC = Path(__file__).parent / "static"
_TEMPLATES = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _block_to_dict(block: SRTBlock, original: Optional[SRTBlock] = None) -> dict:
    """Serialize an SRTBlock to a JSON-friendly dict with metrics."""
    dur_ms = block.duration_ms
    dur_s = dur_ms / 1000
    total_chars = sum(len(l) for l in block.lines)
    cps = round(total_chars / dur_s, 1) if dur_s > 0 else 0.0
    cpl_per_line = [len(l) for l in block.lines]

    return {
        "index": block.index,
        "start_ms": block.start_ms,
        "end_ms": block.end_ms,
        "start_tc": ms_to_timecode(block.start_ms),
        "end_tc": ms_to_timecode(block.end_ms),
        "lines": block.lines,
        "text": block.text,
        "duration_s": round(dur_s, 3),
        "cps": cps,
        "cpl_per_line": cpl_per_line,
        "cpl_max": max(cpl_per_line) if cpl_per_line else 0,
        "modified": original is not None and (
            block.lines != original.lines or
            block.start_ms != original.start_ms or
            block.end_ms != original.end_ms
        ),
    }


def _parse_rules(
    format: Optional[str] = None,
    cpl: Optional[int] = None,
    cps: Optional[float] = None,
    max_lines: Optional[int] = None,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    min_gap: Optional[float] = None,
    source_fps: Optional[float] = None,
    target_fps: Optional[float] = None,
    semantic: bool = True,
) -> CalibrationRules:
    rules = CalibrationRules(
        format=format,
        semantic_segmentation=semantic,
    )
    if cpl is not None:
        rules.max_cpl = cpl
    if cps is not None:
        rules.max_cps = cps
    if max_lines is not None:
        rules.max_lines = max_lines
    if min_duration is not None:
        rules.min_duration = min_duration
    if max_duration is not None:
        rules.max_duration = max_duration
    if min_gap is not None:
        rules.min_gap = min_gap
    if source_fps is not None:
        rules.source_fps = source_fps
    if target_fps is not None:
        rules.target_fps = target_fps
    return rules


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/api/parse")
async def parse_only(file: UploadFile = File(...)):
    """Parse an SRT file and return its original blocks without calibration."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Fichier vide")

    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
        tf.write(content)
        tmp_in = tf.name

    try:
        blocks = parse_srt(tmp_in)
    finally:
        os.unlink(tmp_in)

    return {
        "filename": file.filename,
        "blocks": [_block_to_dict(b) for b in blocks],
    }


@app.post("/api/calibrate")
async def calibrate(
    file: UploadFile = File(...),
    format: Optional[str] = Form(None),
    cpl: Optional[int] = Form(None),
    cps: Optional[float] = Form(None),
    max_lines: Optional[int] = Form(None),
    min_duration: Optional[float] = Form(None),
    max_duration: Optional[float] = Form(None),
    min_gap: Optional[float] = Form(None),
    source_fps: Optional[float] = Form(None),
    target_fps: Optional[float] = Form(None),
    semantic: bool = Form(True),
):
    """Calibrate a single SRT file. Returns blocks + metrics."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Fichier vide")

    rules = _parse_rules(
        format=format, cpl=cpl, cps=cps, max_lines=max_lines,
        min_duration=min_duration, max_duration=max_duration,
        min_gap=min_gap, source_fps=source_fps, target_fps=target_fps,
        semantic=semantic,
    )

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
        tf.write(content)
        tmp_in = tf.name

    try:
        original_blocks = parse_srt(tmp_in)
        result = calibrate_srt(tmp_in, rules=rules)
    finally:
        os.unlink(tmp_in)

    # Build a lookup of original blocks by index for diff
    orig_map = {b.index: b for b in original_blocks}

    return {
        "filename": file.filename,
        "report": result.report,
        "original_count": result.original_count,
        "recalibrated_count": result.recalibrated_count,
        "split_count": result.split_count,
        "errors": result.errors,
        "rules": {
            "max_cpl": rules.max_cpl,
            "max_cps": rules.max_cps,
            "max_lines": rules.max_lines,
            "min_duration": rules.min_duration,
            "max_duration": rules.max_duration,
            "min_gap": rules.min_gap,
        },
        "blocks": [_block_to_dict(b) for b in result.blocks],
        "original_blocks": [_block_to_dict(b) for b in original_blocks],
    }


@app.post("/api/export")
async def export_srt(request: dict):
    """Export edited blocks as a SRT file."""
    blocks_data = request.get("blocks", [])
    filename = request.get("filename", "calibrated.srt")

    if not blocks_data:
        raise HTTPException(400, "Aucun bloc fourni")

    blocks = []
    for bd in blocks_data:
        b = SRTBlock(
            index=bd["index"],
            start_ms=bd["start_ms"],
            end_ms=bd["end_ms"],
            lines=bd["lines"],
        )
        blocks.append(b)

    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
        tmp_out = tf.name

    try:
        write_srt(blocks, tmp_out)
        content = Path(tmp_out).read_bytes()
    finally:
        os.unlink(tmp_out)

    safe_name = Path(filename).stem + "_calibrated.srt"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.post("/api/batch")
async def batch_calibrate(
    files: List[UploadFile] = File(...),
    format: Optional[str] = Form(None),
    cpl: Optional[int] = Form(None),
    cps: Optional[float] = Form(None),
    max_lines: Optional[int] = Form(None),
    min_duration: Optional[float] = Form(None),
    max_duration: Optional[float] = Form(None),
    min_gap: Optional[float] = Form(None),
    source_fps: Optional[float] = Form(None),
    target_fps: Optional[float] = Form(None),
    semantic: bool = Form(True),
):
    """Calibrate multiple SRT files and return a ZIP."""
    if not files:
        raise HTTPException(400, "Aucun fichier fourni")

    rules = _parse_rules(
        format=format, cpl=cpl, cps=cps, max_lines=max_lines,
        min_duration=min_duration, max_duration=max_duration,
        min_gap=min_gap, source_fps=source_fps, target_fps=target_fps,
        semantic=semantic,
    )

    zip_buffer = io.BytesIO()
    summary = []

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for upload in files:
            content = await upload.read()
            if not content:
                continue

            with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
                tf.write(content)
                tmp_in = tf.name

            try:
                result = calibrate_srt(tmp_in, rules=rules)
            finally:
                os.unlink(tmp_in)

            # Write calibrated SRT to ZIP
            with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
                tmp_out = tf.name
            try:
                result.save(tmp_out)
                calibrated_content = Path(tmp_out).read_bytes()
            finally:
                os.unlink(tmp_out)

            out_name = Path(upload.filename).stem + "_calibrated.srt"
            zf.writestr(out_name, calibrated_content)

            summary.append({
                "filename": upload.filename,
                "report": result.report,
                "errors": result.errors,
            })

    zip_buffer.seek(0)

    # Return ZIP with summary in header
    headers = {
        "Content-Disposition": 'attachment; filename="subcal_batch.zip"',
        "X-Subcal-Summary": json.dumps(summary),
    }
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers=headers,
    )


@app.post("/api/normalize")
async def normalize_numbers_endpoint(request: dict):
    """Convert French written numbers to digits in subtitle blocks."""
    blocks = request.get("blocks", [])
    if not blocks:
        raise HTTPException(400, "Aucun bloc fourni")
    return {"blocks": normalize_blocks(blocks)}


@app.get("/api/presets")
async def get_presets():
    """Return format presets info."""
    presets = {}
    for fmt in VALID_FORMATS:
        r = CalibrationRules(format=fmt)
        presets[fmt] = {
            "max_cpl": r.max_cpl,
            "max_cps": r.max_cps,
            "max_lines": r.max_lines,
        }
    return presets
