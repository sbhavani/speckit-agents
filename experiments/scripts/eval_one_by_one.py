#!/usr/bin/env python3
"""Evaluate patches one at a time, deleting images after each."""

import subprocess
import json
import sys

# Instances that have patches and need evaluation
# Filtered from earlier list - only those with non-empty patches
NEED_EVAL = [
    "astropy__astropy-12907",
    "astropy__astropy-14182",
    "astropy__astropy-14365",
    "astropy__astropy-14995",
    "astropy__astropy-6938",
    "astropy__astropy-7746",
    "django__django-10914",
    "django__django-10924",
    "django__django-11001",
    "django__django-11039",
    "django__django-11049",
    "django__django-11133",
    "django__django-11179",
    "django__django-11283",
    "django__django-11422",
    "django__django-11564",
    "django__django-11583",
    "django__django-11620",
    "django__django-11630",
    "django__django-11742",
    "django__django-11797",
    "django__django-11815",
    "django__django-11848",
    "django__django-11905",
    "django__django-11910",
    "django__django-11964",
    "django__django-11999",
    "django__django-12113",
    "django__django-12125",
    "django__django-12184",
    "django__django-12284",
    "django__django-12286",
    "django__django-12308",
    "django__django-12453",
    "django__django-12470",
    "django__django-12497",
    "django__django-12589",
    "django__django-12700",
    "django__django-12708",
    "django__django-12747",
    "django__django-12856",
    "django__django-12908",
    "django__django-12915",
    "django__django-12983",
    "django__django-13028",
    "django__django-13033",
    "django__django-13158",
    "django__django-13220",
    "django__django-13230",
    "django__django-13265",
    "django__django-13315",
    "django__django-13321",
    "django__django-13401",
    "django__django-13447",
    "django__django-13448",
    "django__django-13590",
    "django__django-13658",
    "django__django-13660",
    "django__django-13710",
    "django__django-13757",
    "django__django-13768",
    "django__django-13925",
    "django__django-14608",
    "django__django-14787",
    "django__django-15695",
    "django__django-15738",
    "django__django-15851",
    "django__django-15996",
    "django__django-16229",
    "django__django-16255",
    "django__django-16379",
    "django__django-16400",
    "django__django-16408",
    "django__django-16527",
    "django__django-16595",
    "django__django-16816",
    "django__django-16820",
    "django__django-16873",
    "django__django-16910",
    "django__django-17051",
    "django__django-17087",
    "matplotlib__matplotlib-18869",
    "matplotlib__matplotlib-22711",
    "matplotlib__matplotlib-22835",
    "matplotlib__matplotlib-23299",
    "matplotlib__matplotlib-23314",
    "matplotlib__matplotlib-23476",
    "matplotlib__matplotlib-23562",
    "matplotlib__matplotlib-23563",
    "matplotlib__matplotlib-23913",
    "matplotlib__matplotlib-23964",
    "matplotlib__matplotlib-23987",
    "matplotlib__matplotlib-24149",
    "matplotlib__matplotlib-24265",
    "matplotlib__matplotlib-24334",
    "matplotlib__matplotlib-24970",
    "matplotlib__matplotlib-25079",
    "matplotlib__matplotlib-25311",
]

PREDICTIONS_PATH = "experiments/swebench/predictions_full-augmented.jsonl"

def run_eval(instance_id):
    """Run evaluation for one instance."""
    print(f"\n{'='*50}")
    print(f"Evaluating: {instance_id}")
    print(f"{'='*50}")

    cmd = [
        "uv", "run", "python", "-m", "swebench.harness.run_evaluation",
        "--dataset_name", "princeton-nlp/SWE-bench_Lite",
        "--split", "test",
        "--instance_ids", instance_id,
        "--predictions_path", PREDICTIONS_PATH,
        "--max_workers", "1",
        "--namespace", "none",
        "-id", f"eval_{instance_id.replace('-', '_')}",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)

    return result.returncode

def cleanup_images():
    """Remove specific swebench images to free disk space, but keep base images."""
    print("\nCleaning up Docker images...")
    # Get image IDs for specific instance images (not base)
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "swebench/sweb.eval*"],
        capture_output=True,
        text=True
    )
    images = result.stdout.strip().split("\n")

    for img in images:
        if img and "sweb.eval" in img:
            print(f"  Removing: {img}")
            subprocess.run(["docker", "rmi", "-f", img], capture_output=True)

    print("Cleanup complete")

def main():
    results = []

    for i, instance_id in enumerate(NEED_EVAL):
        print(f"\n[{i+1}/{len(NEED_EVAL)}] {instance_id}")

        # Run evaluation
        rc = run_eval(instance_id)

        # Check result
        try:
            with open(f"speckit-agents-full-augmented.eval_{instance_id.replace('-', '_')}.json") as f:
                result = json.load(f)
            resolved = result.get("resolved_instances", 0)
            unresolved = result.get("unresolved_instances", 0)
            errors = result.get("error_instances", 0)
            status = "PASS" if resolved else ("FAIL" if unresolved else "ERROR")
            print(f"Result: {status} (resolved={resolved}, unresolved={unresolved}, errors={errors})")
            results.append((instance_id, status))
        except Exception as e:
            print(f"Could not read result: {e}")
            results.append((instance_id, "ERROR"))

        # Clean up after each evaluation
        cleanup_images()

    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    passed = sum(1 for _, s in results if s == "PASS")
    failed = sum(1 for _, s in results if s == "FAIL")
    errors = sum(1 for _, s in results if s == "ERROR")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Errors: {errors}")
    print(f"Total: {len(results)}")

if __name__ == "__main__":
    main()
