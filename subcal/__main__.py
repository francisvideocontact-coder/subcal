"""
SubCal CLI — SRT subtitle recalibration tool.

Usage:
  subcal input.srt -o output.srt --format 9:16
  subcal input.srt -o output.srt --cpl 22 --cps 17
  subcal input.srt -o output.srt --source-fps 25 --target-fps 23.976
  subcal ./raw/ -o ./out/ --batch --formats 16:9,9:16
  subcal input.srt --dry-run --format 9:16
  subcal input.srt -o output.srt -v
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from project root without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.calibrator import calibrate_srt
from engine.batch import calibrate_batch, calibrate_batch_multiformat
from engine.rules import CalibrationRules, VALID_FORMATS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="subcal",
        description="SRT subtitle recalibration tool for post-production.",
    )
    p.add_argument("input", help="Input SRT file or folder (with --batch)")
    p.add_argument("-o", "--output", help="Output SRT file or folder")
    p.add_argument(
        "--format",
        choices=VALID_FORMATS,
        help="Format preset: 16:9, 9:16, 1:1 (overrides --cpl/--cps)",
    )
    p.add_argument(
        "--formats",
        help="Comma-separated list of formats for multi-format batch (e.g. 16:9,9:16)",
    )
    p.add_argument("--cpl", type=int, help="Max characters per line")
    p.add_argument("--cps", type=float, help="Max characters per second")
    p.add_argument("--max-lines", type=int, help="Max lines per block")
    p.add_argument("--min-duration", type=float, help="Min block duration in seconds")
    p.add_argument("--max-duration", type=float, help="Max block duration in seconds")
    p.add_argument("--min-gap", type=float, help="Min gap between blocks in seconds")
    p.add_argument("--source-fps", type=float, help="Source framerate")
    p.add_argument("--target-fps", type=float, help="Target framerate")
    p.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable semantic segmentation",
    )
    p.add_argument(
        "--orphan-threshold",
        type=int,
        default=4,
        help="Max orphan words to reattach (default: 4)",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: input is a folder",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show report without writing output",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output: detail each modification",
    )
    return p


def build_rules(args: argparse.Namespace) -> CalibrationRules:
    rules = CalibrationRules(
        format=args.format,
        semantic_segmentation=not args.no_semantic,
        orphan_threshold=args.orphan_threshold,
    )
    # Override preset values if explicitly provided
    if args.cpl is not None:
        rules.max_cpl = args.cpl
    if args.cps is not None:
        rules.max_cps = args.cps
    if args.max_lines is not None:
        rules.max_lines = args.max_lines
    if args.min_duration is not None:
        rules.min_duration = args.min_duration
    if args.max_duration is not None:
        rules.max_duration = args.max_duration
    if args.min_gap is not None:
        rules.min_gap = args.min_gap
    if args.source_fps is not None:
        rules.source_fps = args.source_fps
    if args.target_fps is not None:
        rules.target_fps = args.target_fps
    return rules


def print_result(result, path: str, verbose: bool) -> None:
    print(f"  {path}: {result.report}")
    if result.errors:
        for err in result.errors:
            print(f"    [ERREUR] {err}", file=sys.stderr)
    if verbose:
        for block in result.blocks:
            lines_str = " / ".join(block.lines)
            cpl = max((len(l) for l in block.lines), default=0)
            dur = block.duration_ms / 1000
            cps = sum(len(l) for l in block.lines) / dur if dur > 0 else 0
            print(f"    [{block.index:3d}] CPL={cpl:2d} CPS={cps:.1f} dur={dur:.2f}s  {lines_str}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    rules = build_rules(args)
    input_path = Path(args.input)

    # Multi-format batch
    if args.formats and (args.batch or input_path.is_dir()):
        formats = [f.strip() for f in args.formats.split(",")]
        output = Path(args.output) if args.output else input_path / "calibrated"
        if not args.dry_run:
            all_results = calibrate_batch_multiformat(
                input_path, formats=formats,
                output_dir=output, base_rules=rules,
            )
            for fmt, results in all_results.items():
                print(f"\n[Format {fmt}]")
                for i, r in enumerate(results):
                    print_result(r, f"fichier {i+1}", args.verbose)
        else:
            print(f"[Dry run] {input_path} → {args.formats}")
        return

    # Single-format batch
    if args.batch or input_path.is_dir():
        output = Path(args.output) if args.output else input_path / "calibrated"
        if not args.dry_run:
            results = calibrate_batch(input_path, rules=rules, output_dir=output)
            for i, r in enumerate(results):
                print_result(r, f"fichier {i+1}", args.verbose)
        else:
            print(f"[Dry run] {input_path} → {output}")
        return

    # Single file
    if not input_path.exists():
        print(f"[ERREUR] Fichier introuvable : {input_path}", file=sys.stderr)
        sys.exit(1)

    result = calibrate_srt(input_path, rules=rules)

    if args.dry_run:
        print(f"\n[Dry run] {input_path.name}")
        print(f"  {result.report}")
        if result.blocks:
            cpls = [max((len(l) for l in b.lines), default=0) for b in result.blocks]
            avg_cpl = sum(cpls) / len(cpls)
            max_cpl = max(cpls)
            print(f"  CPL avg={avg_cpl:.1f}  CPL max={max_cpl}")
        return

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(out_path)
        print_result(result, str(out_path), args.verbose)
    else:
        # Print to stdout
        from engine.parser import write_srt
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
            tmp = tf.name
        result.save(tmp)
        print(Path(tmp).read_text(encoding="utf-8"))
        os.unlink(tmp)


if __name__ == "__main__":
    main()
