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
JOB_WORKPLACE_TYPE = "remote"
MAX_PAGES_TO_SCRAPE = 1
HEADLESS = False  

# --- Selectors ---
SELECTORS = {
    "job_card_list": "div[data-job-id].job-card-container, li.jobs-search-results__list-item",
    "detail_pane": {
        "title": "h1.t-24.t-bold, h2.t-16.t-black.t-bold, div.job-details-jobs-unified-top-card__job-title h1",
        "company_link": "div.job-details-jobs-unified-top-card__company-name a, a.uxvNeZlUzUerxhncQCbPGgMBxUNKqUMfQTIcuo",
        "job_location": "span.tvm__text.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "posted_date": "span.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
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
            print("❌ Not logged in. Please run without headless mode once to login.")
            driver.quit()
            return

        # Build URL
        WORKPLACE_FILTER_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
        base = "https://www.linkedin.com/jobs/search/"
        url = f"{base}?keywords={quote_plus(JOB_KEYWORDS)}&location={quote_plus(JOB_LOCATION)}"
        if JOB_WORKPLACE_TYPE in WORKPLACE_FILTER_CODES:
            url += f"&f_WT={WORKPLACE_FILTER_CODES[JOB_WORKPLACE_TYPE]}"

        driver.get(url)
        all_data = []
        processed = set()

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
                    
                    # Scroll sidebar to card to ensure it's clickable
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                    time.sleep(0.2)
                    
                    try: card.click()
                    except: driver.execute_script("arguments[0].click();", card)
                    
                    processed.add(job_id)
                    # Scrape
                    details = {"linkedin_job_id": job_id}
                    for k, v in SELECTORS["detail_pane"].items():
                        try:
                            el = driver.find_element(By.CSS_SELECTOR, v)
                            details[k] = " ".join(el.text.split())
                        except: details[k] = None
                    
                    if details.get('title'):
                        all_data.append(details)
                        print(f"   -> Scraped: {details['title']}")
                except: continue
            
            # Next Page
            if page < MAX_PAGES_TO_SCRAPE:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='View next page']")
                    if btn.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        btn.click()
                        time.sleep(4)
                    else: break
                except: break

        # Save
        clean_kw = JOB_KEYWORDS.replace(" ", "_")
        clean_loc = JOB_LOCATION.replace(" ", "_")
        
        # Ensure filename is safe
        filename = f"linkedin_{clean_kw[:20]}_{clean_loc[:20]}.csv"
        keys = ['linkedin_job_id', 'company_link', 'title', 'company_name', 'job_location', 'posted_date', 'salary_info', 'description']
        
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