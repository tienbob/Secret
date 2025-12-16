import time
import random
import json
import csv
import os
from urllib.parse import quote_plus
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# --- Configuration ---
JOB_KEYWORDS = "Ruby on Rails"
JOB_LOCATION = "Japan"
JOB_WORKPLACE_TYPE = "remote"
MAX_PAGES_TO_SCRAPE = 1

# Login Configuration
MANUAL_LOGIN = False

# --- Dynamically Build Search URL ---
WORKPLACE_FILTER_CODES = {"on-site": "1", "remote": "2", "hybrid": "3"}
base_url = "https://www.linkedin.com/jobs/search/"
encoded_keywords = quote_plus(JOB_KEYWORDS)
encoded_location = quote_plus(JOB_LOCATION)
SEARCH_URL = f"{base_url}?keywords={encoded_keywords}&location={encoded_location}"
if JOB_WORKPLACE_TYPE in WORKPLACE_FILTER_CODES:
    workplace_code = WORKPLACE_FILTER_CODES[JOB_WORKPLACE_TYPE]
    SEARCH_URL += f"&f_WT={workplace_code}"
    print(f"INFO: Added filter for '{JOB_WORKPLACE_TYPE.upper()}' jobs.")

# --- Updated CSS Selectors (Based on Current LinkedIn Structure) ---
SELECTORS = {
    "job_card_list": "div[data-job-id].job-card-container",
    "detail_pane": {
        "title": "h1.t-24.t-bold, h2.t-16.t-black.t-bold, div.job-details-jobs-unified-top-card__job-title h1",
        "company_link": "div.job-details-jobs-unified-top-card__company-name a, a.uxvNeZlUzUerxhncQCbPGgMBxUNKqUMfQTIcuo",
        "job_location": "span.tvm__text.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "posted_date": "span.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "applicant_count": "span.tvm__text--low-emphasis, div.job-details-jobs-unified-top-card__tertiary-description-container span",
        "salary_info": "div.salary.compensation__salary, div.job-details-jobs-unified-top-card__salary",
        "description": "div.jobs-box__html-content, div.jobs-description-content__text--stretch, div.jobs-description__content"
    }
}

# --- Browser Setup ---
def setup_driver():
    """Sets up the Selenium WebDriver with anti-detection options."""
    options = webdriver.EdgeOptions()
    
    # Use existing user profile to maintain login session
    import os
    user_profile = os.path.expanduser("~")
    profile_path = f"{user_profile}\\AppData\\Local\\Microsoft\\Edge\\User Data"
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--profile-directory=Default")
    print(f"INFO: Using existing Edge profile from: {profile_path}")
    
    # Headless mode based on configuration
    if not MANUAL_LOGIN:
        options.add_argument("--headless")
        print("INFO: Running in headless mode (using existing profile)")
    else:
        print("INFO: Running with visible browser (using existing profile)")
    
    options.add_argument("--window-size=1280,1024")
    
    # Enhanced GPU and rendering fixes
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-gpu-sandbox')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-background-timer-throttling')
    options.add_argument('--disable-backgrounding-occluded-windows')
    options.add_argument('--disable-renderer-backgrounding')
    options.add_argument('--disable-features=TranslateUI')
    options.add_argument('--disable-ipc-flooding-protection')
    
    # Memory and performance optimizations
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--memory-pressure-off')
    options.add_argument('--max_old_space_size=4096')
    
    # WebGL and graphics fixes
    options.add_argument('--disable-webgl')
    options.add_argument('--disable-webgl2')
    options.add_argument('--disable-3d-apis')
    options.add_argument('--use-gl=swiftshader-webgl')
    options.add_argument('--enable-unsafe-swiftshader')
    
    # Network and security
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--allow-insecure-localhost')
    options.add_argument('--disable-web-security')
    
    # Anti-detection
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edge/119.0.0.0")
    
    # Logging suppression
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--log-level=3")
    options.add_argument("--silent")

    try:
        service = Service()
        driver = webdriver.Edge(service=service, options=options)
    except Exception as e:
        print(f"Could not start Edge WebDriver. Ensure 'msedgedriver' is installed and on your PATH.\nException: {e}")
        raise
    return driver

# --- Login Check Function ---
def check_and_ensure_login(driver):
    """
    Checks if already logged in using existing profile, or assists with login if needed.
    """
    print("\n=== CHECKING LOGIN STATUS ===")
    
    # First, try to go to LinkedIn feed to check if already logged in
    print("Checking existing login status...")
    driver.get("https://www.linkedin.com/feed/")
    time.sleep(3)
    
    # Check if we're already logged in
    current_url = driver.current_url
    if "feed" in current_url or driver.find_elements(By.CSS_SELECTOR, "nav.global-nav"):
        print("✅ Already logged in using existing profile! No manual login needed.")
        return True
    
    # If not logged in, redirect to login page
    print("❌ Not logged in. Opening login page...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(2)
    
    print("\n=== MANUAL LOGIN REQUIRED ===")
    print("Please complete the following steps:")
    print("1. Enter your LinkedIn email/username")
    print("2. Enter your LinkedIn password")  
    print("3. Complete any 2FA/captcha if required")
    print("4. Make sure you're successfully logged in")
    print("5. Press ENTER in this terminal to continue...")
    
    # Wait for user confirmation
    input()
    
    # Verify login was successful
    current_url = driver.current_url
    if "feed" in current_url or "in/" in current_url or driver.find_elements(By.CSS_SELECTOR, "nav.global-nav"):
        print("✓ Login successful! Continuing with job scraping...")
        return True
    else:
        print("⚠ Login verification failed. Please ensure you're logged in.")
        retry = input("Do you want to try again? (y/n): ").lower().strip()
        if retry == 'y':
            return check_and_ensure_login(driver)
        else:
            print("Exiting...")
            return False

# --- Scraping Logic ---
def scrape_detail_pane(driver, selectors):
    """
    Scrapes all available data from the detail pane using specific, individual selectors.
    """
    job_data = {
        "company_name": None, "linkedin_company_page": None, "title": None,
        "job_location": None, "posted_date": None, "applicant_count": None,
        "salary": "Not specified", "description": None
    }
    
    # Company information with updated selectors for new LinkedIn layout  
    company_selectors = [
        selectors["company_link"],
        "div.job-details-jobs-unified-top-card__company-name a",
        "a.uxvNeZlUzUerxhncQCbPGgMBxUNKqUMfQTIcuo",
        "div.artdeco-entity-lockup__title a",
        "div.artdeco-entity-lockup__subtitle span",  # From job card: "thoughtbot"
        "span.hSoRNBfovczqWfblNZqRBELNzkbfLKoOdXRZLs",  # From your HTML
        "a[href*='/company/']"
    ]
    
    for selector in company_selectors:
        try:
            company_element = driver.find_element(By.CSS_SELECTOR, selector)
            company_text = company_element.text.strip()
            if company_text and len(company_text) > 1:
                job_data['company_name'] = " ".join(company_text.split())
                href = company_element.get_attribute('href')
                if href and '/company/' in href:
                    job_data['linkedin_company_page'] = href.split('?')[0]
                break
        except (NoSuchElementException, TimeoutException, AttributeError): 
            continue

    # Job title with updated selectors for new LinkedIn layout
    title_selectors = [
        selectors["title"],
        "div.job-details-jobs-unified-top-card__job-title h1 a",
        "h1.t-24.t-bold a",
        "h2.t-16.t-black.t-bold",
        "div.job-details-jobs-unified-top-card__title-container h2",
        "h1.t-24.t-bold.inline a",  # Based on your HTML
        "a.job-card-list__title--link span strong",  # From job card
        "a[aria-label*='Ruby on Rails'] span strong"  # Alternative from job card
    ]
    
    for selector in title_selectors:
        try:
            title_element = driver.find_element(By.CSS_SELECTOR, selector)
            title_text = title_element.text.strip()
            if title_text and len(title_text) > 3:
                job_data['title'] = " ".join(title_text.split())
                break
        except (NoSuchElementException, TimeoutException): 
            continue

    # Location with updated selectors - need to parse from the combined text
    location_selectors = [
        "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text--low-emphasis",
        "div.job-details-jobs-unified-top-card__sticky-header div.t-14.truncate",
        selectors["job_location"]
    ]
    
    for selector in location_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                text = element.text.strip()
                # Look for location-like text (contains geographic terms)
                if (text and (',' in text or any(geo in text.lower() for geo in 
                    ['spain', 'portugal', 'ireland', 'nigeria', 'turkey', 'kingdom', 'europe', 'remote', 'barcelona', 'catalonia']))
                    and not text.lower().startswith('reposted')
                    and not 'applicant' in text.lower()
                    and not 'day' in text.lower()):
                    # Extract just the location part (before any extra info)
                    location_text = text.split(' ·')[0] if ' ·' in text else text
                    location_text = location_text.split('(Remote)')[0].strip() if '(Remote)' in location_text else location_text
                    job_data['job_location'] = location_text
                    break
            if job_data['job_location']:
                break
        except (NoSuchElementException, TimeoutException): 
            continue

    # Posted date - extract from the combined description
    date_selectors = [
        "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text--low-emphasis",
        selectors["posted_date"]
    ]
    
    for selector in date_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                text = element.text.strip()
                # Look for time-related text 
                if (text and any(time_word in text.lower() for time_word in 
                    ['day', 'hour', 'week', 'month', 'ago']) 
                    and not 'applicant' in text.lower()):
                    job_data["posted_date"] = text
                    break
            if job_data["posted_date"]:
                break
        except (NoSuchElementException, TimeoutException): 
            continue
    
    # Applicant count - extract from the combined description
    applicant_selectors = [
        "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text--low-emphasis",
        selectors["applicant_count"]
    ]
    
    for selector in applicant_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                text = element.text.strip()
                # Look for applicant-related text
                if text and 'applicant' in text.lower():
                    job_data["applicant_count"] = text
                    break
            if job_data["applicant_count"]:
                break
        except (NoSuchElementException, TimeoutException): 
            continue

    # Salary information
    salary_selectors = [
        selectors["salary_info"],
        "div.salary.compensation__salary",
        "span[class*='salary']",
        "div[class*='compensation']"
    ]
    
    for selector in salary_selectors:
        try:
            salary_element = driver.find_element(By.CSS_SELECTOR, selector)
            if salary_element.text.strip():
                job_data['salary'] = salary_element.text.strip()
                break
        except (NoSuchElementException, TimeoutException): 
            continue

    # Job description with updated selectors for new LinkedIn layout
    description_selectors = [
        "div.jobs-box__html-content.vvdVnjMuCNHkkivIjrdqOCWODleUYe",  # From your HTML
        "div.jobs-description-content__text--stretch",
        "div.jobs-description__content",
        selectors["description"],
        "div.jobs-box--fadein div.mt4 p"
    ]
    
    for selector in description_selectors:
        try:
            desc_element = driver.find_element(By.CSS_SELECTOR, selector)
            description_text = desc_element.text.strip()
            if description_text and len(description_text) > 100:  # Ensure meaningful content
                # Clean up the description
                job_data['description'] = " ".join(description_text.split())
                break
        except (NoSuchElementException, TimeoutException): 
            continue
        
    return job_data

def scrape_jobs(driver, url, max_pages):
    """Orchestrates the scraping of multiple pages with anti-blocking measures."""
    # ... (This function remains unchanged from the previous, working version) ...
    driver.get(url)
    all_jobs_data = []
    print("Waiting for the initial job search results page to load...")
    
    # Give extra time for the page to fully load
    time.sleep(5)
    print(f"Current URL after navigation: {driver.current_url}")
    
    wait = WebDriverWait(driver, 30)
    
    # STAGE 1: Handle any remaining popups or overlays (user is already logged in)
    try:
        print("Checking for any remaining popups or overlays...")
        
        # Check if we're actually on a jobs page
        if "jobs/search" not in driver.current_url:
            print(f"WARNING: Not on jobs search page. Current URL: {driver.current_url}")
            print("Attempting to navigate to jobs search...")
            driver.get(url)  # Try navigating again
            time.sleep(5)
        
        # Remove any potential blocking overlays
        js_script = """
        // Remove common modal overlays
        document.querySelectorAll('div.modal__overlay, div.modal[role="dialog"], div[data-test-modal]').forEach(el => el.remove());
        // Remove any blocking divs
        document.querySelectorAll('div[style*="position: fixed"]').forEach(el => {
            if (el.style.zIndex > 1000) el.remove();
        });
        """
        driver.execute_script(js_script)
        
        time.sleep(2)
        print("✓ Page cleanup completed.")
    except Exception as e:
        print(f"Minor issue during page cleanup: {e}")
    
    # STAGE 2: Initialize job processing with dynamic loading
    print("\n=== DYNAMIC JOB PROCESSING ===")
    print("LinkedIn loads jobs dynamically as we navigate. Using adaptive approach...")
    
    # Track processed job IDs to avoid duplicates
    processed_job_ids = set()
    jobs_processed_count = 0
        
    for page_num in range(1, max_pages + 1):
        print(f"\n--- Scraping Page {page_num} of {max_pages} ---")
        # Dynamic job processing with re-catching and duplicate filtering
        max_jobs_to_process = 100  # Limit to prevent infinite processing
        consecutive_no_new_jobs = 0
        max_consecutive_no_new = 3  # Stop if no new jobs found after 3 re-catches
        
        try:
            while jobs_processed_count < max_jobs_to_process and consecutive_no_new_jobs < max_consecutive_no_new:
                # Get current job cards
                current_job_cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
                
                if not current_job_cards:
                    print("No job cards found, trying alternative selectors...")
                    job_card_selectors = [
                        "div[data-job-id]",
                        "div.job-card-container", 
                        "div.job-search-card"
                    ]
                    
                    for selector in job_card_selectors:
                        current_job_cards = driver.find_elements(By.CSS_SELECTOR, selector)
                        if current_job_cards:
                            break
                
                if not current_job_cards:
                    print("ERROR: No job cards found with any selector.")
                    break
                
                print(f"\n--- Found {len(current_job_cards)} job cards (Round {jobs_processed_count//10 + 1}) ---")
                
                # Check for new jobs (filter out already processed)
                new_jobs_found = 0
                jobs_to_process = []
                
                for i, card in enumerate(current_job_cards):
                    job_id = card.get_attribute('data-job-id')
                    if job_id and job_id not in processed_job_ids:
                        jobs_to_process.append((i, card, job_id))
                        processed_job_ids.add(job_id)
                        new_jobs_found += 1
                
                if new_jobs_found == 0:
                    consecutive_no_new_jobs += 1
                    print(f"⚠ No new jobs found (attempt {consecutive_no_new_jobs}/{max_consecutive_no_new})")
                    if consecutive_no_new_jobs < max_consecutive_no_new:
                        print("Scrolling down to potentially load more jobs...")
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(random.uniform(3, 5))
                        continue
                    else:
                        print("✓ No more new jobs available. Stopping.")
                        break
                else:
                    consecutive_no_new_jobs = 0
                    print(f"✅ Found {new_jobs_found} new jobs to process")
                
                # Process new jobs
                for job_index, (i, card, job_id) in enumerate(jobs_to_process):
                    if jobs_processed_count >= max_jobs_to_process:
                        break
                        
                    # Human-like breaks
                    if jobs_processed_count > 0 and jobs_processed_count % 15 == 0:
                        break_time = random.uniform(8, 18)
                        print(f"\n--- Taking a human-like break for {break_time:.2f} seconds ---")
                        time.sleep(break_time)

                    jobs_processed_count += 1
                    print(f"\n--- Processing Job {jobs_processed_count} (ID: {job_id}) ---")
                    
                    try:
                        # Re-find the specific job card to avoid stale references
                        fresh_job_cards = driver.find_elements(By.CSS_SELECTOR, SELECTORS["job_card_list"])
                        target_card = None
                        
                        for fresh_card in fresh_job_cards:
                            if fresh_card.get_attribute('data-job-id') == job_id:
                                target_card = fresh_card
                                break
                        
                        if not target_card:
                            print(f"Job {job_id} no longer found, skipping...")
                            continue
                        
                        # Scroll to and click the job card
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", target_card)
                        time.sleep(random.uniform(1.5, 3.0))
                        
                        # Click with multiple fallbacks
                        click_success = False
                        for attempt in range(3):
                            try:
                                if attempt == 0:
                                    driver.execute_script("arguments[0].click();", target_card)
                                elif attempt == 1:
                                    target_card.click()
                                else:
                                    driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", target_card)
                                click_success = True
                                break
                            except Exception as click_e:
                                print(f"Click attempt {attempt + 1} failed: {click_e}")
                                time.sleep(1)
                        
                        if not click_success:
                            print("All click attempts failed, skipping this job")
                            continue
                        
                        # Wait for detail pane to load
                        detail_loaded = False
                        detail_selectors = [
                            SELECTORS["detail_pane"]["company_link"],
                            SELECTORS["detail_pane"]["title"],
                            "div.job-details-jobs-unified-top-card__content"
                        ]
                        
                        for selector in detail_selectors:
                            try:
                                detail_pane_wait = WebDriverWait(driver, 8)
                                detail_pane_wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                                detail_loaded = True
                                break
                            except TimeoutException:
                                continue
                        
                        if not detail_loaded:
                            print("Detail pane failed to load, skipping...")
                            continue
                        
                        # Give time for content to stabilize
                        time.sleep(random.uniform(1.0, 2.0))
                        
                        # Try to expand description
                        try:
                            show_more_selectors = [
                                "button[aria-label='Show more']",
                                "button[data-tracking-control-name='public_jobs_show-more-html-btn']"
                            ]
                            
                            for selector in show_more_selectors:
                                try:
                                    show_more_wait = WebDriverWait(driver, 2)
                                    show_more_button = show_more_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                                    driver.execute_script("arguments[0].click();", show_more_button)
                                    time.sleep(1)
                                    break
                                except TimeoutException:
                                    continue
                                    
                        except Exception:
                            pass  # Description expansion is optional
                        
                        # Scrape job details
                        job_details = scrape_detail_pane(driver, SELECTORS["detail_pane"])
                        job_details['linkedin_job_id'] = job_id  # Add job ID to data
                        
                        if job_details.get("title") and job_details.get("company_name"):
                            all_jobs_data.append(job_details)
                            print(f"✓ Successfully scraped: {job_details.get('title')} at {job_details.get('company_name')}")
                        else:
                            print(f"⚠ Incomplete data scraped - missing title or company")
                            
                    except Exception as e:
                        print(f"❌ Error processing job {job_id}: {e!r}")
                        if "TimeoutException" in str(e):
                            print("Timeout detected - taking longer break...")
                            time.sleep(random.uniform(5, 8))
                        continue
                
                # After processing this batch, check if more jobs loaded dynamically
                print(f"\n--- Checking for more dynamically loaded jobs ---")
                time.sleep(random.uniform(2, 4))  # Let dynamic content load
            
            print(f"\n✅ Completed processing for page {page_num}")
            print(f"📊 Total jobs processed so far: {jobs_processed_count}")
            print(f"💾 Total jobs scraped successfully: {len(all_jobs_data)}")
            
            # After processing all jobs on this page, handle pagination  
            if page_num < max_pages:
                print("\nMoving to the next page...")
                try:
                    # Updated next button selectors based on actual LinkedIn HTML
                    next_button_selectors = [
                        "button[aria-label='View next page']",  # From your HTML
                        "button.jobs-search-pagination__button--next",  # From your HTML
                        "button[aria-label*='next' i]",  # Case-insensitive next
                        "button[aria-label='Next']",  # Old selector fallback
                        "button:has-text('Next')"  # Text-based fallback
                    ]
                    
                    next_button = None
                    for selector in next_button_selectors:
                        try:
                            print(f"Trying next button selector: {selector}")
                            next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                            if next_button:
                                print(f"✓ Found next button with selector: {selector}")
                                break
                        except TimeoutException:
                            continue
                    
                    if not next_button:
                        print("'Next' button not found with any selector. Reached the last page.")
                        break
                    
                    # Check if button is disabled
                    if next_button.get_attribute('disabled') or next_button.get_attribute('aria-disabled') == 'true':
                        print("'Next' button is disabled. Reached the last page.")
                        break
                    
                    # Click the next button
                    driver.execute_script("arguments[0].click();", next_button)
                    print("✓ Clicked next button, waiting for new page to load...")
                    time.sleep(random.uniform(5, 8))  # Give more time for page transition
                    
                    # Reset job processing counters for new page
                    processed_job_ids.clear()  # Allow reprocessing jobs on new page
                    jobs_processed_count = 0
                    
                except TimeoutException:
                    print("'Next' button not found. Reached the last page.")
                    break
                except Exception as e:
                    print(f"Error clicking next button: {e}")
                    break
        except TimeoutException:
            print("Error: Timed out waiting for job cards to load on this page.")
            break
    return all_jobs_data

# --- MODIFIED: The new, intelligent CSV Saving Function ---
def save_to_csv(data, filename):
    """
    Saves a list of job data dictionaries to a CSV file, handling duplicates
    based on company name and job title.
    """
    if not data:
        print("No data to save to CSV.")
        return

    fieldnames = [
        'linkedin_job_id', 'company_name', 'linkedin_company_page', 'title', 
        'job_location', 'posted_date', 'applicant_count', 
        'salary', 'description'
    ]
    
    print(f"\nSaving data to '{filename}', handling duplicates...")

    # Step 1: Read existing data if the file exists
    existing_rows = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    existing_rows.append(row)
            print(f"Found {len(existing_rows)} existing jobs in '{filename}'.")
        except Exception as e:
            print(f"Warning: Could not read existing file '{filename}'. Will overwrite. Error: {e}")
            existing_rows = []

    # Step 2: Create sets for fast duplicate checking
    def get_key(job_dict):
        # Primary key: LinkedIn job ID (most reliable)
        job_id = job_dict.get('linkedin_job_id', '').strip()
        if job_id:
            return ('job_id', job_id)
        
        # Fallback key: company + title (for jobs without ID)
        company = (job_dict.get('company_name') or "").strip().lower()
        title = (job_dict.get('title') or "").strip().lower()
        return ('company_title', company, title)

    existing_keys = {get_key(row) for row in existing_rows}
    existing_job_ids = {row.get('linkedin_job_id') for row in existing_rows if row.get('linkedin_job_id')}
    
    # Step 3: Filter the newly scraped data to find only unique jobs
    new_unique_jobs = []
    for job in data:
        key = get_key(job)
        if key not in existing_keys:
            new_unique_jobs.append(job)
            existing_keys.add(key) # Add to set to handle duplicates within the new batch itself

    if not new_unique_jobs:
        print("No new unique jobs to add. The CSV file is already up to date.")
        return

    print(f"Found {len(new_unique_jobs)} new unique jobs to add.")
    
    # Step 4: Combine existing data with new unique jobs
    combined_data = existing_rows + new_unique_jobs

    # Step 5: Write the combined data back to the file
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(combined_data)
        print(f"Successfully saved {len(combined_data)} total jobs to '{filename}'.")
    except Exception as e:
        print(f"Error writing to CSV file: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    driver = setup_driver()
    raw_scraped_data = []
    try:
        # Step 1: Login (if manual login is enabled)
        if MANUAL_LOGIN:
            if not check_and_ensure_login(driver):
                print("Login failed or cancelled. Exiting...")
                exit(1)
        else:
            print("Skipping login check (headless mode)")
        
        # Step 2: Start scraping
        print(f"\nStarting job scraping for: {JOB_KEYWORDS} in {JOB_LOCATION} ({JOB_WORKPLACE_TYPE})")
        print(f"Search URL: {SEARCH_URL}")
        
        # Debug: Check if we can access the search URL
        print("Testing search URL access...")
        driver.get(SEARCH_URL)
        time.sleep(3)
        print(f"After navigation - Current URL: {driver.current_url}")
        print(f"Page title: {driver.title}")
        
        raw_scraped_data = scrape_jobs(driver, SEARCH_URL, MAX_PAGES_TO_SCRAPE)
        if raw_scraped_data:
            print("\n--- Scraping Complete ---")
            print(f"Successfully scraped a total of {len(raw_scraped_data)} jobs.")
            
            # Save raw backup JSON file
            json_filename = f"{JOB_KEYWORDS}_{JOB_LOCATION}_{JOB_WORKPLACE_TYPE}_raw_backup.json"
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(raw_scraped_data, f, indent=2, ensure_ascii=False)
            print(f"Raw backup data has been saved to '{json_filename}'.")
            
            # Save the final, deduplicated CSV file
            csv_filename = f"{JOB_KEYWORDS}_{JOB_LOCATION}_{JOB_WORKPLACE_TYPE}.csv"
            save_to_csv(raw_scraped_data, filename=csv_filename)
        else:
            print("No data was scraped. Exiting.")
    finally:
        print("\nScript finished. Closing browser.")
        if driver:
            driver.quit()