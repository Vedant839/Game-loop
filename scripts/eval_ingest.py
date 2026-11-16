"""Evaluation harness for Content Understanding Layer (§7.3.9, P1.5.7).

Runs the content understanding pipeline or evaluates generated checkpoints on a
chosen lecture and prints/saves:
  - Suitability and window analysis
  - Generation report (counts of concepts, proposed, rejected, kept, needs_review, fallback)
  - Every kept checkpoint with its cited concept and evidence
  - Every rejected checkpoint with its rejection rule/reason

Usage:
  python scripts/eval_ingest.py --lecture-file tests/fixtures/ingest/mary_transcript.json
  python scripts/eval_ingest.py --lecture-id math_sample_lecture
  python scripts/eval_ingest.py --compare-baseline tests/fixtures/ingest/mary_baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.schemas.lecture import Lecture
from backend.services.transcript_quality import analyze_transcript_quality
from backend.utils.question_rules import filter_checkpoints


def evaluate_lecture(
    lecture_data: dict,
    baseline_data: dict | None = None,
) -> dict:
    """Run deterministic evaluation and comparison on a lecture."""
    duration = lecture_data.get("duration_seconds", 300.0)
    transcript = lecture_data.get("transcript", [])

    # 1. Quality gate
    quality_report = analyze_transcript_quality(
        segments=transcript,
        duration_seconds=duration,
    )

    # 2. Checkpoints evaluation
    interventions = lecture_data.get("interventions", [])
    raw_checkpoints = []
    for intv in interventions:
        if isinstance(intv, dict):
            raw_checkpoints.append(intv)
        else:
            raw_checkpoints.append(intv.model_dump(mode="json"))

    kept, dropped = filter_checkpoints(raw_checkpoints, skip_r4=True)

    # 3. Baseline comparison if provided
    baseline_comparison = None
    if baseline_data:
        b_checkpoints = baseline_data.get("checkpoints", [])
        b_kept, b_dropped = filter_checkpoints(b_checkpoints, skip_r4=True)
        baseline_comparison = {
            "baseline_total": len(b_checkpoints),
            "baseline_rejected_by_rules": len(b_dropped),
            "baseline_survived": len(b_kept),
            "rejections": [
                {"question": d.get("question"), "rule": d.get("_drop_rule"), "reason": d.get("_drop_reason")}
                for d in b_dropped
            ],
        }

    # 4. Compile eval summary
    report = {
        "lecture_id": lecture_data.get("id", "unknown"),
        "duration_seconds": duration,
        "suitability": quality_report.suitability,
        "speech_coverage": quality_report.speech_coverage,
        "longest_silent_stretch_s": quality_report.longest_silent_stretch_s,
        "total_windows": len(quality_report.windows),
        "weak_windows_count": len([w for w in quality_report.windows if w.verdict == "weak"]),
        "quality_message": quality_report.message,
        "generation": {
            "proposed": len(raw_checkpoints),
            "rejected_by_rules": len(dropped),
            "kept": len(kept),
            "needs_review": sum(1 for k in kept if k.get("review_state") == "needs_review"),
            "fallback_reflect": sum(1 for k in kept if str(k.get("id", "")).startswith("fb_chk_")),
            "rejections": [
                {"id": d.get("id"), "question": d.get("question"), "rule": d.get("_drop_rule"), "reason": d.get("_drop_reason")}
                for d in dropped
            ],
        },
        "kept_checkpoints": [
            {
                "id": k.get("id"),
                "trigger_time": k.get("trigger_time"),
                "question": k.get("question"),
                "concept": k.get("concept"),
                "review_state": k.get("review_state", "auto"),
            }
            for k in kept
        ],
        "baseline_comparison": baseline_comparison,
    }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Content Understanding Eval Harness")
    parser.add_argument("--lecture-file", type=Path, help="Path to lecture JSON file")
    parser.add_argument("--baseline-file", type=Path, help="Path to baseline bad checkpoints JSON file")
    parser.add_argument("--out", type=Path, help="Output JSON path")
    args = parser.parse_args()

    if not args.lecture_file:
        print("Please provide --lecture-file", file=sys.stderr)
        sys.exit(1)

    with open(args.lecture_file, encoding="utf-8") as f:
        lecture_data = json.load(f)

    baseline_data = None
    if args.baseline_file and args.baseline_file.exists():
        with open(args.baseline_file, encoding="utf-8") as f:
            baseline_data = json.load(f)

    result = evaluate_lecture(lecture_data, baseline_data)

    print("=" * 60)
    print(f"EVAL REPORT: {result['lecture_id']}")
    print("=" * 60)
    print(f"Suitability:     {result['suitability'].upper()}")
    print(f"Speech Coverage: {result['speech_coverage'] * 100:.1f}%")
    print(f"Silent stretch:  {result['longest_silent_stretch_s']}s")
    print(f"Windows:         {result['total_windows']} (weak: {result['weak_windows_count']})")
    print(f"Message:         {result['quality_message']}")
    print("-" * 60)
    print(f"Proposed:        {result['generation']['proposed']}")
    print(f"Rejected:        {result['generation']['rejected_by_rules']}")
    print(f"Kept:            {result['generation']['kept']} (needs_review: {result['generation']['needs_review']}, fallback: {result['generation']['fallback_reflect']})")

    if result.get("baseline_comparison"):
        b = result["baseline_comparison"]
        print("-" * 60)
        print(f"BASELINE COMPARISON: {b['baseline_total']} bad baseline checkpoints")
        print(f"Successfully rejected: {b['baseline_rejected_by_rules']} / {b['baseline_total']}")
        print(f"False passes:          {b['baseline_survived']} / {b['baseline_total']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved report to {args.out}")


if __name__ == "__main__":
    main()

