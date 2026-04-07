import csv
import json
import os
import re
import sys
import time
import platform
import subprocess
import random
from urllib.parse import quote_plus

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.selenium_manager import SeleniumManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails" 
JOB_LOCATION = "Vietnam"       
MAX_PAGES_TO_SCRAPE = 3  # Set this to > 1 to test pagination
HEADLESS = False
BROWSER = "brave"  # Options: chrome, brave
BRAVE_BINARY_PATH = ""
USER_AGENT = ""
RUN_TIMESTAMP = ""

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

    if HEADLESS: options.add_argument("--headless=new")

    try:
        sm_args = ["--browser", "chrome"]
        if browser == "brave":
            sm_args.extend(["--browser-path", options.binary_location])

        sm_result = SeleniumManager().binary_paths(sm_args)
        service = ChromeService(sm_result["driver_path"])
        driver = webdriver.Chrome(service=service, options=options)
        print(f"Browser mode: {browser}")
        return driver
    except Exception as e:
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

# --- Helper ---
def clean_text(text):
    if not text: return None
    return " ".join(text.split())


def export_run_timestamp():
    return RUN_TIMESTAMP or time.strftime("%Y-%m-%dT%H:%M:%S%z")


def extract_company_website(driver, current_url):
    try:
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
        for anchor in anchors:
            href = anchor.get_attribute("href")
            if href and "rubyonremote.com" not in href and href != current_url:
                return href
    except Exception:
        return None
    return None

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
                    "scrape_run_at": export_run_timestamp(),
                    "url": url,
                    "title": None,
                    "company": None,
                    "company_website": None,
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

                data['company_website'] = extract_company_website(driver, url)
                
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
        clean_kw = JOB_KEYWORDS.replace(" ", "_").replace("/", "-")
        clean_loc = JOB_LOCATION.replace(" ", "_").replace("/", "-")
        
        # Format: rubyonremote_KEYWORDS_LOCATION.csv
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
        if driver: driver.quit()

if __name__ == "__main__":
    main()