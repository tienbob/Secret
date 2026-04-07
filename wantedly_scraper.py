import csv
import os
import re
import sys
import time
import platform
import subprocess
from urllib.parse import urlencode, quote_plus
import requests

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.selenium_manager import SeleniumManager
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
MAX_PAGES_TO_SCRAPE = 3
HEADLESS = False
BROWSER = "brave"  # Options: chrome, brave
BRAVE_BINARY_PATH = ""
USER_AGENT = ""
RUN_TIMESTAMP = ""

# Wantedly-specific
HIRING_TYPE = "mid_career"  # e.g. mid_career, newgrad
ORDER = "mixed"  # e.g. mixed
ONLY_NEW = True


def slugify_filename(text):
    if not text:
        return ""
    return text.replace(" ", "_").replace("/", "-")


def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def resolve_brave_binary_path():
    if BRAVE_BINARY_PATH and os.path.exists(BRAVE_BINARY_PATH):
        return BRAVE_BINARY_PATH

    system = platform.system()
    if system == "Darwin":
        default_path = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
        return default_path if os.path.exists(default_path) else None
    if system == "Windows":
        default_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        return default_path if os.path.exists(default_path) else None

    for path in ["/usr/bin/brave-browser", "/usr/bin/brave"]:
        if os.path.exists(path):
            return path
    return None


def default_user_agent():
    system = platform.system()
    if system == "Darwin":
        return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    if system == "Windows":
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def detect_browser_major_version(binary_path):
    if not binary_path:
        return None

    try:
        output = subprocess.check_output([binary_path, "--version"], text=True).strip()
        match = re.search(r"(\d+)\.\d+\.\d+\.\d+", output)
        return match.group(1) if match else None
    except Exception:
        return None


def setup_driver():
    current_dir = os.getcwd()
    local_profile_path = os.path.join(current_dir, "chrome_profile")
    browser = (BROWSER or "chrome").lower().strip()

    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={local_profile_path}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--log-level=3")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument(f"user-agent={USER_AGENT or default_user_agent()}")

    if browser == "brave":
        brave_binary = resolve_brave_binary_path()
        if not brave_binary:
            raise FileNotFoundError(
                "Brave binary not found. Install Brave or set BRAVE_BINARY_PATH."
            )
        options.binary_location = brave_binary

    if HEADLESS:
        options.add_argument("--headless=new")

    try:
        sm_args = ["--browser", "chrome"]
        if browser == "brave":
            sm_args.extend(["--browser-path", options.binary_location])

        sm_result = SeleniumManager().binary_paths(sm_args)
        service = ChromeService(sm_result["driver_path"])
        driver = webdriver.Chrome(service=service, options=options)
        print(f"Browser mode: {browser}")
        return driver
    except Exception:
        # Fallback for environments where Selenium Manager cannot fetch metadata.
        try:
            driver_version = None
            if browser == "brave":
                driver_version = detect_browser_major_version(options.binary_location)
                if driver_version:
                    driver_version = f"{driver_version}.0.0.0"

            service = ChromeService(
                ChromeDriverManager(driver_version=driver_version).install()
                if driver_version
                else ChromeDriverManager().install()
            )
            driver = webdriver.Chrome(service=service, options=options)
            print(f"Browser mode: {browser} (fallback driver manager)")
            return driver
        except Exception as fallback_error:
            print(f"FATAL: {fallback_error}")
            sys.exit(1)


def build_search_url(page_num):
    base = "https://www.wantedly.com/projects"
    params = {
        "new": "true" if ONLY_NEW else "false",
        "page": page_num,
        "keywords": JOB_KEYWORDS,
        "hiringTypes": HIRING_TYPE,
        "order": ORDER,
    }
    return f"{base}?{urlencode(params, quote_via=quote_plus)}"


def extract_project_ids(list_html):
    ids = []

    # Pattern 1: classic anchor links.
    ids.extend(re.findall(r'href="/projects/(\d+)', list_html))

    # Pattern 2: full paths in any string content.
    ids.extend(re.findall(r'/projects/(\d+)', list_html))

    # Pattern 3: Next.js payload references such as JobPost:{\"id\":\"123\"}
    ids.extend(re.findall(r'JobPost:\{\\"id\\":\\"(\d+)\\"\}', list_html))

    # Pattern 4: Fallback for arrays like "fetched_ids":[1,2,3]
    fetched_ids_match = re.search(r'"fetched_ids":\[(.*?)\]', list_html)
    if fetched_ids_match:
        ids.extend(re.findall(r'\d+', fetched_ids_match.group(1)))

    seen = set()
    ordered = []
    for pid in ids:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return ordered


def extract_meta_content(html, property_name):
    # Supports both double and single quotes around attributes.
    patterns = [
        rf'<meta[^>]*property="{re.escape(property_name)}"[^>]*content="([^"]+)"',
        rf"<meta[^>]*property='{re.escape(property_name)}'[^>]*content='([^']+)'",
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return None


def strip_wantedly_title_suffix(title):
    if not title:
        return None
    # Typical format: "<job title> - <company> ... - Wantedly"
    if " - " in title:
        parts = title.split(" - ")
        if parts:
            return clean_text(parts[0])
    return clean_text(title)


def extract_company_slug(html):
    match = re.search(r'/companies/([^"\'#?]+)', html)
    return match.group(1) if match else None


def seems_location_match(text, location):
    if not location:
        return True
    if not text:
        return False
    return location.lower() in text.lower()


def should_enforce_location_filter(location):
    if not location:
        return False

    # Wantedly listings are JP-focused and location can be implicit.
    if location.strip().lower() in {"japan", "jp", "日本"}:
        return False

    return True


def build_request_headers():
    return {
        "User-Agent": USER_AGENT or default_user_agent(),
        "Accept-Language": "en-US,en;q=0.9",
    }


def main():
    session = requests.Session()
    session.headers.update(build_request_headers())

    # Optional cookie hydration from Selenium profile can help with some anti-bot setups.
    # We keep this non-fatal so scraping can proceed even if browser setup fails.
    try:
        driver = setup_driver()
        driver.get("https://www.wantedly.com/projects")
        time.sleep(1)
        for cookie in driver.get_cookies():
            if cookie.get("name") and cookie.get("value"):
                session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
        driver.quit()
    except Exception:
        pass

    try:
        print("Scanning Wantedly listings...")

        project_ids = []
        project_set = set()

        # Phase 1: collect project IDs across listing pages.
        for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
            url = build_search_url(page_num)
            print(f"--- Collecting IDs: Page {page_num} ---")
            print(f"URL: {url}")

            response = session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text
            page_ids = extract_project_ids(html)

            new_count = 0
            for pid in page_ids:
                if pid not in project_set:
                    project_set.add(pid)
                    project_ids.append(pid)
                    new_count += 1

            print(f"   Found {new_count} new projects on this page.")

            # Stop early if this page added nothing.
            if new_count == 0:
                print("   No new project IDs. Stopping pagination.")
                break

        print(f"\nTotal unique projects found: {len(project_ids)}")
        print("Extracting details...")

        # Phase 2: extract details from each project page.
        all_data = []
        for i, pid in enumerate(project_ids, start=1):
            detail_url = f"https://www.wantedly.com/projects/{pid}"
            try:
                response = session.get(detail_url, timeout=30)
                response.raise_for_status()
                html = response.text
                og_title = extract_meta_content(html, "og:title")
                og_desc = extract_meta_content(html, "og:description")
                og_url = extract_meta_content(html, "og:url") or detail_url
                published_at = extract_meta_content(html, "article:published_time")
                company_slug = extract_company_slug(html)

                title = strip_wantedly_title_suffix(og_title)
                description = clean_text(og_desc)

                if should_enforce_location_filter(JOB_LOCATION) and not (
                    seems_location_match(title, JOB_LOCATION)
                    or seems_location_match(description, JOB_LOCATION)
                ):
                    print(f"[{i}/{len(project_ids)}] Skipped location mismatch: {detail_url}")
                    continue

                data = {
                    "wantedly_project_id": pid,
                    "scrape_run_at": export_run_timestamp(),
                    "url": og_url,
                    "title": title,
                    "company": company_slug,
                    "company_website": f"https://www.wantedly.com/companies/{company_slug}" if company_slug else None,
                    "date": published_at,
                    "description": description,
                    "keywords": JOB_KEYWORDS,
                    "hiring_type": HIRING_TYPE,
                    "location_filter": JOB_LOCATION,
                }

                if data["title"]:
                    print(f"[{i}/{len(project_ids)}] Scraped: {data['title']}")
                    all_data.append(data)
                else:
                    print(f"[{i}/{len(project_ids)}] Skipped (No Title): {detail_url}")

            except Exception as e:
                print(f"Error processing {detail_url}: {e}")
                continue

        # Save CSV
        clean_kw = slugify_filename(JOB_KEYWORDS)
        clean_loc = slugify_filename(JOB_LOCATION) if JOB_LOCATION else "all"
        filename = f"wantedly_{clean_kw}_{clean_loc}.csv"

        if all_data:
            print(f"\nSaving {len(all_data)} jobs to: {filename}")
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=all_data[0].keys())
                writer.writeheader()
                writer.writerows(all_data)
            print(f"\nSaved {len(all_data)} jobs to {filename}")
        else:
            print("\nNo data collected.")

    except Exception as e:
        print(f"Fatal Error: {e}")


if __name__ == "__main__":
    main()
