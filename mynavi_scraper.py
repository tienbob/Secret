import csv
import html
import json
import re
import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
MAX_PAGES_TO_SCRAPE = 3
RUN_TIMESTAMP = ""
FEATURE_WORD_ID = "f16010103"

def slugify_filename(text):
    if not text:
        return ""
    return text.replace(" ", "_").replace("/", "-")


def clean_text(text):
    if not text:
        return None
    return " ".join(html.unescape(str(text)).split())


def strip_tags(text):
    if not text:
        return ""
    soup = BeautifulSoup(str(text), "html.parser")
    return clean_text(soup.get_text(" ", strip=True)) or ""


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def default_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }


def build_search_url(keyword, page_num):
    if FEATURE_WORD_ID:
        if page_num <= 1:
            return f"https://tenshoku.mynavi.jp/fw/{FEATURE_WORD_ID}/"
        return f"https://tenshoku.mynavi.jp/fw/{FEATURE_WORD_ID}/pg{page_num}/"

    encoded_kw = quote(keyword)
    if page_num <= 1:
        return f"https://tenshoku.mynavi.jp/list/kw{encoded_kw}/"
    return f"https://tenshoku.mynavi.jp/list/kw{encoded_kw}/pg{page_num}/"


def normalize_job_url(url):
    if not url:
        return None

    absolute_url = urljoin("https://tenshoku.mynavi.jp", url)

    match = re.search(r"https://tenshoku\.mynavi\.jp/jobinfo-\d+-\d+-\d+-\d+/", absolute_url)
    if match:
        return match.group(0)

    match = re.search(r"https://tenshoku\.mynavi\.jp/jobinfo-\d+-\d+-\d+-\d+", absolute_url)
    if match:
        return f"{match.group(0)}/"

    return None


def extract_job_urls(list_html):
    soup = BeautifulSoup(list_html, "html.parser")
    candidates = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if href and "jobinfo-" in href:
            candidates.append(href)

    # Fallback for script-embedded URLs.
    candidates.extend(re.findall(r"(?:https://tenshoku\.mynavi\.jp)?/jobinfo-[^\s\"'<>]+", list_html))

    seen = set()
    ordered = []
    for candidate in candidates:
        normalized = normalize_job_url(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def has_next_page(list_html, current_page_num):
    soup = BeautifulSoup(list_html, "html.parser")
    next_page_num = current_page_num + 1
    return soup.select_one(f'a[href*="/pg{next_page_num}/"]') is not None


def extract_meta_content(html, property_name):
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"property": property_name})
    if not meta:
        meta = soup.find("meta", attrs={"name": property_name})
    if meta:
        return clean_text(meta.get("content"))
    return None


def parse_jobposting_ldjson(html_text):
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
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return {}


def extract_company_name(html):
    soup = BeautifulSoup(html, "html.parser")
    company_tag = soup.select_one("span.companyName")
    if company_tag:
        return clean_text(company_tag.get_text(" ", strip=True))

    ld = parse_jobposting_ldjson(html)
    hiring_org = ld.get("hiringOrganization") if isinstance(ld, dict) else {}
    if isinstance(hiring_org, dict):
        return clean_text(hiring_org.get("name"))
    return None


def extract_info_update_date(html):
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = re.search(r"情報更新日\s*[：:]\s*([0-9]{4}/[0-9]{2}/[0-9]{2})", text)
    if match:
        return match.group(1)
    return None


def extract_job_title(html):
    soup = BeautifulSoup(html, "html.parser")
    occ_name = soup.select_one("span.occName")
    if occ_name:
        value = clean_text(occ_name.get_text(" ", strip=True))
        if value:
            return value

    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta:
        value = clean_text(meta.get("content"))
        if value:
            return value
    return None


def extract_company_website(html):
    ld = parse_jobposting_ldjson(html)
    hiring_org = ld.get("hiringOrganization") if isinstance(ld, dict) else {}
    if isinstance(hiring_org, dict):
        same_as = hiring_org.get("sameAs")
        if isinstance(same_as, list):
            for url in same_as:
                if isinstance(url, str) and "tenshoku.mynavi.jp" not in url:
                    return clean_text(url) or ""
        elif isinstance(same_as, str) and "tenshoku.mynavi.jp" not in same_as:
            return clean_text(same_as) or ""
    return ""


def extract_table_value(html, item_class):
    soup = BeautifulSoup(html, "html.parser")
    dd = soup.select_one(f"dl.majorJobOfferTable__item.{item_class} dd")
    if not dd:
        return ""
    return clean_text(dd.get_text(" ", strip=True)) or ""


def extract_description(html):
    soup = BeautifulSoup(html, "html.parser")
    blocks = []

    summary_tag = soup.select_one("div.jobPointArea__head")
    if summary_tag:
        summary = clean_text(summary_tag.get_text(" ", strip=True))
        if summary:
            blocks.append(summary)

    for body_tag in soup.select("div.jobPointArea__body"):
        text = clean_text(body_tag.get_text(" ", strip=True))
        if text:
            blocks.append(text)

    if blocks:
        unique_blocks = []
        seen = set()
        for block in blocks:
            if block not in seen:
                seen.add(block)
                unique_blocks.append(block)
        return "\n\n".join(unique_blocks)

    return extract_meta_content(html, "description") or extract_meta_content(html, "og:description")


def should_enforce_location_filter(location):
    if not location:
        return False
    return location.strip().lower() not in {"japan", "jp", "日本"}


def seems_location_match(text, location):
    if not location:
        return True
    if not text:
        return False
    return location.lower() in text.lower()


def main():
    session = requests.Session()
    session.headers.update(default_headers())

    try:
        print("Scanning Mynavi listings...")
        if FEATURE_WORD_ID:
            print(f"Mode: Feature-word listing (fw/{FEATURE_WORD_ID})")
        else:
            print("Mode: Keyword listing (list/kw...)" )

        job_urls = []
        url_set = set()

        for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
            list_url = build_search_url(JOB_KEYWORDS, page_num)
            print(f"--- Collecting URLs: Page {page_num} ---")
            print(f"URL: {list_url}")

            response = session.get(list_url, timeout=30)
            response.raise_for_status()
            page_html = response.text

            page_urls = extract_job_urls(page_html)
            new_count = 0
            for page_url in page_urls:
                if page_url not in url_set:
                    url_set.add(page_url)
                    job_urls.append(page_url)
                    new_count += 1

            print(f"   Found {new_count} new jobs on this page.")

            if new_count == 0:
                print("   No new job URLs. Stopping pagination.")
                break

            if not has_next_page(page_html, page_num):
                print("   No next page link found. Stopping pagination.")
                break

        print(f"\nTotal unique jobs found: {len(job_urls)}")
        print("Extracting details...")

        all_data = []
        for index, detail_url in enumerate(job_urls, start=1):
            try:
                response = session.get(detail_url, timeout=30)
                response.raise_for_status()
                html = response.text

                title = extract_job_title(html)
                company = extract_company_name(html)
                company_website = extract_company_website(html)
                description = extract_description(html)
                posted_date = extract_info_update_date(html)
                location = extract_table_value(html, "location")
                salary_info = extract_table_value(html, "salary")

                if should_enforce_location_filter(JOB_LOCATION):
                    if not (
                        seems_location_match(title, JOB_LOCATION)
                        or seems_location_match(description, JOB_LOCATION)
                        or seems_location_match(location, JOB_LOCATION)
                    ):
                        print(f"[{index}/{len(job_urls)}] Skipped location mismatch: {detail_url}")
                        continue

                source_job_id = ""
                id_match = re.search(r"jobinfo-(\d+-\d+-\d+-\d+)", detail_url)
                if id_match:
                    source_job_id = id_match.group(1)

                data = {
                    "source_job_id": source_job_id,
                    "scrape_run_at": export_run_timestamp(),
                    "url": detail_url,
                    "title": title,
                    "company": company,
                    "company_website": company_website,
                    "date": posted_date,
                    "location": location,
                    "salary_info": salary_info,
                    "description": description,
                    "keywords": JOB_KEYWORDS,
                    "location_filter": JOB_LOCATION,
                }

                if data["title"]:
                    print(f"[{index}/{len(job_urls)}] Scraped: {data['title'][:80]}")
                    all_data.append(data)
                else:
                    print(f"[{index}/{len(job_urls)}] Skipped (No Title): {detail_url}")

            except Exception as err:
                print(f"Error processing {detail_url}: {err}")
                continue

        clean_kw = slugify_filename(JOB_KEYWORDS)
        clean_loc = slugify_filename(JOB_LOCATION) if JOB_LOCATION else "all"
        filename = f"tenshoku_{clean_kw}_{clean_loc}.csv"

        if all_data:
            print(f"\nSaving {len(all_data)} jobs to: {filename}")
            with open(filename, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=all_data[0].keys())
                writer.writeheader()
                writer.writerows(all_data)
            print(f"\nSaved {len(all_data)} jobs to {filename}")
        else:
            print("\nNo data collected.")

    except Exception as err:
        print(f"Fatal Error: {err}")


if __name__ == "__main__":
    main()
