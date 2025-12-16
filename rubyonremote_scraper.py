import csv
import json
import os
import re
import sys
import time
import platform
import random
from urllib.parse import quote_plus

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails" 
JOB_LOCATION = "Vietnam"       
MAX_PAGES_TO_SCRAPE = 3  # Set this to > 1 to test pagination
HEADLESS = False

# --- URL Logic ---
def slugify(text):
    if not text: return ""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def construct_search_url():
    base = "https://rubyonremote.com"
    parts = ["remote", slugify(JOB_KEYWORDS), "jobs"]
    if JOB_LOCATION:
        parts.extend(["in", slugify(JOB_LOCATION)])
    return f"{base}/{'-'.join(parts)}/"

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
    if HEADLESS: options.add_argument("--headless=new")

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)

# --- Helper ---
def clean_text(text):
    if not text: return None
    return " ".join(text.split())

# --- Main Logic ---
def main():
    driver = setup_driver()
    try:
        search_url = construct_search_url()
        print(f"Scanning: {search_url}")
        
        # Phase 1: Collect Links across Multiple Pages
        driver.get(search_url)
        time.sleep(3)
        
        all_links = []
        
        for page_num in range(1, MAX_PAGES_TO_SCRAPE + 1):
            print(f"--- Collecting Links: Page {page_num} ---")
            
            # Scroll to trigger lazy loading
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/1.5);")
            time.sleep(1.5)
            
            # Grab job cards
            cards = driver.find_elements(By.CSS_SELECTOR, "li a[href^='/jobs/']")
            new_count = 0
            for card in cards:
                try: 
                    url = card.get_attribute("href")
                    if url and url not in all_links:
                        all_links.append(url)
                        new_count += 1
                except: pass
            
            print(f"   Found {new_count} new jobs on this page.")
            
            # Pagination Logic
            if page_num < MAX_PAGES_TO_SCRAPE:
                try:
                    # Look for the 'Next' button specifically using rel="next"
                    next_btn = driver.find_element(By.CSS_SELECTOR, "a[rel='next']")
                    next_url = next_btn.get_attribute("href")
                    
                    if next_url:
                        print(f"   Navigating to Page {page_num + 1}...")
                        driver.get(next_url)
                        time.sleep(3) # Wait for page load
                    else:
                        print("   'Next' button found but has no link. Stopping.")
                        break
                except:
                    print("   No 'Next' button found. Reached last page.")
                    break
            
        # Phase 2: Details Extraction
        print(f"\nTotal unique jobs found: {len(all_links)}")
        print("Extracting details...")
        
        all_data = []
        
        for i, url in enumerate(all_links):
            try:
                driver.get(url)
                time.sleep(1) # Polite delay
                
                # Extract ID
                job_id_match = re.search(r"/jobs/(\d+)-", url)
                job_id = job_id_match.group(1) if job_id_match else "unknown"
                
                data = {
                    "rubyonremote_job_id": job_id,
                    "url": url,
                    "title": None,
                    "company": None,
                    "date": None,
                    "description": None
                }
                
                # Scrape Title
                try: 
                    data['title'] = clean_text(driver.find_element(By.CSS_SELECTOR, "h1.schema-job-title").text)
                except: pass
                
                # Scrape Company
                try: 
                    data['company'] = clean_text(driver.find_element(By.CSS_SELECTOR, "div.rounded-lg h3").text)
                except: pass
                
                # Scrape Date
                try: 
                    date_el = driver.find_element(By.XPATH, "//h2[contains(text(), 'Published on')]")
                    data['date'] = clean_text(date_el.text.replace("Published on", ""))
                except: pass
                
                # Scrape Description
                try:
                    desc_el = driver.find_element(By.CSS_SELECTOR, "div.schema-job-description")
                    data['description'] = clean_text(desc_el.text)
                except: pass

                if data['title']:
                    print(f"[{i+1}/{len(all_links)}] Scraped: {data['title']}")
                    all_data.append(data)
                else:
                    print(f"[{i+1}/{len(all_links)}] Skipped (No Title): {url}")

            except Exception as e:
                print(f"Error processing {url}: {e}")
                continue
            
        # Save
        clean_kw = slugify(JOB_KEYWORDS)
        clean_loc = slugify(JOB_LOCATION)
        filename = f"rubyonremote_{clean_kw}_{clean_loc}.csv"
        
        if all_data:
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
        if driver: driver.quit()

if __name__ == "__main__":
    main()