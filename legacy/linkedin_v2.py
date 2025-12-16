import time
import random
import json
import csv
import os
import platform
import sys
from urllib.parse import quote_plus

# Selenium & Driver Manager
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
JOB_WORKPLACE_TYPE = "remote"
MAX_PAGES_TO_SCRAPE = 1

# --- Browser Configuration ---
HEADLESS = False  
MANUAL_LOGIN = False 

# --- Anti-Bot Settings ---
MIN_DELAY = 2.0
MAX_DELAY = 5.0

# --- Selectors ---
SELECTORS = {
    "scroll_containers": [
        ".jobs-search-results-list",
        ".scaffold-layout__list",
        "div[class*='jobs-search-results-list']"
    ],
    "job_card_list": "div[data-job-id].job-card-container, li.jobs-search-results__list-item",
    "detail_pane": {
        "title": "h1.t-24.t-bold, h2.t-16.t-black.t-bold, div.job-details-jobs-unified-top-card__job-title h1",
        "company_link": "div.job-details-jobs-unified-top-card__company-name a, a.uxvNeZlUzUerxhncQCbPGgMBxUNKqUMfQTIcuo",
        "job_location": "span.tvm__text.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "posted_date": "span.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "description": "div.jobs-box__html-content, div.jobs-description-content__text--stretch, div.jobs-description__content, #job-details"
    }
}

# --- Helper: Human Behavior ---
def random_sleep(min_s=None, max_s=None):
    """Sleeps for a random amount of time."""
    mn = min_s or MIN_DELAY
    mx = max_s or MAX_DELAY
    time.sleep(random.uniform(mn, mx))

def random_mouse_movement(driver):
    """Moves mouse to a random element to trigger hover events."""
    try:
        action = ActionChains(driver)
        # Find some common elements
        elements = driver.find_elements(By.CSS_SELECTOR, "a, p, h2")
        if len(elements) > 2:
            target = random.choice(elements[:4]) # Pick from top visible ones
            action.move_to_element(target).perform()
    except: pass

# --- Browser Setup ---
def setup_driver():
    system_os = platform.system()
    print(f"INFO: Detected OS: {system_os}")

    current_dir = os.getcwd()
    local_profile_path = os.path.join(current_dir, "chrome_profile")
    profile_exists = os.path.exists(local_profile_path)
    
    print(f"INFO: Profile Path: {local_profile_path}")

    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={local_profile_path}")
    
    # Critical Anti-Detection Flags
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--log-level=3")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    should_run_headless = False
    if MANUAL_LOGIN: should_run_headless = False
    elif HEADLESS and system_os == "Linux" and profile_exists: should_run_headless = True
    elif HEADLESS and system_os != "Linux": should_run_headless = True

    if should_run_headless: options.add_argument("--headless=new")

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        sys.exit(1)

# --- Scroll Logic (Keyboard + Jitter) ---
def load_full_job_list(driver):
    """
    Uses Keyboard 'END' key with random pauses.
    """
    print("   -> Loading jobs (Keyboard Scroll)...")
    
    last_count = 0
    max_retries = 3
    retries = 0
    
    # Focus container
    container = None
    for selector in SELECTORS["scroll_containers"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            if el.is_displayed():
                container = el
                break
        except: continue
    
    while True:
        cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
        count = len(cards)
        print(f"      Loaded {count} jobs...")

        if count >= 25:
            print("      ✓ Reached page limit (25).")
            break
            
        if count == last_count:
            retries += 1
            if retries >= max_retries:
                print("      ⚠ Stopped loading.")
                break
        else:
            retries = 0 
            last_count = count

        # Physical Scroll
        try:
            if container:
                # Move mouse over container first
                ActionChains(driver).move_to_element(container).perform()
                random_sleep(0.5, 1.0)
                container.send_keys(Keys.END)
                random_sleep(1.0, 2.0) # Random pause between keypresses
            else:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
        except: pass
        
        time.sleep(2)

# --- Login Check ---
def check_and_ensure_login(driver):
    print("\n=== CHECKING LOGIN STATUS ===")
    driver.get("https://www.linkedin.com/feed/")
    time.sleep(3)
    
    if "feed" in driver.current_url or driver.find_elements(By.CSS_SELECTOR, "nav.global-nav"):
        print("✅ Already logged in using local profile.")
        return True
    
    print("❌ Not logged in. Redirecting...")
    driver.get("https://www.linkedin.com/login")
    print("ACTION REQUIRED: Log In manually -> Press ENTER here when done.")
    input()
    return True

# --- Scraping Logic ---
def scrape_detail_pane(driver, selectors):
    job_data = {
        "company_name": None, "linkedin_company_page": None, "title": None,
        "job_location": None, "posted_date": None, "description": None
    }
    
    # Try multiple selectors for each field
    try:
        el = driver.find_element(By.CSS_SELECTOR, selectors["company_link"])
        job_data['company_name'] = el.text.strip()
        href = el.get_attribute('href')
        if href and '/company/' in href: job_data['linkedin_company_page'] = href.split('?')[0]
    except: pass

    try:
        el = driver.find_element(By.CSS_SELECTOR, selectors["title"])
        job_data['title'] = el.text.strip()
    except: pass

    try:
        el = driver.find_element(By.CSS_SELECTOR, selectors["description"])
        job_data['description'] = " ".join(el.text.split())
    except: pass

    try:
        sub_text = driver.find_element(By.CSS_SELECTOR, "div.job-details-jobs-unified-top-card__primary-description").text
        if sub_text:
            parts = sub_text.split('·')
            if len(parts) > 0: job_data['job_location'] = parts[0].strip()
            if len(parts) > 1: job_data['posted_date'] = parts[1].strip()
    except: pass

    return job_data

def scrape_jobs(driver, url, max_pages):
    driver.get(url)
    all_jobs_data = []
    
    print("Waiting for initial load...")
    random_sleep(3, 6)
    
    # Human-like mouse jitter at start
    random_mouse_movement(driver)

    processed_job_ids = set()
    jobs_processed_count = 0
    
    for page_num in range(1, max_pages + 1):
        print(f"\n--- Scraping Page {page_num} ---")
        
        # 1. LOAD ALL JOBS (Keyboard Method)
        load_full_job_list(driver)
        
        # 2. Collect Cards
        current_job_cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
        print(f"Found {len(current_job_cards)} total cards.")
        
        for i, card in enumerate(current_job_cards):
            # --- HUMAN BREAK LOGIC ---
            if jobs_processed_count > 0 and jobs_processed_count % 12 == 0:
                break_time = random.uniform(8, 15)
                print(f"    ☕ Taking a coffee break for {break_time:.1f}s...")
                time.sleep(break_time)

            try:
                job_id = card.get_attribute('data-job-id')
                if not job_id:
                    try: 
                        href = card.find_element(By.TAG_NAME, "a").get_attribute("href")
                        import re
                        job_id = re.search(r"view/(\d+)", href).group(1)
                    except: pass

                if not job_id or job_id in processed_job_ids:
                    continue

                print(f"[{jobs_processed_count + 1}/{len(current_job_cards)}] ID: {job_id}")
                
                # Scroll to card with offset (don't put it exactly at top every time)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", card)
                random_sleep(0.5, 1.2)
                
                # Click
                try: card.click()
                except: driver.execute_script("arguments[0].click();", card)
                
                processed_job_ids.add(job_id)
                jobs_processed_count += 1
                
                # Wait for detail loading (randomized)
                random_sleep(1.5, 3.5)
                
                # Expand Description (Optional, V1 style)
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Show more']")
                    driver.execute_script("arguments[0].click();", btn)
                    random_sleep(0.3, 0.7)
                except: pass

                # Scrape
                details = scrape_detail_pane(driver, SELECTORS["detail_pane"])
                details['linkedin_job_id'] = job_id
                
                if details['title']:
                    all_jobs_data.append(details)
                    print(f"   -> Scraped: {details['title']}")
            
            except: continue
        
        # Pagination
        if page_num < max_pages:
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='View next page']")
                if next_btn.is_enabled():
                    # Move to button first
                    ActionChains(driver).move_to_element(next_btn).perform()
                    random_sleep(0.5, 1.0)
                    next_btn.click()
                    print("Moving to next page...")
                    random_sleep(4, 7)
                else: break
            except:
                print("No next button found.")
                break

    return all_jobs_data

def save_to_csv(data, filename):
    if not data: return
    fieldnames = ['linkedin_job_id', 'company_name', 'linkedin_company_page', 'title', 'job_location', 'posted_date', 'salary', 'description']
    
    existing_ids = set()
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f): existing_ids.add(row.get('linkedin_job_id'))
        except: pass
    
    new_rows = [r for r in data if r.get('linkedin_job_id') not in existing_ids]
    
    if new_rows:
        mode = 'a' if os.path.exists(filename) else 'w'
        with open(filename, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if mode == 'w': writer.writeheader()
            writer.writerows(new_rows)
        print(f"✓ Saved {len(new_rows)} new jobs.")
    else:
        print("No new jobs to save.")

# --- Main ---
def main():
    driver = setup_driver()
    try:
        check_and_ensure_login(driver)
        
        WORKPLACE_FILTER_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
        base_url = "https://www.linkedin.com/jobs/search/"
        encoded_keywords = quote_plus(JOB_KEYWORDS)
        encoded_location = quote_plus(JOB_LOCATION)
        SEARCH_URL = f"{base_url}?keywords={encoded_keywords}&location={encoded_location}"
        if JOB_WORKPLACE_TYPE in WORKPLACE_FILTER_CODES:
            SEARCH_URL += f"&f_WT={WORKPLACE_FILTER_CODES[JOB_WORKPLACE_TYPE]}"

        results = scrape_jobs(driver, SEARCH_URL, MAX_PAGES_TO_SCRAPE)
        
        csv_name = f"linkedin_{JOB_KEYWORDS.replace(' ', '_')}_{JOB_LOCATION.replace(' ', '_')}.csv"
        save_to_csv(results, csv_name)

    except Exception as e:
        print(f"Fatal Error: {e}")
    finally:
        print("Closing browser...")
        driver.quit()

if __name__ == "__main__":
    main()