import csv
import os
import re
import time
from urllib.parse import quote_plus

# Playwright
from playwright.sync_api import sync_playwright

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Vietnam"
MAX_PAGES_TO_SCRAPE = 3  # Set this to > 1 to test pagination
HEADLESS = False
BROWSER = "brave"  # Options: chrome, brave (mapped to Playwright chromium)
BRAVE_BINARY_PATH = ""
USER_AGENT = ""
RUN_TIMESTAMP = ""

# --- URL Logic ---
def slugify(text):
    if not text:
        return ""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def construct_search_url():
    base = "https://rubyonremote.com"
    parts = ["remote", slugify(JOB_KEYWORDS), "jobs"]
    if JOB_LOCATION:
        parts.extend(["in", slugify(JOB_LOCATION)])
    return f"{base}/{'-'.join(parts)}/"


# --- Browser Setup ---
def default_user_agent():
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


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


# --- Helper ---
def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def extract_company_website(page, current_url):
    """Extract company website from job listing page, filtering out tracking params."""
    try:
        anchors = page.locator("a[href^='http']")
        for i in range(anchors.count()):
            href = anchors.nth(i).get_attribute("href")
            if not href or "rubyonremote.com" in href or href == current_url:
                continue

            # Remove common tracking parameters
            clean_href = re.sub(r'[?&](utm_|fbclid|gclid|mc_|_ga|_gl).*', '', href)
            clean_href = clean_href.rstrip('?&')

            # Skip tracking/affiliate domains
            skip_domains = {"bit.ly", "tinyurl.com", "shorturl", "aff.", "tracking"}
            if any(skip in clean_href for skip in skip_domains):
                continue

            return clean_href if clean_href else href
    except Exception:
        return None
    return None


# --- Main Logic ---
def main():
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            # Reuse existing context (has saved session) instead of creating new one
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

            search_url = construct_search_url()
            print(f"Scanning: {search_url}")

            # Phase 1: Collect Links across Multiple Pages
            page.goto(search_url, wait_until="domcontentloaded")

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

            all_links = []

            for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
                print(f"--- Collecting Links: Page {page_num} ---")

                # Scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight/1.5);")
                time.sleep(1.5)

                # Grab job cards
                cards = page.locator("li a[href^='/jobs/']")
                new_count = 0
                for i in range(cards.count()):
                    try:
                        href = cards.nth(i).get_attribute("href")
                        if href:
                            # Ensure absolute URL (needed when connected to existing browser)
                            if href.startswith('/'):
                                href = f"https://rubyonremote.com{href}"
                            if href not in all_links:
                                all_links.append(href)
                                new_count += 1
                    except Exception:
                        pass

                print(f"   Found {new_count} new jobs on this page.")

                # Pagination Logic
                if page_num < MAX_PAGES_TO_SCRAPE:
                    try:
                        next_btn = page.locator("a[rel='next']").first
                        next_url = next_btn.get_attribute("href")

                        if next_url:
                            print(f"   Navigating to Page {page_num + 1}...")
                            page.goto(next_url, wait_until="domcontentloaded")
                            time.sleep(3)
                        else:
                            print("   'Next' button found but has no link. Stopping.")
                            break
                    except Exception:
                        print("   No 'Next' button found. Reached last page.")
                        break

            # Phase 2: Details Extraction
            print(f"\nTotal unique jobs found: {len(all_links)}")
            print("Extracting details...")

            all_data = []

            for i, url in enumerate(all_links):
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    time.sleep(1)  # Polite delay

                    # Extract ID
                    job_id_match = re.search(r"/jobs/(\d+)-", url)
                    job_id = job_id_match.group(1) if job_id_match else "unknown"

                    data = {
                        "rubyonremote_job_id": job_id,
                        "scrape_run_at": export_run_timestamp(),
                        "url": url,
                        "title": None,
                        "company": None,
                        "company_website": None,
                        "date": None,
                        "description": None
                    }

                    # Scrape Title (try multiple selectors as page structure may vary)
                    title = None
                    selectors = [
                        "h1.schema-job-title",
                        "h1",
                        "[data-testid='job-title']",
                        ".job-title",
                        "div.title h1",
                    ]
                    for selector in selectors:
                        try:
                            loc = page.locator(selector).first
                            if loc.count():
                                title = clean_text(loc.inner_text())
                                if title:
                                    break
                        except Exception:
                            continue

                    # Fallback: extract title from URL slug
                    if not title:
                        try:
                            url_match = re.search(r'/jobs/\d+-(.+?)(?:$|[?#])', url)
                            if url_match:
                                slug = url_match.group(1)
                                if '-at-' in slug:
                                    title_part = slug.split('-at-')[0]
                                else:
                                    title_part = slug
                                title = title_part.replace('-', ' ').replace('_', ' ').strip()
                                title = clean_text(title)
                                if title:
                                    title = ' '.join(word.capitalize() for word in title.split())
                        except Exception:
                            pass

                    data['title'] = title

                    # Debug: log page title if extraction failed
                    if not data['title']:
                        try:
                            page_title = page.title()
                            print(f"   [DEBUG] Page title: {page_title}")
                        except Exception:
                            pass

                    # Scrape Company (try multiple selectors)
                    company = None
                    company_selectors = [
                        "div.rounded-lg h3",
                        "[data-testid='company-name']",
                        ".company-name",
                        "div.company h3",
                        "a[href*='companies']",
                    ]
                    for selector in company_selectors:
                        try:
                            loc = page.locator(selector).first
                            if loc.count():
                                company = clean_text(loc.inner_text())
                                if company:
                                    break
                        except Exception:
                            continue
                    data['company'] = company

                    data['company_website'] = extract_company_website(page, url)

                    # Scrape Date
                    try:
                        date_el = page.locator("h2:has-text('Published on')").first
                        if date_el.count():
                            data['date'] = clean_text(date_el.inner_text().replace("Published on", ""))
                    except Exception:
                        pass

                    # Scrape Description (try multiple selectors)
                    description = None
                    desc_selectors = [
                        "div.schema-job-description",
                        "[data-testid='job-description']",
                        ".job-description",
                        "div.description",
                        "main article",
                    ]
                    for selector in desc_selectors:
                        try:
                            loc = page.locator(selector).first
                            if loc.count():
                                description = clean_text(loc.inner_text())
                                if description:
                                    break
                        except Exception:
                            continue
                    data['description'] = description

                    if data['title']:
                        print(f"[{i+1}/{len(all_links)}] Scraped: {data['title']}")
                        all_data.append(data)
                    else:
                        print(f"[{i+1}/{len(all_links)}] Skipped (No Title): {url}")

                except Exception as e:
                    print(f"Error processing {url}: {e}")
                    continue

            # Save
            clean_kw = JOB_KEYWORDS.replace(" ", "_").replace("/", "-")
            clean_loc = JOB_LOCATION.replace(" ", "_").replace("/", "-")

            filename = f"rubyonremote_{clean_kw}_{clean_loc}.csv"

            if all_data:
                print(f"\n💾 Saving {len(all_data)} jobs to: {filename}")
                with open(filename, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=all_data[0].keys())
                    writer.writeheader()
                    writer.writerows(all_data)
                print(f"\n✅ Saved {len(all_data)} jobs to {filename}")
            else:
                print("\n❌ No data collected.")

        except Exception as e:
            print(f"Fatal Error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()