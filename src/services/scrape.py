
import os
import re
import logging
import requests
from typing import List
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logger = logging.getLogger("scrape-service")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s'
    )

# ------------------------------------------------------------------------------
# URL / Request setup
# ------------------------------------------------------------------------------
# Match .pdf links possibly followed by query or fragment (e.g., .pdf?dl=1 or .pdf#page=2)
PDF_PATTERN = re.compile(r"\.pdf([?#].*)?$", re.IGNORECASE)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def normalize_url(url: str) -> str:
    """Trim whitespace; return as-is if empty."""
    return url.strip() if url else url


# ------------------------------------------------------------------------------
# Static scraping (BeautifulSoup)
# ------------------------------------------------------------------------------
def find_pdf_links(url: str, max_links: int = 10) -> List[str]:
    """
    Fetch the page via requests and extract up to `max_links` hyperlinks ending in .pdf.
    Handles relative paths via urljoin.
    """
    from urllib.parse import urljoin

    links: List[str] = []
    try:
        logger.info(f"[static] GET {url}")
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"[static] Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        if PDF_PATTERN.search(href):
            if href.startswith("/"):
                href = urljoin(url, href)
            links.append(normalize_url(href))
            if len(links) >= max_links:
                break

    unique = list(dict.fromkeys(links))
    logger.info(f"[static] Found {len(unique)} PDF links")
    return unique


# ------------------------------------------------------------------------------
# Dynamic scraping (Selenium) with robust fallback to static
# ------------------------------------------------------------------------------
def dynamic_collect_links(url: str, max_links: int = 10) -> List[str]:
    """
    Use Selenium (headless Chrome) to collect up to `max_links` PDF hyperlinks.
    If Selenium fails or collects too few links, falls back to static scraping.

    Returns a de-duplicated list of links.
    """
    opts = Options()
    opts.add_argument("--headless=new")  # new headless mode for recent Chrome
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    # Optional: reduce logging noise
    opts.add_experimental_option('excludeSwitches', ['enable-logging'])

    links: List[str] = []
    driver = None

    try:
        # ✅ Correct initialization using Service
        logger.info("[dynamic] Starting Chrome via webdriver_manager")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)

        logger.info(f"[dynamic] GET {url}")
        driver.get(url)

        # Wait until at least one anchor tag is present
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "a")))

        anchors = driver.find_elements(By.TAG_NAME, "a")
        for a in anchors:
            href = a.get_attribute("href")
            if href and PDF_PATTERN.search(href):
                links.append(normalize_url(href))
                if len(links) >= max_links:
                    break

        links = list(dict.fromkeys(links))
        logger.info(f"[dynamic] Found {len(links)} PDF links")

        # If dynamic finds too few links, supplement via static fallback
        if len(links) < max_links // 2:
            logger.info("[dynamic] Too few links, supplementing with static fallback")
            static_links = find_pdf_links(url, max_links=max_links)
            merged = list(dict.fromkeys(links + static_links))
            return merged[:max_links]

        return links[:max_links]

    except (WebDriverException, TimeoutException) as e:
        logger.warning(f"[dynamic] Selenium error on {url}: {e}. Falling back to static.")
        return find_pdf_links(url, max_links=max_links)

    except Exception as e:
        logger.error(f"[dynamic] Unexpected error on {url}: {e}. Falling back to static.")
        return find_pdf_links(url, max_links=max_links)

    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            # Avoid raising during cleanup
            pass


# ------------------------------------------------------------------------------
# File download helper
# ------------------------------------------------------------------------------
def download_file(url: str, dest_path: str) -> bool:
    """Stream-download a file to `dest_path`. Returns True on success."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        logger.info(f"[download] {url} -> {dest_path}")
        with session.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        logger.warning(f"[download] Failed: {e}")
        return False
