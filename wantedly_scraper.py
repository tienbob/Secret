import csv
import json
import re
import time
from urllib.parse import urlencode, quote_plus

import requests
from bs4 import BeautifulSoup

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


def default_user_agent():
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


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
    soup = BeautifulSoup(list_html, "html.parser")
    ids = []

    # 1) IDs from standard anchors.
    for anchor in soup.select("a[href]"):
        href = anchor.get("href") or ""
        match = re.search(r"/projects/(\d+)", href)
        if match:
            ids.append(match.group(1))

    # 2) IDs from script payloads and inline text.
    ids.extend(re.findall(r'/projects/(\d+)', list_html))

    # 3) Next.js payload references such as JobPost:{\"id\":\"123\"}
    ids.extend(re.findall(r'JobPost:\{\\"id\\":\\"(\d+)\\"\}', list_html))

    # 4) Fallback for arrays like "fetched_ids":[1,2,3]
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
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"property": property_name})
    if meta:
        return clean_text(meta.get("content"))
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
    soup = BeautifulSoup(html, "html.parser")
    company_link = soup.select_one('a[href*="/companies/"]')
    if company_link:
        href = company_link.get("href") or ""
        match = re.search(r"/companies/([^\"'#?]+)", href)
        if match:
            return match.group(1)

    match = re.search(r'/companies/([^"\'#?]+)', html)
    return match.group(1) if match else None


def parse_project_ldjson(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") in {"JobPosting", "Posting"}:
                return candidate
    return {}


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
                ld = parse_project_ldjson(html)
                og_title = extract_meta_content(html, "og:title")
                og_desc = extract_meta_content(html, "og:description")
                og_url = extract_meta_content(html, "og:url") or detail_url
                published_at = extract_meta_content(html, "article:published_time")
                company_slug = extract_company_slug(html)

                title = strip_wantedly_title_suffix(og_title) or clean_text(ld.get("title"))
                description = clean_text(og_desc) or clean_text(ld.get("description"))
                if not published_at:
                    published_at = clean_text(ld.get("datePosted"))

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
