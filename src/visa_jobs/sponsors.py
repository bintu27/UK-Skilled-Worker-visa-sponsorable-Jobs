from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import List, Optional

import httpx
import pandas as pd

from .config import TECH_KEYWORDS, AppConfig

logger = logging.getLogger(__name__)


def download_sponsor_register(config: AppConfig) -> Path:
    """Download the UK Home Office register of licensed sponsors."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    response = httpx.get(config.sponsor_register_url, timeout=30)
    response.raise_for_status()
    config.sponsor_csv_path.write_bytes(response.content)
    logger.info("Downloaded sponsor register to %s", config.sponsor_csv_path)
    return config.sponsor_csv_path


def _normalize_text(value: str) -> str:
    return value.strip().lower()


def filter_tech_companies(csv_path: Path, max_companies: int) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    company_column = _find_company_column(df)
    df["_name"] = df[company_column].fillna("")
    mask = df["_name"].apply(lambda val: _looks_like_tech(val))
    filtered = df[mask].copy()
    filtered = filtered.head(max_companies)
    filtered["company_hash"] = filtered["_name"].apply(_stable_hash)
    return filtered


def _find_company_column(df: pd.DataFrame) -> str:
    for candidate in [
        "Organisation Name",
        "Organisation",
        "Organization Name",
        "Company Name",
        "OrganisationName",
        "Name",
    ]:
        if candidate in df.columns:
            return candidate
    raise ValueError("Unable to locate company name column in sponsor register")


def _looks_like_tech(name: str) -> bool:
    text = _normalize_text(name)
    return any(keyword in text for keyword in TECH_KEYWORDS)


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def derive_career_page(name: str, overrides: Optional[dict[str, str]] = None) -> Optional[str]:
    if overrides and name in overrides:
        return overrides[name]
    slug = _normalize_text(name).replace(" ", "-")
    return f"https://{slug}.com/careers"
