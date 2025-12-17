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
from .sponsors import download_sponsor_register, export_skilled_sponsors, filter_tech_companies

logger = logging.getLogger(__name__)


def run_pipeline(config: AppConfig) -> None:
    config.ensure_directories()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sponsor_csv = download_sponsor_register(config)
    sponsor_df = pd.read_csv(sponsor_csv)
    skilled_df = export_skilled_sponsors(sponsor_df, config.skilled_companies_path)
    tech_companies_df = filter_tech_companies(skilled_df, config.max_companies)

    company_names = tech_companies_df["_name"].tolist()

    logger.info("Scraping %d companies for QA roles", len(company_names))
    jobs, discovered_pages = asyncio.run(
        scrape_careers(company_names, concurrent_browsers=config.concurrent_browsers)
    )

    jobs_export = pd.DataFrame(discovered_pages)
    if jobs_export.empty:
        jobs_export = pd.DataFrame(columns=["company", "career_page_url"])
    else:
        source_df = tech_companies_df.rename(columns={"_name": "company"})
        jobs_export = jobs_export.merge(source_df, on="company", how="left")
    export_columns = ["company", "career_page_url", "Town/City", "County", "Route", "Type & Rating"]
    for column in export_columns:
        if column not in jobs_export.columns:
            jobs_export[column] = ""
    jobs_export[export_columns].to_csv(config.career_pages_path, index=False)
    logger.info("Saved verified career pages to %s", config.career_pages_path)

    logger.info("Discovered %d potential jobs", len(jobs))
    raw_records = [
        {
            "company": job.company,
            "career_page_url": job.source,
            "job_title": job.title,
            "job_url": job.url,
            "job_description": job.snippet,
        }
        for job in jobs
    ]
    raw_df = pd.DataFrame(raw_records)
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
            job.llm_reason = str(llm_output.get("reason", ""))
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
    rename_map = {
        "title": "job_title",
        "url": "job_url",
        "source": "career_page_url",
        "snippet": "job_description",
    }
    scored_df = ranked_df.rename(columns=rename_map)
    scored_df.to_csv(config.scored_jobs_path, index=False)
    logger.info("Saved scored jobs to %s", config.scored_jobs_path)
