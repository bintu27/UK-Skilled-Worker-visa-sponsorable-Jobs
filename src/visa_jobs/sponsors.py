from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import List, Optional

import httpx
import pandas as pd

from .config import TECH_KEYWORDS, AppConfig

logger = logging.getLogger(__name__)

REGISTER_PAGE_URL = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"


def download_sponsor_register(config: AppConfig) -> Path:
    """Download the UK Home Office register of licensed sponsors."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if config.sponsor_csv_path.exists():
        logger.info("Using cached sponsor register at %s", config.sponsor_csv_path)
        return config.sponsor_csv_path

    resolved_url = config.sponsor_register_url
    content: bytes

    if not resolved_url.endswith(".csv"):
        resolved_url = _discover_latest_register_url(resolved_url)

    try:
        content = _download_csv(resolved_url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.warning("Register URL %s returned 404. Attempting to discover the latest asset link.", resolved_url)
            resolved_url = _discover_latest_register_url()
            content = _download_csv(resolved_url)
        else:
            raise

    config.sponsor_csv_path.write_bytes(content)
    logger.info("Downloaded sponsor register from %s to %s", resolved_url, config.sponsor_csv_path)
    return config.sponsor_csv_path


def _download_csv(url: str) -> bytes:
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def _discover_latest_register_url(page_url: Optional[str] = None) -> str:
    page = page_url or REGISTER_PAGE_URL
    response = httpx.get(page, timeout=30)
    response.raise_for_status()
    matches = re.findall(r"https://assets\.publishing\.service\.gov\.uk/[^\"]+\.csv", response.text)
    worker_links = [link for link in matches if "worker" in link.lower()]
    candidates = worker_links or matches
    if not candidates:
        raise ValueError(f"Unable to locate sponsor register CSV link on {page}")
    latest_url = candidates[0]
    logger.info("Discovered latest sponsor register asset %s", latest_url)
    return latest_url


def _normalize_text(value: str) -> str:
    return value.strip().lower()


def export_skilled_sponsors(df: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    skilled_df = _filter_skilled_worker(df)
    skilled_df.to_csv(output_path, index=False)
    logger.info("Saved Skilled Worker sponsors to %s (%d rows)", output_path, len(skilled_df))
    return skilled_df


def filter_tech_companies(df: pd.DataFrame, max_companies: int) -> pd.DataFrame:
    company_column = _find_company_column(df)
    skilled_df = _filter_skilled_worker(df)
    skilled_df["_name"] = skilled_df[company_column].fillna("")
    mask = skilled_df["_name"].apply(lambda val: _looks_like_tech(val))
    filtered = skilled_df[mask].copy()
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


def _find_route_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in [
        "Route",
        "Routes",
        "Routes Offered",
        "Visa Route",
    ]:
        if candidate in df.columns:
            return candidate
    return None


def _filter_skilled_worker(df: pd.DataFrame) -> pd.DataFrame:
    route_column = _find_route_column(df)
    if not route_column:
        logger.warning("Unable to locate visa route column; returning original sponsor list")
        return df.copy()
    mask = df[route_column].fillna("").astype(str).str.contains("skilled worker", case=False)
    skilled = df[mask].copy()
    if skilled.empty:
        logger.warning("No Skilled Worker sponsors found after filtering")
    return skilled


def _looks_like_tech(name: str) -> bool:
    text = _normalize_text(name)
    return any(keyword in text for keyword in TECH_KEYWORDS)


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()
