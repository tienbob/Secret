import csv
import json
import os
import re
import sys
import time
import platform
import random
from typing import Optional

# Selenium & Driver Manager
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails" 
JOB_LOCATION = ""       
JOB_SENIORITY = "" # e.g. "Senior", "Junior"

# --- Scraper Settings ---
MAX_PAGES_TO_SCRAPE = 3        # <--- UPDATED: Set how many pages to scrape
HEADLESS = False               # False = Safer (Browser visible)
MIN_DELAY = 3.0                # Minimum seconds to wait between actions
MAX_DELAY = 6.0                # Maximum seconds to wait between actions
PAGE_LOAD_TIMEOUT = 30         # Maximum seconds to wait for page load
SCRIPT_TIMEOUT = 30            # Maximum seconds for script execution

# --- URL Logic ---
def slugify(text: str) -> str:
    if not text: return ""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def construct_search_url():
    base = "https://rubyonremote.com"
    parts = []
    if JOB_SENIORITY: parts.append(slugify(JOB_SENIORITY))
    parts.append("remote")
    if JOB_KEYWORDS: parts.append(slugify(JOB_KEYWORDS))
    parts.append("jobs")
    if JOB_LOCATION:
        parts.append("in")
        parts.append(slugify(JOB_LOCATION))
    
    final_url = f"{base}/{'-'.join(parts)}/"
    print(f"INFO: Generated Search URL: {final_url}")
    return final_url

# --- Helper: Human Behavior ---
def random_sleep(min_s=None, max_s=None):
    """Sleeps for a random amount of time to mimic human processing."""
    mn = min_s or MIN_DELAY
    mx = max_s or MAX_DELAY
    sleep_time = random.uniform(mn, mx)
    # print(f"    (Waiting {sleep_time:.1f}s...)")
    time.sleep(sleep_time)

def human_scroll(driver):
    """Scrolls the page like a human (smoothly, with pauses)."""
    total_height = int(driver.execute_script("return document.body.scrollHeight"))
    current_position = 0
    
    # Don't scroll infinitely if page is huge, just enough to trigger loads
    while current_position < total_height:
        scroll_step = random.randint(300, 700)
        current_position += scroll_step
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(random.uniform(0.2, 0.5))
        
        if current_position >= total_height:
            break

def random_mouse_movement(driver):
    """Simulates random mouse movements to trigger hover events."""
    try:
        action = ActionChains(driver)
        elements = driver.find_elements(By.TAG_NAME, 'a')
        if len(elements) > 2:
            target = random.choice(elements[:5])
            action.move_to_element(target).perform()
    except: pass

# --- Browser Setup ---
def setup_driver():
    """Robust, Anti-Detection Driver Setup."""
    system_os = platform.system()
    print(f"INFO: Detected OS: {system_os}")
    
    def add_stealth_args(opts):
        opts.add_argument("--window-size=1280,1024")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--log-level=3")
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        if HEADLESS: opts.add_argument("--headless=new")

    try:
        print("INFO: Initializing Chrome...")
        options = ChromeOptions()
        add_stealth_args(options)
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # Set timeouts
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        driver.implicitly_wait(10)
        
        return driver
    except Exception:
        print("WARNING: Chrome failed. Falling back to Edge...")

    try:
        options = EdgeOptions()
        add_stealth_args(options)
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)
        
        # Set timeouts
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        driver.implicitly_wait(10)
        
        return driver
    except Exception as e:
        print(f"CRITICAL: Failed to initialize any browser. {e}")
        sys.exit(1)

# --- Helper: Clean Text ---
def clean_text(text: Optional[str]) -> Optional[str]:
    if not text: return None
    return " ".join(text.split())

def extract_id_from_url(url: str) -> Optional[str]:
    match = re.search(r"/jobs/(\d+)-", url)
    return match.group(1) if match else None

# --- Phase 1: List Scraper (With Pagination) ---
def collect_all_job_links(driver, start_url, max_pages):
    """
    Navigates through pages 1..max_pages and collects all job links.
    """
    print(f"\n--- Starting Job Scan (Max Pages: {max_pages}) ---")
    
    try:
        driver.get(start_url)
    except TimeoutException:
        print("WARNING: Page load timeout. Continuing anyway...")
    
    all_links = []
    
    for page_num in range(1, max_pages + 1):
        print(f"\n--- Scanning Page {page_num} of {max_pages} ---")
        
        # 1. Random Wait & Check Validity
        random_sleep(2, 4)
        if "Page not found" in driver.title:
            print("❌ Page not found. Stopping pagination.")
            break

        # 2. Wait for Jobs
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li a[href^='/jobs/']"))
            )
        except TimeoutException:
            print("❌ No jobs found on this page. Stopping.")
            break

        # 3. Human Scroll (Triggers lazy load images, looks natural)
        human_scroll(driver)

        # 4. Extract Links
        cards = driver.find_elements(By.CSS_SELECTOR, "li a[href^='/jobs/']")
        page_count = 0
        for card in cards:
            try:
                href = card.get_attribute("href")
                try: title = card.find_element(By.CSS_SELECTOR, "h2").text
                except: title = "Unknown"
                
                # Deduplicate based on URL in current batch
                if not any(d['url'] == href for d in all_links):
                    all_links.append({
                        "url": href,
                        "title_preview": clean_text(title),
                        "rubyonremote_id": extract_id_from_url(href)
                    })
                    page_count += 1
            except: continue
            
        print(f"✓ Found {page_count} new jobs on page {page_num}. (Total: {len(all_links)})")

        # 5. Handle Next Page
        if page_num < max_pages:
            try:
                # Based on your HTML: <a href="..." rel="next" aria-label="next">
                next_btn = driver.find_element(By.CSS_SELECTOR, "a[rel='next'], a[aria-label='next']")
                
                # Scroll to it
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(random.uniform(0.5, 1.5))
                
                print("➡ Clicking 'Next' button...")
                next_btn.click()
                
            except NoSuchElementException:
                print("⚠ No 'Next' button found. Reached last page.")
                break
            except Exception as e:
                print(f"⚠ Error navigating to next page: {e}")
                break
    
    return all_links

# --- Phase 2: Detail Scraper ---
def scrape_detail_page(driver, job_entry):
    url = job_entry['url']
    
    try:
        driver.get(url)
    except TimeoutException:
        print(f"WARNING: Timeout loading {url}. Skipping...")
        return None
    
    random_sleep(2.0, 4.0)
    random_mouse_movement(driver)
    
    data = {
        "rubyonremote_id": job_entry['rubyonremote_id'],
        "full_title": job_entry['title_preview'],
        "company_name": None,
        "posted_date": None,
        "apply_link": None,
        "company_website": None,
        "tags": [],
        "full_description": None,
        "url": url
    }

    try:
        wait = WebDriverWait(driver, 8)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.schema-job-title")))

        # Title
        data['full_title'] = clean_text(driver.find_element(By.CSS_SELECTOR, "h1.schema-job-title").text)

        # Company Info
        try:
            sidebar = driver.find_element(By.CSS_SELECTOR, "div.rounded-lg.shadow-sm")
            data['company_name'] = clean_text(sidebar.find_element(By.CSS_SELECTOR, "h3").text)
            for link in sidebar.find_elements(By.TAG_NAME, "a"):
                href = link.get_attribute("href")
                if href and "http" in href and "rubyonremote" not in href and "twitter" not in href:
                    data['company_website'] = href
                    break
        except: pass

        # Apply Link
        try:
            apply_btn = driver.find_element(By.CSS_SELECTOR, "a#apply_link")
            data['apply_link'] = apply_btn.get_attribute("href")
        except:
            data['apply_link'] = "Not Found"

        # Tags
        tags = driver.find_elements(By.CSS_SELECTOR, ".job-tags")
        tag_list = []
        for tag in tags:
            txt = clean_text(tag.text)
            if txt and "Featured" not in txt and "✨" not in txt:
                tag_list.append(txt)
        data['tags'] = ", ".join(tag_list)

        # Date
        try:
            date_el = driver.find_element(By.XPATH, "//h2[contains(text(), 'Published on')]")
            data['posted_date'] = date_el.text.replace("Published on", "").strip()
        except: pass

        # Description
        try:
            desc_el = driver.find_element(By.CSS_SELECTOR, "div.schema-job-description")
            data['full_description'] = clean_text(desc_el.text)
        except: pass

    except Exception:
        pass 

    return data

# --- Saver ---
def save_to_csv(data_list, filename):
    if not data_list: return
    
    fieldnames = [
        "rubyonremote_id", "full_title", "company_name", "posted_date", 
        "tags", "apply_link", "company_website", "url", "full_description"
    ]
    
    existing_ids = set()
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("rubyonremote_id"):
                        existing_ids.add(row["rubyonremote_id"])
        except: pass

    new_rows = [r for r in data_list if r.get("rubyonremote_id") not in existing_ids]

    if new_rows:
        mode = 'a' if os.path.exists(filename) else 'w'
        with open(filename, mode, newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if mode == 'w': writer.writeheader()
            writer.writerows(new_rows)
        print(f"✓ Saved {len(new_rows)} new jobs to {filename}")
    else:
        print("No new jobs to save.")

# --- Main ---
def main():
    driver = setup_driver()
    
    try:
        # Phase 1: Collect Links (Recursive)
        search_url = construct_search_url()
        job_links = collect_all_job_links(driver, search_url, MAX_PAGES_TO_SCRAPE)
        
        if not job_links:
            return

        # Phase 2: Process Details
        print(f"\n--- Extracting Details for {len(job_links)} Jobs ---")
        full_results = []
        
        for i, job in enumerate(job_links):
            print(f"[{i+1}/{len(job_links)}] {job['title_preview']}")
            
            detail = scrape_detail_page(driver, job)
            full_results.append(detail)
            
            # Anti-Bot Delay between jobs
            if i < len(job_links) - 1:
                random_sleep(MIN_DELAY, MAX_DELAY)
        
        # Save
        clean_kw = slugify(JOB_KEYWORDS)
        clean_loc = slugify(JOB_LOCATION)
        filename = f"rubyonremote_{clean_kw}_{clean_loc}.csv"
        
        save_to_csv(full_results, filename)

    finally:
        print("\nClosing browser...")
        driver.quit()

if __name__ == "__main__":
    main()