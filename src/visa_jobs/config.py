from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List


DEFAULT_SPONSOR_URL = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration for the job discovery pipeline."""

    sponsor_register_url: str = DEFAULT_SPONSOR_URL
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    resumes_dir: Path = Path(os.getenv("RESUMES_DIR", "resumes"))
    daily_job_limit: int = int(os.getenv("DAILY_JOB_LIMIT", "25"))
    max_companies: int = int(os.getenv("MAX_COMPANIES", "150"))
    concurrent_browsers: int = int(os.getenv("CONCURRENT_BROWSERS", "4"))
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    career_page_overrides: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AppConfig":
        career_config_path = os.getenv("CAREER_PAGES_FILE", "career_pages.json")
        overrides: Dict[str, str] = {}
        path = Path(career_config_path)
        if path.exists():
            overrides = json.loads(path.read_text())
        return cls(career_page_overrides=overrides)

    def ensure_directories(self) -> None:
        for path in self.directories():
            path.mkdir(parents=True, exist_ok=True)

    def directories(self) -> Iterable[Path]:
        return [self.data_dir, self.resumes_dir]

    @property
    def raw_jobs_path(self) -> Path:
        return self.data_dir / "jobs_raw.csv"

    @property
    def ranked_jobs_path(self) -> Path:
        return self.data_dir / "jobs_ranked.csv"

    @property
    def seen_jobs_path(self) -> Path:
        return self.data_dir / "jobs_seen.json"

    @property
    def sponsor_csv_path(self) -> Path:
        return self.data_dir / "sponsor_register.csv"

    @property
    def jobs_csv_path(self) -> Path:
        return self.data_dir / "jobs.csv"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "run.log"


TECH_KEYWORDS: List[str] = [
    "tech",
    "software",
    "digital",
    "ai",
    "data",
    "cloud",
    "robotics",
    "electronics",
    "automation",
    "solutions",
    "systems",
    "cyber",
]

QA_KEYWORDS: List[str] = [
    "qa",
    "quality assurance",
    "quality engineer",
    "sdet",
    "test engineer",
    "automation engineer",
    "quality manager",
    "qe",
]

EXCLUSION_KEYWORDS: List[str] = [
    "junior",
    "graduate",
    "intern",
    "placement",
    "contract",
    "temp",
    "temporary",
    "manual tester",
]
