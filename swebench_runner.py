#!/usr/bin/env python3
"""SWE-bench Lite runner for speckit-agents evaluation.

Runs SWE-bench instances under baseline and augmented conditions to measure
whether tool-augmented discovery/validation hooks improve bug-fix quality.

Requires: `pip install datasets` (HuggingFace) or a local JSONL dataset file.

Usage:
    uv run python swebench_runner.py                          # all 300 instances x 2
    uv run python swebench_runner.py --sample 50              # random 50 instances x 2
    uv run python swebench_runner.py --repo django/django     # filter by repo
    uv run python swebench_runner.py --instance-id django__django-11099  # single instance
    uv run python swebench_runner.py --condition baseline     # one condition only
    uv run python swebench_runner.py --resume                 # skip completed
    uv run python swebench_runner.py --dry-run                # print plan only
"""

import argparse
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / "experiments" / "swebench"
REPOS_DIR = WORKSPACE / "repos"
RESULTS_DIR = WORKSPACE / "results"
CONDITIONS = ["baseline", "augmented"]

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))

# Tools matching the architecture's discovery/validation layers
DISCOVERY_TOOLS = [
    "Read", "Glob", "Grep",
    "Bash(git log *)", "Bash(git diff *)", "Bash(ls *)",
]

# Prompt for pre-implementation discovery (adapted from tool_augment.py)
DISCOVERY_PROMPT = """\
You are a codebase analyst helping fix a bug. Examine this project and return a JSON object with:
{{
  "relevant_files": ["files most likely to need changes"],
  "root_cause_hypothesis": "your best guess at the root cause",
  "related_code": "key code snippets or patterns related to the issue",
  "test_files": ["test files related to this issue"],
  "fix_approach": "suggested approach to fixing this issue"
}}

Bug report:
{problem_statement}

Search for relevant code, read key files, check git log for related changes. Return ONLY the JSON object."""

# Prompt for post-implementation validation (adapted from tool_augment.py)
VALIDATION_PROMPT = """\
You are a code reviewer validating a bug fix. Check the changes in this repo and return a JSON object with:
{{
  "validation_passed": true/false,
  "changes_reviewed": ["files that were modified"],
  "issues": ["any problems found with the fix"],
  "test_coverage": "whether the fix is covered by existing tests"
}}

Original bug report:
{problem_statement}

Run `git diff` to see what changed. Check if the fix addresses the root cause. Return ONLY the JSON object."""

# Implementation prompt
IMPLEMENT_PROMPT = """\
Fix the following bug in this codebase. Make minimal, targeted changes.
Do NOT create new test files. Only modify existing source files to fix the bug.

{context}

Bug report:
{problem_statement}"""


def _run_claude(
    prompt: str,
    cwd: str,
    allowed_tools: list[str] | None = None,
    timeout: int = 300,
) -> dict:
    """Run claude -p and return parsed JSON output."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return {"result": "", "_timeout": True}

    if result.returncode != 0:
        return {"result": "", "_error": result.stderr[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"result": result.stdout.strip()}


def _parse_json_findings(text: str) -> dict:
    """Extract JSON from Claude response (same strategy as tool_augment.py)."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    return {"raw_response": text[:500], "parse_error": True}


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_dataset_hf() -> list[dict]:
    """Load SWE-bench Lite from HuggingFace datasets."""
    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    return [dict(row) for row in ds]


def load_dataset_local(path: Path) -> list[dict]:
    """Load from a local JSONL file."""
    instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def load_swebench(local_path: str | None = None) -> list[dict]:
    """Load SWE-bench Lite dataset."""
    if local_path:
        return load_dataset_local(Path(local_path))
    try:
        return load_dataset_hf()
    except ImportError:
        print(
            "Install 'datasets' package: pip install datasets\n"
            "Or provide a local JSONL file with --dataset-path",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Repo management
# ---------------------------------------------------------------------------


def repo_dir_name(repo: str) -> str:
    """Convert 'django/django' -> 'django__django'."""
    return repo.replace("/", "__")


def clone_repo(repo: str) -> Path:
    """Clone a repo into the workspace if not already present."""
    repo_path = REPOS_DIR / repo_dir_name(repo)
    if repo_path.exists():
        return repo_path

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    print(f"  Cloning {repo}...")
    subprocess.run(
        ["git", "clone", "--quiet", url, str(repo_path)],
        check=True, capture_output=True, text=True,
    )
    return repo_path


def checkout_commit(repo_path: Path, commit: str) -> None:
    """Hard-reset repo to a specific commit."""
    subprocess.run(
        ["git", "checkout", "-f", commit],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "clean", "-fdx"],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )


def capture_diff(repo_path: Path) -> str:
    """Capture git diff of all uncommitted changes."""
    # Stage everything so we get a complete diff
    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_path, capture_output=True, text=True,
    )
    result = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=repo_path, capture_output=True, text=True,
    )
    # Unstage
    subprocess.run(
        ["git", "reset", "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Running instances
# ---------------------------------------------------------------------------


def run_discovery(repo_path: Path, problem_statement: str) -> str:
    """Run pre-implementation discovery probe. Returns context string."""
    prompt = DISCOVERY_PROMPT.format(problem_statement=problem_statement)
    result = _run_claude(
        prompt=prompt,
        cwd=str(repo_path),
        allowed_tools=DISCOVERY_TOOLS,
        timeout=120,
    )
    raw = result.get("result", "")
    findings = _parse_json_findings(raw)

    if findings.get("parse_error"):
        return ""

    # Format findings as context for the implementation prompt
    parts = []
    if findings.get("relevant_files"):
        parts.append(f"Relevant files: {', '.join(findings['relevant_files'])}")
    if findings.get("root_cause_hypothesis"):
        parts.append(f"Likely root cause: {findings['root_cause_hypothesis']}")
    if findings.get("fix_approach"):
        parts.append(f"Suggested approach: {findings['fix_approach']}")
    if findings.get("related_code"):
        parts.append(f"Related code: {findings['related_code']}")

    return "\n".join(parts)


def run_validation(repo_path: Path, problem_statement: str) -> dict:
    """Run post-implementation validation. Returns findings dict."""
    prompt = VALIDATION_PROMPT.format(problem_statement=problem_statement)
    tools = DISCOVERY_TOOLS + ["Bash(pytest *)", "Bash(ruff *)"]
    result = _run_claude(
        prompt=prompt,
        cwd=str(repo_path),
        allowed_tools=tools,
        timeout=120,
    )
    raw = result.get("result", "")
    return _parse_json_findings(raw)


def run_instance(
    instance: dict,
    condition: str,
    dry_run: bool = False,
) -> dict:
    """Run a single SWE-bench instance under one condition."""
    instance_id = instance["instance_id"]
    repo = instance["repo"]
    base_commit = instance["base_commit"]
    problem_statement = instance["problem_statement"]

    run_id = f"{instance_id}_{condition}"
    run_dir = RESULTS_DIR / run_id

    if dry_run:
        print(f"  [dry-run] {instance_id} ({condition})")
        print(f"    repo={repo} commit={base_commit[:12]}")
        return {"instance_id": instance_id, "condition": condition, "dry_run": True}

    run_dir.mkdir(parents=True, exist_ok=True)

    # Clone and checkout
    repo_path = clone_repo(repo)
    checkout_commit(repo_path, base_commit)

    start = time.monotonic()
    discovery_context = ""
    validation = {}

    # Augmented: run pre-implementation discovery
    if condition == "augmented":
        print(f"    Running discovery probe...")
        discovery_context = run_discovery(repo_path, problem_statement)
        if discovery_context:
            (run_dir / "discovery.txt").write_text(discovery_context, encoding="utf-8")

    # Build implementation prompt
    context = ""
    if discovery_context:
        context = f"## Codebase Analysis\n{discovery_context}\n"

    impl_prompt = IMPLEMENT_PROMPT.format(
        context=context,
        problem_statement=problem_statement,
    )

    # Run implementation
    print(f"    Running implementation...")
    impl_result = _run_claude(
        prompt=impl_prompt,
        cwd=str(repo_path),
        timeout=600,
    )

    # Capture the diff
    patch = capture_diff(repo_path)

    # Augmented: run post-implementation validation
    if condition == "augmented" and patch:
        print(f"    Running validation...")
        validation = run_validation(repo_path, problem_statement)
        (run_dir / "validation.json").write_text(
            json.dumps(validation, indent=2), encoding="utf-8"
        )

    duration = time.monotonic() - start

    # Save outputs
    (run_dir / "patch.diff").write_text(patch, encoding="utf-8")
    (run_dir / "stdout.log").write_text(
        impl_result.get("result", ""), encoding="utf-8"
    )

    metadata = {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": base_commit,
        "condition": condition,
        "duration_s": round(duration, 2),
        "patch_size": len(patch),
        "has_patch": bool(patch.strip()),
        "discovery_context_len": len(discovery_context),
        "validation": validation if validation else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # Reset repo for next run
    checkout_commit(repo_path, base_commit)

    status = "PATCH" if patch.strip() else "EMPTY"
    print(f"    {status} ({len(patch)} bytes) in {duration:.1f}s")
    return metadata


def write_predictions(results_dir: Path, output_path: Path, model_name: str) -> int:
    """Collect all patches into SWE-bench predictions JSONL format."""
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for run_dir in sorted(results_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "metadata.json"
            patch_path = run_dir / "patch.diff"
            if not meta_path.exists() or not patch_path.exists():
                continue

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            patch = patch_path.read_text(encoding="utf-8")

            prediction = {
                "instance_id": meta["instance_id"],
                "model_name_or_path": model_name,
                "model_patch": patch,
            }
            f.write(json.dumps(prediction) + "\n")
            count += 1

    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-bench Lite runner for speckit-agents")
    parser.add_argument("--dataset-path", type=str, default=None,
                        help="Local JSONL dataset file (default: download from HuggingFace)")
    parser.add_argument("--sample", type=int, default=None,
                        help="Random sample of N instances (default: all)")
    parser.add_argument("--repo", type=str, default=None,
                        help="Filter to a specific repo (e.g. django/django)")
    parser.add_argument("--instance-id", type=str, default=None,
                        help="Run a specific instance ID")
    parser.add_argument("--condition", type=str, default=None, choices=CONDITIONS,
                        help="Run only one condition (default: both)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip instances that already have results")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without executing")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for --sample (default: 42)")
    parser.add_argument("--export", type=str, default=None,
                        help="Export predictions JSONL for SWE-bench evaluation harness")
    parser.add_argument("--model-name", type=str, default="speckit-agents",
                        help="Model name for predictions JSONL")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Export mode — just collect existing results into predictions.jsonl
    if args.export:
        condition = args.condition or "augmented"
        # Filter results dirs by condition
        filtered_dir = RESULTS_DIR
        model_name = f"{args.model_name}-{condition}"
        output = Path(args.export)
        count = write_predictions(filtered_dir, output, model_name)
        print(f"Wrote {count} predictions to {output}")
        return

    # Load dataset
    print("Loading SWE-bench Lite dataset...")
    instances = load_swebench(args.dataset_path)
    print(f"Loaded {len(instances)} instances")

    # Apply filters
    if args.repo:
        instances = [i for i in instances if i["repo"] == args.repo]
    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
    if args.sample and len(instances) > args.sample:
        random.seed(args.seed)
        instances = random.sample(instances, args.sample)

    if not instances:
        print("No instances match the given filters.", file=sys.stderr)
        sys.exit(1)

    conditions = [args.condition] if args.condition else CONDITIONS
    n_runs = len(instances) * len(conditions)
    print(f"Plan: {len(instances)} instances x {len(conditions)} conditions = {n_runs} runs")
    if args.dry_run:
        print("(DRY RUN)\n")
    print()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    completed = 0
    for instance in instances:
        for condition in conditions:
            completed += 1
            instance_id = instance["instance_id"]
            run_id = f"{instance_id}_{condition}"
            label = f"[{completed}/{n_runs}] {instance_id} ({condition})"

            if args.resume and (RESULTS_DIR / run_id / "metadata.json").exists():
                print(f"{label} -- skipped (already done)")
                continue

            print(f"{label}")
            meta = run_instance(instance, condition, dry_run=args.dry_run)
            results.append(meta)

            if not args.dry_run:
                time.sleep(2)

    if not args.dry_run and results:
        ok = sum(1 for r in results if r.get("has_patch"))
        empty = sum(1 for r in results if not r.get("has_patch") and not r.get("dry_run"))
        print(f"\nDone: {ok} with patches, {empty} empty out of {len(results)} runs")

        # Write per-condition predictions files
        for condition in conditions:
            pred_path = WORKSPACE / f"predictions_{condition}.jsonl"
            count = 0
            with open(pred_path, "w", encoding="utf-8") as f:
                for run_dir in sorted(RESULTS_DIR.iterdir()):
                    if not run_dir.is_dir() or not run_dir.name.endswith(f"_{condition}"):
                        continue
                    meta_path = run_dir / "metadata.json"
                    patch_path = run_dir / "patch.diff"
                    if not meta_path.exists() or not patch_path.exists():
                        continue
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    patch = patch_path.read_text(encoding="utf-8")
                    f.write(json.dumps({
                        "instance_id": meta["instance_id"],
                        "model_name_or_path": f"{args.model_name}-{condition}",
                        "model_patch": patch,
                    }) + "\n")
                    count += 1
            print(f"Predictions ({condition}): {pred_path} ({count} entries)")


if __name__ == "__main__":
    main()
