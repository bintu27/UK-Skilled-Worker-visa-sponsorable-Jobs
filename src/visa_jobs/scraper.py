from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Tuple

from playwright.async_api import async_playwright

from .careers import extract_qa_jobs, find_real_career_page
from .model import JobOpportunity

logger = logging.getLogger(__name__)


async def scrape_careers(
    companies: Iterable[str],
    concurrent_browsers: int = 4,
    search_result_limit: int = 5,
) -> Tuple[List[JobOpportunity], List[dict]]:
    """Discover real career pages and extract QA jobs for each company."""
    semaphore = asyncio.Semaphore(concurrent_browsers)
    results: list[JobOpportunity] = []
    discovered_pages: list[dict] = []

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process"])
            browser_name = "chromium"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chromium launch failed (%s); falling back to Firefox", exc)
            browser = await p.firefox.launch(headless=True)
            browser_name = "firefox"
        context = await browser.new_context()
        logger.info("Using %s browser context for scraping", browser_name)

        async def bound_scrape(company: str) -> None:
            async with semaphore:
                career_url = await find_real_career_page(
                    company, context=context, max_results=search_result_limit
                )
                if not career_url:
                    logger.info("Skipping %s: no validated career page", company)
                    return
                discovered_pages.append({"company": company, "career_page_url": career_url})
                jobs = await extract_qa_jobs(career_url, company, context=context)
                if not jobs:
                    logger.info("No QA jobs extracted for %s (%s)", company, career_url)
                    return
                for job in jobs:
                    results.append(
                        JobOpportunity(
                            company=job["company_name"],
                            title=job["job_title"],
                            location="",
                            url=job["job_url"],
                            source=job["career_page_url"],
                            snippet=job["job_description"],
                        )
                    )

        tasks = [bound_scrape(company) for company in companies]
        await asyncio.gather(*tasks)
        await context.close()
        await browser.close()
    return results, discovered_pages
