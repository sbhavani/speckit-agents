#!/usr/bin/env python3
"""LLM-as-judge quality evaluator for experiment runs.

Scores each run's output on 4 dimensions using a separate Claude call
(no tools, no session reuse) for unbiased evaluation.

Usage:
    uv run python quality_evaluator.py experiments/results/
    uv run python quality_evaluator.py --re-score
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "experiments" / "results"
MAX_STDOUT_CHARS = 50_000

RUBRIC_PROMPT = """\
You are evaluating the output of an automated software engineering agent.
The agent was given a feature request and produced a plan and/or implementation.

## Feature Request
{description}

## Agent Output
```
{stdout}
```

## Scoring Rubric

Rate each dimension from 1 (poor) to 5 (excellent):

**Completeness** (1-5): Were all requirements in the feature request addressed?
- 1: Most requirements missing or ignored
- 3: Core requirements addressed, some gaps
- 5: All requirements fully addressed with edge cases considered

**Correctness** (1-5): Are the technical decisions sound?
- 1: Major errors, would not work
- 3: Generally correct, minor issues
- 5: Technically excellent, robust approach

**Consistency** (1-5): Does it follow existing codebase conventions?
- 1: Ignores project structure and patterns
- 3: Mostly follows conventions, some deviations
- 5: Seamlessly integrates with existing code style and patterns

**Code Quality** (1-5): Is the output clean, tested, and documented?
- 1: Messy, no tests, no documentation
- 3: Readable code, some tests or docs
- 5: Clean code, good test coverage, clear documentation

## Response Format

Respond with ONLY a JSON object (no markdown fences, no extra text):
{{"completeness": <int>, "correctness": <int>, "consistency": <int>, "code_quality": <int>, "rationale": "<brief explanation of scores>"}}
"""


def _parse_json_response(text: str) -> dict:
    """Extract a JSON object from Claude's response text.

    Uses the same 3-stage parsing strategy as tool_augment.py.
    """
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try markdown fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Try brace scan
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    return {"raw_response": text[:500], "parse_error": True}


def score_run(run_dir: Path) -> dict | None:
    """Score a single run directory using Claude."""
    metadata_path = run_dir / "metadata.json"
    stdout_path = run_dir / "stdout.log"

    if not metadata_path.exists() or not stdout_path.exists():
        return None

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stdout = stdout_path.read_text(encoding="utf-8")

    if not stdout.strip():
        return {
            "run_id": metadata.get("run_id", run_dir.name),
            "scores": {"completeness": 0, "correctness": 0, "consistency": 0, "code_quality": 0},
            "rationale": "Empty stdout - run produced no output",
            "error": None,
        }

    # Truncate if needed
    if len(stdout) > MAX_STDOUT_CHARS:
        stdout = stdout[:MAX_STDOUT_CHARS] + "\n\n[... truncated ...]"

    prompt = RUBRIC_PROMPT.format(
        description=metadata["description"],
        stdout=stdout,
    )

    # Filter out CLAUDECODE to avoid nested session issues
    env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode != 0:
            return {
                "run_id": metadata.get("run_id", run_dir.name),
                "scores": None,
                "rationale": None,
                "error": f"claude exit {result.returncode}: {result.stderr[:200]}",
            }

        # Parse the Claude CLI JSON wrapper
        cli_response = json.loads(result.stdout)
        response_text = cli_response.get("result", result.stdout)

        scores = _parse_json_response(response_text)

    except subprocess.TimeoutExpired:
        return {
            "run_id": metadata.get("run_id", run_dir.name),
            "scores": None,
            "rationale": None,
            "error": "claude call timed out after 120s",
        }
    except Exception as e:
        return {
            "run_id": metadata.get("run_id", run_dir.name),
            "scores": None,
            "rationale": None,
            "error": str(e),
        }

    if scores.get("parse_error"):
        return {
            "run_id": metadata.get("run_id", run_dir.name),
            "scores": None,
            "rationale": None,
            "error": f"Failed to parse scores: {scores.get('raw_response', '')[:200]}",
        }

    rationale = scores.pop("rationale", "")
    return {
        "run_id": metadata.get("run_id", run_dir.name),
        "scores": {
            "completeness": scores.get("completeness", 0),
            "correctness": scores.get("correctness", 0),
            "consistency": scores.get("consistency", 0),
            "code_quality": scores.get("code_quality", 0),
        },
        "rationale": rationale,
        "error": None,
    }


def evaluate_all(results_dir: Path, re_score: bool = False) -> list[dict]:
    """Score all run directories."""
    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    run_dirs = sorted(
        d for d in results_dir.iterdir()
        if d.is_dir() and (d / "metadata.json").exists()
    )

    if not run_dirs:
        print("No run directories found.", file=sys.stderr)
        sys.exit(1)

    all_results = []
    for i, run_dir in enumerate(run_dirs):
        quality_path = run_dir / "quality.json"

        if quality_path.exists() and not re_score:
            print(f"[{i+1}/{len(run_dirs)}] {run_dir.name} -- skipped (already scored)")
            existing = json.loads(quality_path.read_text(encoding="utf-8"))
            all_results.append(existing)
            continue

        print(f"[{i+1}/{len(run_dirs)}] Scoring {run_dir.name}...")
        result = score_run(run_dir)

        if result:
            quality_path.write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            all_results.append(result)

            if result["error"]:
                print(f"  Error: {result['error']}")
            elif result["scores"]:
                s = result["scores"]
                avg = sum(s.values()) / len(s)
                print(f"  Scores: C={s['completeness']} R={s['correctness']} "
                      f"S={s['consistency']} Q={s['code_quality']} (avg={avg:.1f})")

    return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-as-judge quality evaluator")
    parser.add_argument(
        "results_dir", nargs="?", default=str(RESULTS_DIR),
        help="Path to results directory (default: experiments/results/)",
    )
    parser.add_argument(
        "--re-score", action="store_true",
        help="Overwrite existing quality.json scores",
    )
    args = parser.parse_args()

    results = evaluate_all(Path(args.results_dir), re_score=args.re_score)

    # Print summary
    scored = [r for r in results if r.get("scores") and not r.get("error")]
    errored = [r for r in results if r.get("error")]
    print(f"\nDone: {len(scored)} scored, {len(errored)} errors out of {len(results)} runs")

    if scored:
        dims = ["completeness", "correctness", "consistency", "code_quality"]
        for dim in dims:
            vals = [r["scores"][dim] for r in scored if r["scores"][dim] > 0]
            if vals:
                avg = sum(vals) / len(vals)
                print(f"  {dim}: {avg:.2f} avg (n={len(vals)})")


if __name__ == "__main__":
    main()
