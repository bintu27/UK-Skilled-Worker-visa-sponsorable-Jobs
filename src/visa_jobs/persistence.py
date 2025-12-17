from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set


def load_seen_jobs(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return set(data)


def save_seen_jobs(path: Path, job_ids: Set[str]) -> None:
    path.write_text(json.dumps(sorted(job_ids), indent=2))


def append_seen_jobs(path: Path, new_jobs: Set[str]) -> None:
    existing = load_seen_jobs(path)
    combined = existing.union(new_jobs)
    save_seen_jobs(path, combined)
