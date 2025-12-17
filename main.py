from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from visa_jobs.config import AppConfig
from visa_jobs.pipeline import run_pipeline


if __name__ == "__main__":
    config = AppConfig.from_env()
    run_pipeline(config)
