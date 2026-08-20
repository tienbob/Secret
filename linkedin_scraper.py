import time
import random
import csv
import os
import re
from urllib.parse import quote_plus

# Playwright
from playwright.sync_api import sync_playwright

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
JOB_WORKPLACE_TYPE = "remote"  # Options: on-site, remote, hybrid
INDUSTRY_FILTER = ""  # LinkedIn industry code (e.g., 4 = Computer Software, leave empty for all)
TIME_POSTED_FILTER = ""  # Last X days (e.g., r2592000 = 30 days, r604800 = 7 days, leave empty for all)
SORT_BY = ""  # R = Most Recent, DD = Date Posted, leave empty for relevance
MAX_PAGES_TO_SCRAPE = 1
HEADLESS = False
BROWSER = "brave"  # Options: chrome, brave (mapped to Playwright chromium)
BRAVE_BINARY_PATH = ""
USER_AGENT = ""
RUN_TIMESTAMP = ""

# --- Selectors (Updated for LinkedIn's new job detail pane structure) ---
SELECTORS = {
    "job_card_list": "div[data-job-id].job-card-container, li.jobs-search-results__list-item",
    "detail_pane": {
        "title": "div.job-details-jobs-unified-top-card__job-title h1, h1.t-24.t-bold, h2.t-16.t-black.t-bold",
        "company_name": "div.job-details-jobs-unified-top-card__company-name a",
        "job_location": "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text.tvm__text--low-emphasis",
        "posted_date": "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text.tvm__text--low-emphasis",
        "salary_info": "div.job-details-fit-level-preferences button strong",
        "description": "div.jobs-box__html-content, div.jobs-description-content__text--stretch, div.jobs-description__content, #job-details"
    }
}


def default_user_agent():
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def launch_browser(pw):
    """Connect to existing Brave browser via remote debugging port 9222.
    If not running, launches Brave with CDP first, then connects."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            print("🔗 Connected to existing Brave browser (port 9222)")
            return browser
        except Exception:
            print(f"⚠️  Could not connect to Brave on port 9222 (attempt {attempt + 1}/{max_retries}).")
            if attempt < max_retries - 1:
                print("   Launching Brave with remote debugging...")
                import subprocess
                subprocess.Popen(
                    ["./brave-debug.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(8)  # Give Brave time to start and enable CDP
    raise RuntimeError("Could not launch or connect to Brave browser after multiple attempts.")


# --- Scroll Logic ---
def load_full_job_list(page):
    print("   -> Loading jobs (Dynamic JS Scroll)...")

    # Zoom out to fit more items (triggers lazy load easier)
    try:
        page.evaluate("document.body.style.zoom = '80%'")
    except Exception:
        pass

    last_count = 0
    retries = 0
    max_retries = 4

    while True:
        cards = page.locator(SELECTORS["job_card_list"])
        count = cards.count()
        print(f"      Loaded {count} jobs...")

        if count >= 25 or (count == last_count and retries >= max_retries):
            try:
                page.evaluate("document.body.style.zoom = '100%'")
            except Exception:
                pass
            break

        if count == last_count:
            retries += 1
        else:
            retries = 0
            last_count = count

        # Aggressive scrolling strategy
        try:
            if count > 0:
                # Scroll the container of the first card and the window
                page.evaluate("""
                    var card = document.querySelector(arguments[0]);
                    if (card) {
                        var container = card.parentElement;
                        container.scrollTop = container.scrollHeight;
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                """, SELECTORS["job_card_list"])

                # Scroll the last card into view
                cards.nth(count - 1).scroll_into_view_if_needed()
        except Exception:
            # Blindly scroll known classes
            page.evaluate("""
                var targets = document.querySelectorAll('.jobs-search-results-list, .scaffold-layout__list');
                targets.forEach(t => t.scrollTop = t.scrollHeight);
            """)

        time.sleep(3)  # Wait for network


def main():
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            # Reuse existing context (has login cookies) instead of creating new one
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                print("🔗 Reusing existing Brave context with saved session")
                pages = context.pages
                page = pages[0] if pages else context.new_page()
            else:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 1024},
                )
                page = context.new_page()

            # Check Login
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(2)  # Let any redirects settle

            def get_current_url():
                """Safely get current URL, handling mid-navigation context destruction."""
                try:
                    return page.evaluate("window.location.href")
                except Exception:
                    try:
                        return page.url
                    except Exception:
                        return ""

            current_url = get_current_url()
            if "login" in current_url or "authwall" in current_url:
                print("Not logged in. Please log in manually in the opened browser window.")
                print("Waiting up to 300 seconds for login...")
                logged_in = False
                for _ in range(300):
                    time.sleep(1)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=2000)
                    except Exception:
                        pass  # Navigation may still be in progress
                    current_url = get_current_url()
                    # Success: URL changed to feed (or any non-login page)
                    if "login" not in current_url and "authwall" not in current_url:
                        logged_in = True
                        break
                if not logged_in:
                    print("Login not detected after 300 seconds. Exiting.")
                    browser.close()
                    return
            else:
                print("✅ Already logged in to LinkedIn")

            # Build URL with filters - Based on LinkedIn's URL structure
            WORKPLACE_FILTER_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
            GEO_ID_MAP = {
                "Europe": "100506914",
                "European Union": "100506914",
                "EU": "100506914",
                "Japan": "101355337",
                "United States": "103644278",
                "US": "103644278",
                "USA": "103644278",
                "United Kingdom": "101165590",
                "UK": "101165590",
                "Canada": "101174742",
                "Germany": "101282230",
                "France": "105015875",
                "Spain": "105646813",
                "Italy": "103350119",
                "Netherlands": "102890719",
                "Poland": "105072130",
                "Sweden": "105117694",
                "Switzerland": "106693272",
                "India": "102713980",
                "Australia": "101452733",
                "Singapore": "102454443",
                "Vietnam": "104195383"
            }

            base = "https://www.linkedin.com/jobs/search/"
            params = []

            if JOB_WORKPLACE_TYPE in WORKPLACE_FILTER_CODES:
                params.append(f"f_WT={WORKPLACE_FILTER_CODES[JOB_WORKPLACE_TYPE]}")

            if JOB_LOCATION in GEO_ID_MAP:
                params.append(f"geoId={GEO_ID_MAP[JOB_LOCATION]}")
            else:
                params.append(f"location={quote_plus(JOB_LOCATION)}")

            params.append(f'keywords=%22{quote_plus(JOB_KEYWORDS)}%22')

            if INDUSTRY_FILTER:
                params.append(f"f_I={INDUSTRY_FILTER}")

            if TIME_POSTED_FILTER:
                params.append(f"f_TPR={TIME_POSTED_FILTER}")

            if SORT_BY:
                params.append(f"sortBy={SORT_BY}")

            params.append("origin=JOB_SEARCH_PAGE_LOCATION_HISTORY")
            params.append("refresh=true")

            url = base + "?" + "&".join(params)
            print(f"Search URL: {url}")

            page.goto(url, wait_until="domcontentloaded")

            # Detect Cloudflare challenge and pause for manual verification
            if "Performing security verification" in page.title() or "Cloudflare" in page.title():
                print("🛑 Cloudflare challenge detected. Please complete the verification in the browser window.")
                print("Waiting up to 300 seconds for verification...")
                verified = False
                for _ in range(300):
                    time.sleep(1)
                    if "Performing security verification" not in page.title() and "Cloudflare" not in page.title():
                        verified = True
                        break
                if not verified:
                    print("Verification not completed after 300 seconds. Exiting.")
                    browser.close()
                    return
            else:
                # Normal site load: wait for content
                time.sleep(5)

            all_data = []
            processed = set()
            seen_jobs = set()

            for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
                print(f"--- Scraping Page {page_num} ---")

                load_full_job_list(page)

                cards = page.locator(SELECTORS["job_card_list"])
                card_count = cards.count()

                for i in range(card_count):
                    try:
                        card = cards.nth(i)
                        job_id = card.get_attribute("data-job-id")
                        if not job_id:
                            try:
                                href = card.locator("a").first.get_attribute("href") or ""
                                job_id = href.split("view/")[1].split("/")[0]
                            except Exception:
                                pass

                        if not job_id or job_id in processed:
                            continue

                        # Anti-bot random wait
                        rand_wait = random.uniform(1.5, 4.5)
                        time.sleep(rand_wait)

                        # Scroll sidebar to card to ensure it's clickable
                        card.scroll_into_view_if_needed()
                        time.sleep(0.2)

                        try:
                            card.click()
                        except Exception:
                            card.evaluate("el => el.click()")

                        # Wait for detail pane to load
                        time.sleep(1)

                        processed.add(job_id)

                        details = {
                            "linkedin_job_id": job_id,
                            "scrape_run_at": export_run_timestamp(),
                            "company_website": None,
                        }

                        # Get title
                        try:
                            el = page.locator(SELECTORS["detail_pane"]["title"]).first
                            details["title"] = clean_text(el.inner_text())
                        except Exception:
                            details["title"] = None

                        # Get company name
                        try:
                            el = page.locator(SELECTORS["detail_pane"]["company_name"]).first
                            details["company_name"] = clean_text(el.inner_text())
                            details["company_website"] = el.get_attribute("href")
                        except Exception:
                            details["company_name"] = None

                        # Get location (first tvm__text span)
                        try:
                            els = page.locator(SELECTORS["detail_pane"]["job_location"])
                            details["job_location"] = clean_text(els.first.inner_text()) if els.count() else None
                        except Exception:
                            details["job_location"] = None

                        # Get posted date (usually second or third tvm__text span)
                        try:
                            els = page.locator(SELECTORS["detail_pane"]["posted_date"])
                            posted = None
                            for j in range(els.count()):
                                text = els.nth(j).inner_text().strip()
                                if "ago" in text.lower() or "reposted" in text.lower():
                                    posted = clean_text(text)
                                    break
                            details["posted_date"] = posted
                        except Exception:
                            details["posted_date"] = None

                        # Get salary info (ignore non-salary badges like Remote/Full-time)
                        try:
                            el = page.locator(SELECTORS["detail_pane"]["salary_info"]).first
                            salary_text = clean_text(el.inner_text()) or ""
                            lower_text = salary_text.lower()

                            has_digits = any(ch.isdigit() for ch in salary_text)
                            salary_markers = ["$", "£", "€", "¥", "usd", "eur", "gbp", "/yr", "/year", "/hr", "/hour", "per", "k"]
                            has_marker = any(marker in lower_text for marker in salary_markers)

                            if salary_text and has_digits and has_marker:
                                details["salary_info"] = salary_text
                            else:
                                details["salary_info"] = None
                        except Exception:
                            details["salary_info"] = None

                        # Get description
                        try:
                            el = page.locator(SELECTORS["detail_pane"]["description"]).first
                            details["description"] = clean_text(el.inner_text())
                        except Exception:
                            details["description"] = None

                        if details.get("title"):
                            company_name = details.get("company_name", "")
                            job_key = (
                                details["title"].lower().strip(),
                                company_name.lower().strip() if company_name else "",
                            )

                            if job_key in seen_jobs:
                                print(f"   -> Skipped duplicate: {details['title']} at {company_name or 'Unknown'}")
                                continue

                            seen_jobs.add(job_key)
                            all_data.append(details)
                            print(f"   -> Scraped: {details['title']} at {company_name or 'Unknown'}")
                    except Exception:
                        continue

                # Next Page
                if page_num < MAX_PAGES_TO_SCRAPE:
                    try:
                        btn = page.locator("button[aria-label='View next page']").first
                        if btn.is_enabled():
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            time.sleep(5)
                        else:
                            break
                    except Exception:
                        break

            # Save
            clean_kw = JOB_KEYWORDS.replace(" ", "_").replace("/", "-")
            clean_loc = JOB_LOCATION.replace(" ", "_").replace("/", "-")

            filename = f"linkedin_{clean_kw}_{clean_loc}.csv"
            keys = ['linkedin_job_id', 'scrape_run_at', 'company_name', 'company_website', 'title', 'job_location', 'posted_date', 'salary_info', 'description']

            print(f"\n💾 Saving {len(all_data)} jobs to: {filename}")
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(all_data)

        except Exception as e:
            print(f"Fatal Error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()