import csv
import html
import json
import re
import time
from urllib.parse import urlencode, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
MAX_PAGES_TO_SCRAPE = 3
RUN_TIMESTAMP = ""
SORT_BY = "published_at desc"


def slugify_filename(text):
    if not text:
        return ""
    return text.replace(" ", "_").replace("/", "-")


def clean_text(text):
    if not text:
        return None
    return " ".join(str(text).split())


def strip_tags(text):
    if not text:
        return ""
    return clean_text(BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True))


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def should_enforce_location_filter(location):
    if not location:
        return False
    return location.strip().lower() not in {"japan", "jp", "日本"}


def seems_location_match(text, location):
    if not location:
        return True
    if not text:
        return False
    return location.lower() in str(text).lower()


def default_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }


def build_search_url(page_num):
    params = {
        "q[freeword]": JOB_KEYWORDS,
        "q[sort]": SORT_BY,
        "q[yearly_base_salaly_min_value]": "",
    }
    if page_num > 1:
        params["page"] = page_num
    return f"https://jobs.forkwell.com/jobs/search?{urlencode(params, quote_via=quote_plus)}"


def extract_salary_text(card_soup):
    salary_label = card_soup.find("span", string=re.compile(r"年収"))
    if not salary_label:
        return ""

    list_item = salary_label.find_parent("li")
    if not list_item:
        return ""

    return clean_text(list_item.get_text(" ", strip=True).replace(" 年収", "")) or ""


def parse_listing_page(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    cards = soup.select("div.job-list > div.card")

    jobs = []
    for card in cards:
        title_anchor = card.select_one("a.job-list__link")
        if not title_anchor:
            continue

        detail_href = title_anchor.get("href")
        if not detail_href:
            continue

        detail_url = urljoin("https://jobs.forkwell.com", detail_href)
        title = clean_text(title_anchor.get_text(" ", strip=True))

        company = ""
        company_link = card.select_one("a.link-inherit[href]:not([href*='/jobs/']) .avatar__detail")
        if company_link:
            company = clean_text(company_link.get_text(" ", strip=True)) or ""

        location = ""
        map_icon = card.select_one("i.fa-map-marker-alt")
        if map_icon and map_icon.parent:
            location = clean_text(map_icon.parent.get_text(" ", strip=True)) or ""

        updated_text = ""
        footer_clock = card.select_one(".card-footer .text-muted")
        if footer_clock:
            updated_text = clean_text(footer_clock.get_text(" ", strip=True)) or ""

        jobs.append(
            {
                "url": detail_url,
                "title": title,
                "company": company,
                "location": location,
                "salary_info": extract_salary_text(card),
                "listing_updated_text": updated_text,
            }
        )

    has_next = soup.select_one("li.page-item.next a[rel='next']") is not None
    return jobs, has_next


def parse_jobposting_ldjson(detail_html):
    soup = BeautifulSoup(detail_html, "html.parser")
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


def extract_detail_data(url, listing_fallback, session):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    ld = parse_jobposting_ldjson(response.text)

    job_id = ""
    id_match = re.search(r"/jobs/(\d+)", url)
    if id_match:
        job_id = id_match.group(1)

    company = listing_fallback.get("company", "")
    company_website = ""
    hiring_org = ld.get("hiringOrganization") if isinstance(ld, dict) else {}
    if isinstance(hiring_org, dict):
        company = clean_text(hiring_org.get("name")) or company
        same_as = hiring_org.get("sameAs")
        if isinstance(same_as, list):
            company_website = clean_text(next((x for x in same_as if isinstance(x, str) and x.startswith("http")), "")) or ""
        elif isinstance(same_as, str):
            company_website = clean_text(same_as) or ""

    address_region = ""
    job_location = ld.get("jobLocation") if isinstance(ld, dict) else {}
    if isinstance(job_location, list) and job_location:
        job_location = job_location[0]
    if isinstance(job_location, dict):
        address = job_location.get("address")
        if isinstance(address, dict):
            address_region = clean_text(address.get("addressRegion")) or ""

    salary_info = listing_fallback.get("salary_info", "")
    base_salary = ld.get("baseSalary") if isinstance(ld, dict) else {}
    if isinstance(base_salary, dict):
        value = base_salary.get("value")
        if isinstance(value, dict):
            min_value = value.get("minValue")
            max_value = value.get("maxValue")
            if min_value is not None and max_value is not None:
                salary_info = f"{int(min_value):,} JPY - {int(max_value):,} JPY"

    description = ""
    if isinstance(ld, dict):
        description = strip_tags(ld.get("description")) or ""

    title = clean_text(ld.get("title")) if isinstance(ld, dict) else ""
    if not title:
        title = listing_fallback.get("title") or ""

    return {
        "source_job_id": job_id,
        "forkwell_job_id": job_id,
        "scrape_run_at": export_run_timestamp(),
        "url": url,
        "title": title,
        "company": company,
        "company_website": company_website,
        "date": clean_text(ld.get("datePosted")) if isinstance(ld, dict) else "",
        "location": address_region or listing_fallback.get("location", ""),
        "salary_info": salary_info,
        "description": description,
        "keywords": JOB_KEYWORDS,
        "location_filter": JOB_LOCATION,
        "listing_updated_text": listing_fallback.get("listing_updated_text", ""),
    }


def main():
    session = requests.Session()
    session.headers.update(default_headers())

    try:
        print("Scanning Forkwell listings...")

        listing_by_url = {}
        ordered_urls = []

        for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
            list_url = build_search_url(page_num)
            print(f"--- Collecting URLs: Page {page_num} ---")
            print(f"URL: {list_url}")

            response = session.get(list_url, timeout=30)
            response.raise_for_status()

            jobs, has_next = parse_listing_page(response.text)
            new_count = 0

            for job in jobs:
                url = job["url"]
                if url not in listing_by_url:
                    listing_by_url[url] = job
                    ordered_urls.append(url)
                    new_count += 1

            print(f"   Found {new_count} new jobs on this page.")

            if new_count == 0:
                print("   No new jobs found. Stopping pagination.")
                break
            if not has_next:
                print("   No next page found. Stopping pagination.")
                break

        print(f"\nTotal unique jobs found: {len(ordered_urls)}")
        print("Extracting details...")

        all_data = []
        for index, detail_url in enumerate(ordered_urls, start=1):
            try:
                item = extract_detail_data(detail_url, listing_by_url[detail_url], session)

                if should_enforce_location_filter(JOB_LOCATION):
                    if not (
                        seems_location_match(item.get("location"), JOB_LOCATION)
                        or seems_location_match(item.get("title"), JOB_LOCATION)
                        or seems_location_match(item.get("description"), JOB_LOCATION)
                    ):
                        print(f"[{index}/{len(ordered_urls)}] Skipped location mismatch: {detail_url}")
                        continue

                if item.get("title"):
                    print(f"[{index}/{len(ordered_urls)}] Scraped: {item['title'][:80]}")
                    all_data.append(item)
                else:
                    print(f"[{index}/{len(ordered_urls)}] Skipped (No Title): {detail_url}")

                time.sleep(0.2)
            except Exception as err:
                print(f"Error processing {detail_url}: {err}")
                continue

        clean_kw = slugify_filename(JOB_KEYWORDS)
        clean_loc = slugify_filename(JOB_LOCATION) if JOB_LOCATION else "all"
        filename = f"forkwell_{clean_kw}_{clean_loc}.csv"

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