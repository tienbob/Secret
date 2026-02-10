import time
import random
import json
import csv
import os
import platform
import sys
from urllib.parse import quote_plus

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
JOB_WORKPLACE_TYPE = "remote"  # Options: on-site, remote, hybrid
INDUSTRY_FILTER = ""  # LinkedIn industry code (e.g., 4 = Computer Software, leave empty for all)
TIME_POSTED_FILTER = ""  # Last X days (e.g., r2592000 = 30 days, r604800 = 7 days, leave empty for all)
SORT_BY = ""  # R = Most Recent, DD = Date Posted, leave empty for relevance
MAX_PAGES_TO_SCRAPE = 1
HEADLESS = False  

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

# --- Browser Setup ---
def setup_driver():
    current_dir = os.getcwd()
    local_profile_path = os.path.join(current_dir, "chrome_profile")
    
    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={local_profile_path}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--log-level=3")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    if HEADLESS and os.path.exists(local_profile_path):
        options.add_argument("--headless=new")

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1)

# --- Scroll Logic (The Fix) ---
def load_full_job_list(driver):
    print("   -> Loading jobs (Dynamic JS Scroll)...")
    
    # 1. Zoom out to fit more items (Triggers lazy load easier)
    try:
        driver.execute_script("document.body.style.zoom = '80%'")
    except: pass

    last_count = 0
    retries = 0
    max_retries = 4

    while True:
        # 2. Get current cards
        cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
        count = len(cards)
        print(f"      Loaded {count} jobs...")

        if count >= 25 or (count == last_count and retries >= max_retries):
            # Reset zoom before exiting
            try: driver.execute_script("document.body.style.zoom = '100%'")
            except: pass
            break
            
        if count == last_count:
            retries += 1
        else:
            retries = 0
            last_count = count

        # 3. AGGRESSIVE SCROLLING STRATEGY
        try:
            # Strategy A: Find the parent of the first card (the real container) and scroll IT
            if cards:
                # Get the container of the cards
                driver.execute_script("""
                    var card = arguments[0];
                    var container = card.parentElement;
                    // Scroll container to bottom
                    container.scrollTop = container.scrollHeight;
                    // Also scroll window just in case
                    window.scrollTo(0, document.body.scrollHeight);
                """, cards[0])
            
            # Strategy B: Scroll the last card into view
            if cards:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", cards[-1])
            
        except Exception as e:
            # Strategy C: Blindly scroll known classes
            driver.execute_script("""
                var targets = document.querySelectorAll('.jobs-search-results-list, .scaffold-layout__list');
                targets.forEach(t => t.scrollTop = t.scrollHeight);
            """)

        time.sleep(3) # Wait for network

# --- Main Logic ---
def clean_text(text):
    if not text: return None
    return " ".join(text.split())

def main():
    driver = setup_driver()
    try:
        # Check Login
        driver.get("https://www.linkedin.com/feed/")
        if "login" in driver.current_url:
            print("Not logged in. Please log in manually in the opened browser window.")
            print("Waiting up to 300 seconds for login...")
            logged_in = False
            for _ in range(300):
                time.sleep(1)
                if "login" not in driver.current_url:
                    logged_in = True
                    break
            if not logged_in:
                print("Login not detected after 300 seconds. Exiting.")
                driver.quit()
                return

        # Build URL with filters - Based on LinkedIn's URL structure
        WORKPLACE_FILTER_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
        # Common LinkedIn geoIds
        GEO_ID_MAP = {
            "Europe": "100506914",  # Entire Europe region
            "European Union": "100506914",  # Same as Europe
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
        
        # Add workplace type filter (f_WT)
        if JOB_WORKPLACE_TYPE in WORKPLACE_FILTER_CODES:
            params.append(f"f_WT={WORKPLACE_FILTER_CODES[JOB_WORKPLACE_TYPE]}")
        
        # Add location as geoId (more accurate than location parameter)
        if JOB_LOCATION in GEO_ID_MAP:
            params.append(f"geoId={GEO_ID_MAP[JOB_LOCATION]}")
        else:
            # Fallback to location parameter if geoId not found
            params.append(f"location={quote_plus(JOB_LOCATION)}")
        
        # Add keywords with quotes for exact phrase matching
        # %22 is the URL-encoded double quote character
        params.append(f'keywords=%22{quote_plus(JOB_KEYWORDS)}%22')
        
        # Add industry filter (optional)
        if INDUSTRY_FILTER:
            params.append(f"f_I={INDUSTRY_FILTER}")
        
        # Add time posted filter (optional)
        if TIME_POSTED_FILTER:
            params.append(f"f_TPR={TIME_POSTED_FILTER}")
        
        # Add sort order (optional)
        if SORT_BY:
            params.append(f"sortBy={SORT_BY}")
        
        # Add origin and refresh
        params.append("origin=JOB_SEARCH_PAGE_LOCATION_HISTORY")
        params.append("refresh=true")
        
        url = base + "?" + "&".join(params)
        print(f"Search URL: {url}")
        
        driver.get(url)
        all_data = []
        processed = set()
        seen_jobs = set()  # Track (title, company) combinations to avoid duplicates

        for page in range(1, MAX_PAGES_TO_SCRAPE + 1):
            print(f"--- Scraping Page {page} ---")
            
            # Use the new robust loader
            load_full_job_list(driver)
            
            cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
            
            for i, card in enumerate(cards):
                try:
                    job_id = card.get_attribute("data-job-id")
                    if not job_id: 
                        try: job_id = card.find_element(By.TAG_NAME, "a").get_attribute("href").split("view/")[1].split("/")[0]
                        except: pass
                    
                    if not job_id or job_id in processed: continue
                    
                    # Anti-bot random wait
                    rand_wait = random.uniform(1.5, 4.5)
                    time.sleep(rand_wait)
                    
                    # Scroll sidebar to card to ensure it's clickable
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                    time.sleep(0.2)
                    
                    try: card.click()
                    except: driver.execute_script("arguments[0].click();", card)
                    
                    # Wait for detail pane to load
                    time.sleep(1)
                    
                    processed.add(job_id)
                    
                    # Scrape details
                    details = {"linkedin_job_id": job_id}
                    
                    # Get title
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, SELECTORS["detail_pane"]["title"])
                        details["title"] = " ".join(el.text.split())
                    except: details["title"] = None
                    
                    # Get company name
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, SELECTORS["detail_pane"]["company_name"])
                        details["company_name"] = " ".join(el.text.split())
                    except: details["company_name"] = None
                    
                    # Get location (first tvm__text span)
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, SELECTORS["detail_pane"]["job_location"])
                        details["job_location"] = " ".join(els[0].text.split()) if els else None
                    except: details["job_location"] = None
                    
                    # Get posted date (usually second or third tvm__text span)
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, SELECTORS["detail_pane"]["posted_date"])
                        # Look for the one containing "ago" or "Reposted"
                        posted = None
                        for el in els:
                            text = el.text.strip()
                            if "ago" in text.lower() or "reposted" in text.lower():
                                posted = " ".join(text.split())
                                break
                        details["posted_date"] = posted
                    except: details["posted_date"] = None
                    
                    # Get salary info (ignore non-salary badges like Remote/Full-time)
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, SELECTORS["detail_pane"]["salary_info"])
                        salary_text = " ".join(el.text.split())
                        lower_text = salary_text.lower()

                        has_digits = any(ch.isdigit() for ch in salary_text)
                        salary_markers = ["$", "£", "€", "¥", "usd", "eur", "gbp", "/yr", "/year", "/hr", "/hour", "per", "k"]
                        has_marker = any(marker in lower_text for marker in salary_markers)

                        if salary_text and has_digits and has_marker:
                            details["salary_info"] = salary_text
                        else:
                            details["salary_info"] = None
                    except: details["salary_info"] = None
                    
                    # Get description
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, SELECTORS["detail_pane"]["description"])
                        details["description"] = " ".join(el.text.split())
                    except: details["description"] = None
                    
                    if details.get('title'):
                        # Extract company name for duplicate checking
                        company_name = details.get('company_name', '')
                        
                        # Create unique key (title, company)
                        job_key = (details['title'].lower().strip(), 
                                   company_name.lower().strip() if company_name else "")
                        
                        # Check for duplicates
                        if job_key in seen_jobs:
                            print(f"   -> Skipped duplicate: {details['title']} at {company_name or 'Unknown'}")
                            continue
                        
                        # Mark as seen and add to results
                        seen_jobs.add(job_key)
                        all_data.append(details)
                        print(f"   -> Scraped: {details['title']} at {company_name or 'Unknown'}")
                except: continue
            
            # Next Page
            if page < MAX_PAGES_TO_SCRAPE:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='View next page']")
                    if btn.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        btn.click()
                        time.sleep(5)  # Wait 5s when changing page
                    else: break
                except: break

        # Save
        clean_kw = JOB_KEYWORDS.replace(" ", "_").replace("/", "-")
        clean_loc = JOB_LOCATION.replace(" ", "_").replace("/", "-")
        
        # Format: linkedin_KEYWORDS_LOCATION.csv
        filename = f"linkedin_{clean_kw}_{clean_loc}.csv"
        keys = ['linkedin_job_id', 'company_name', 'title', 'job_location', 'posted_date', 'salary_info', 'description']
        
        print(f"\n💾 Saving {len(all_data)} jobs to: {filename}")
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(all_data)

    except Exception as e:
        print(f"Fatal Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()