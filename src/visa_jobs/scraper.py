from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List

from playwright.async_api import async_playwright, BrowserContext, Page

from .config import EXCLUSION_KEYWORDS, QA_KEYWORDS
from .model import JobOpportunity

logger = logging.getLogger(__name__)


async def _extract_job_links(page: Page) -> list[JobOpportunity]:
    anchors = await page.query_selector_all("a")
    jobs: list[JobOpportunity] = []
    for anchor in anchors:
        text = (await anchor.inner_text()).strip()
        href = await anchor.get_attribute("href")
        if not href or not text:
            continue
        lower_text = text.lower()
        if any(keyword in lower_text for keyword in QA_KEYWORDS) and not any(
            block in lower_text for block in EXCLUSION_KEYWORDS
        ):
            url = href if href.startswith("http") else page.url.rstrip("/") + "/" + href.lstrip("/")
            jobs.append(
                JobOpportunity(
                    company="",
                    title=text,
                    location="",
                    url=url,
                    source=page.url,
                    snippet=text,
                )
            )
    return jobs


async def _scrape_company(context: BrowserContext, company: str, career_url: str) -> list[JobOpportunity]:
    page = await context.new_page()
    try:
        await page.goto(career_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        jobs = await _extract_job_links(page)
        for job in jobs:
            job.company = company
            job.location = job.location or (await page.title())
        if not jobs:
            logger.info("No QA roles found on %s", career_url)
        return jobs
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to scrape %s (%s): %s", company, career_url, exc)
        return []
    finally:
        await page.close()


async def scrape_careers(companies: Iterable[tuple[str, str]], concurrent_browsers: int = 4) -> List[JobOpportunity]:
    semaphore = asyncio.Semaphore(concurrent_browsers)
    results: list[JobOpportunity] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        async def bound_scrape(company: str, url: str) -> None:
            async with semaphore:
                jobs = await _scrape_company(context, company, url)
                results.extend(jobs)

        tasks = [bound_scrape(company, url) for company, url in companies]
        await asyncio.gather(*tasks)
        await context.close()
        await browser.close()
    return results
