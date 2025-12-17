from __future__ import annotations

from visa_jobs.config import AppConfig
from visa_jobs.pipeline import run_pipeline


if __name__ == "__main__":
    config = AppConfig.from_env()
    run_pipeline(config)
