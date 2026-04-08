"""
Batch processing: calibrate a folder of SRT files.
Supports multi-format output (generates subfolders per format).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from .calibrator import calibrate_srt, CalibrationResult
from .rules import CalibrationRules


def calibrate_batch(
    input_dir: str | Path,
    rules: Optional[CalibrationRules] = None,
    output_dir: Optional[str | Path] = None,
) -> List[CalibrationResult]:
    """
    Calibrate all SRT files in input_dir.
    Writes results to output_dir (default: input_dir/calibrated/).
    Returns list of CalibrationResult.
    """
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise ValueError(f"Not a directory: {input_dir}")

    if output_dir is None:
        output_dir = input_path / "calibrated"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if rules is None:
        rules = CalibrationRules()

    srt_files = sorted(input_path.glob("*.srt"))
    results = []

    for srt_file in srt_files:
        out_file = output_path / srt_file.name
        try:
            result = calibrate_srt(srt_file, rules=rules)
            result.save(out_file)
            results.append(result)
        except Exception as e:
            results.append(CalibrationResult([], 0, 0, 0, [str(e)]))

    return results


def calibrate_batch_multiformat(
    input_dir: str | Path,
    formats: List[str],
    output_dir: Optional[str | Path] = None,
    base_rules: Optional[CalibrationRules] = None,
) -> Dict[str, List[CalibrationResult]]:
    """
    Calibrate all SRT files in multiple formats.
    Generates one subfolder per format in output_dir.
    Returns dict mapping format → list of CalibrationResult.
    """
    input_path = Path(input_dir)
    if output_dir is None:
        output_dir = input_path / "calibrated"

    all_results: Dict[str, List[CalibrationResult]] = {}

    for fmt in formats:
        fmt_output = Path(output_dir) / fmt.replace(":", "x")
        fmt_output.mkdir(parents=True, exist_ok=True)

        # Build rules for this format
        if base_rules is not None:
            import dataclasses
            fmt_rules = dataclasses.replace(base_rules, format=fmt)
        else:
            fmt_rules = CalibrationRules(format=fmt)

        results = calibrate_batch(input_path, rules=fmt_rules, output_dir=fmt_output)
        all_results[fmt] = results

    return all_results
