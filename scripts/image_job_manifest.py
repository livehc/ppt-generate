#!/usr/bin/env python3
"""Create and maintain a resumable manifest for per-slide image generation."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STATUSES = ("pending", "running", "completed", "failed")
ERROR_TYPES = ("moderation_blocked", "timeout", "transient", "content_error", "missing_output")


def now() -> str:
    return datetime.now(UTC).isoformat()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("jobs"), dict):
        raise SystemExit(f"Unsupported or invalid manifest: {path}")
    return data


def save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}."
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def init_manifest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    if manifest_path.exists() and not args.force:
        raise SystemExit(f"Manifest already exists: {manifest_path}; use --force to replace")
    out_dir = Path(args.out_dir).expanduser().resolve()
    width = max(2, len(str(args.slide_count)))
    jobs: dict[str, Any] = {}
    for page in range(1, args.slide_count + 1):
        output = out_dir / f"slide-{page:0{width}d}.png"
        jobs[str(page)] = {
            "page": page,
            "status": "pending",
            "attempts": 0,
            "path": str(output),
            "error_type": None,
            "error": None,
            "updated_at": now(),
        }
    data = {
        "version": 1,
        "slide_count": args.slide_count,
        "page_number_width": width,
        "out_dir": str(out_dir),
        "created_at": now(),
        "updated_at": now(),
        "jobs": jobs,
    }
    save_manifest(manifest_path, data)
    print(manifest_path)
    return 0


def reconcile_missing_outputs(data: dict[str, Any]) -> bool:
    changed = False
    for job in data["jobs"].values():
        if job["status"] == "completed" and not Path(job["path"]).exists():
            job.update(
                status="pending",
                error_type="missing_output",
                error="Completed output is missing; job returned to pending.",
                updated_at=now(),
            )
            changed = True
    return changed


def pending_jobs(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    data = load_manifest(path)
    if reconcile_missing_outputs(data):
        save_manifest(path, data)
    jobs = [job for job in data["jobs"].values() if job["status"] in ("pending", "failed")]
    jobs.sort(key=lambda job: job["page"])
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
    else:
        for job in jobs:
            print(job["page"])
    return 0


def mark_job(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    data = load_manifest(path)
    key = str(args.page)
    if key not in data["jobs"]:
        raise SystemExit(f"Page {args.page} is outside 1..{data['slide_count']}")
    job = data["jobs"][key]
    if args.path:
        job["path"] = str(Path(args.path).expanduser().resolve())
    if args.status == "completed" and not Path(job["path"]).exists():
        raise SystemExit(f"Cannot mark completed; output does not exist: {job['path']}")
    if args.status == "running":
        job["attempts"] = int(job.get("attempts", 0)) + 1
    job["status"] = args.status
    job["error_type"] = args.error_type
    job["error"] = args.error
    if args.status == "completed":
        job["error_type"] = None
        job["error"] = None
    job["updated_at"] = now()
    save_manifest(path, data)
    print(json.dumps(job, ensure_ascii=False))
    return 0


def summary(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    data = load_manifest(path)
    if reconcile_missing_outputs(data):
        save_manifest(path, data)
    counts = {status: 0 for status in STATUSES}
    for job in data["jobs"].values():
        counts[job["status"]] += 1
    result = {
        "slide_count": data["slide_count"],
        "counts": counts,
        "complete": counts["completed"] == data["slide_count"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new manifest")
    init_parser.add_argument("manifest")
    init_parser.add_argument("--slide-count", required=True, type=positive_int)
    init_parser.add_argument("--out-dir", required=True)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=init_manifest)

    pending_parser = subparsers.add_parser("pending", help="List pending and failed pages")
    pending_parser.add_argument("manifest")
    pending_parser.add_argument("--json", action="store_true")
    pending_parser.set_defaults(func=pending_jobs)

    mark_parser = subparsers.add_parser("mark", help="Update one page job")
    mark_parser.add_argument("manifest")
    mark_parser.add_argument("page", type=positive_int)
    mark_parser.add_argument("--status", required=True, choices=STATUSES)
    mark_parser.add_argument("--path")
    mark_parser.add_argument("--error-type", choices=ERROR_TYPES)
    mark_parser.add_argument("--error")
    mark_parser.set_defaults(func=mark_job)

    summary_parser = subparsers.add_parser("summary", help="Print status counts")
    summary_parser.add_argument("manifest")
    summary_parser.set_defaults(func=summary)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
