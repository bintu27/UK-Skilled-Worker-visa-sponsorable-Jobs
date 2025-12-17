from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Dict, List

import pandas as pd

from .config import AppConfig
from .llm import LLMEvaluator
from .model import JobOpportunity
from .persistence import append_seen_jobs, load_seen_jobs
from .resume import load_resumes
from .scraper import scrape_careers
from .sponsors import derive_career_page, download_sponsor_register, filter_tech_companies

logger = logging.getLogger(__name__)


def run_pipeline(config: AppConfig) -> None:
    config.ensure_directories()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sponsor_csv = download_sponsor_register(config)
    tech_companies_df = filter_tech_companies(sponsor_csv, config.max_companies)

    companies_with_urls: list[tuple[str, str]] = []
    career_urls: list[str] = []
    for _, row in tech_companies_df.iterrows():
        name = row["_name"]
        url = derive_career_page(name, config.career_page_overrides)
        companies_with_urls.append((name, url))
        career_urls.append(url)

    if career_urls:
        tech_companies_df = tech_companies_df.copy()
        tech_companies_df["career_page_url"] = career_urls
        export_columns = ["_name", "career_page_url", "Town/City", "County", "Route", "Type & Rating"]
        present_columns = [col for col in export_columns if col in tech_companies_df.columns]
        jobs_export = tech_companies_df[present_columns].rename(columns={"_name": "company"})
        jobs_export.to_csv(config.jobs_csv_path, index=False)
        logger.info("Saved sponsor job targets to %s", config.jobs_csv_path)

    logger.info("Scraping %d companies for QA roles", len(companies_with_urls))
    jobs: List[JobOpportunity] = asyncio.run(
        scrape_careers(companies_with_urls, concurrent_browsers=config.concurrent_browsers)
    )

    logger.info("Discovered %d potential jobs", len(jobs))
    raw_df = pd.DataFrame([asdict(job) for job in jobs])
    raw_df.to_csv(config.raw_jobs_path, index=False)

    seen_ids = load_seen_jobs(config.seen_jobs_path)
    resumes = load_resumes(config.resumes_dir)
    evaluator = LLMEvaluator(config.openai_api_key, config.llm_model)

    ranked_records: List[dict] = []
    new_job_ids = set()

    for job in jobs:
        if job.job_id() in seen_ids:
            continue
        for resume_name, resume_text in resumes.items():
            llm_output = evaluator.evaluate(asdict(job), resume_text)
            job.qa_relevance = int(llm_output.get("qa_relevance", 0))
            job.visa_likelihood = str(llm_output.get("visa_likelihood", "Low"))
            job.resume_match_score = int(llm_output.get("resume_match_score", 0))
            job.matched_resume = resume_name
            if job.resume_match_score < 60:
                continue
            ranked_records.append(asdict(job))
        new_job_ids.add(job.job_id())
        if len(ranked_records) >= config.daily_job_limit:
            break

    append_seen_jobs(config.seen_jobs_path, new_job_ids)

    if not ranked_records:
        logger.warning("No jobs passed filtering or resume match threshold")
        return

    ranked_df = pd.DataFrame(ranked_records)
    ranked_df = ranked_df.sort_values(by=["resume_match_score", "qa_relevance"], ascending=False)
    ranked_df.to_csv(config.ranked_jobs_path, index=False)
    logger.info("Saved ranked jobs to %s", config.ranked_jobs_path)
