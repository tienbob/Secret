from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import os
import json
import threading
from datetime import datetime
import csv
import uuid
import time
import re
import signal
import platform
import sys

app = Flask(__name__)

# --- Configuration ---
OUTPUT_DIR = 'scraper_outputs'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Store scraping job status
scraping_jobs = {}
job_counter = 0
job_lock = threading.Lock()

# --- Helpers ---
def cleanup_old_files():
    try:
        cutoff_time = time.time() - (3 * 24 * 60 * 60)
        for filename in os.listdir(OUTPUT_DIR):
            filepath = os.path.join(OUTPUT_DIR, filename)
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff_time:
                try: os.remove(filepath)
                except: pass
    except: pass

def start_cleanup_thread():
    def cleanup_loop():
        while True:
            cleanup_old_files()
            time.sleep(3600)
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    global job_counter
    data = request.json
    
    with job_lock:
        job_counter += 1
        job_id = job_counter
    
    file_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Initialize Job State
    scraping_jobs[job_id] = {
        'status': 'running',
        'progress': 'Initializing...',
        'platform': data.get('platform', 'linkedin'),
        'job_keywords': data.get('job_keywords', ''),
        'job_location': data.get('job_location', ''),
        'file_id': file_id,
        'timestamp': timestamp,
        'started_at': datetime.now().isoformat(), # Fixed date issue
        'jobs_found': 0,
        'jobs_processed': 0,
        'results_count': 0
    }
    
    thread = threading.Thread(
        target=run_scraper,
        args=(job_id, data)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id, 'status': 'started'})

def run_scraper(job_id, data):
    temp_script = None
    platform_name = data.get('platform')
    browser = data.get('browser') or os.getenv('BROWSER') or ('brave' if platform.system() == 'Darwin' else 'chrome')
    brave_binary_path = data.get('brave_binary_path') or os.getenv('BRAVE_BINARY_PATH', '')
    run_timestamp = scraping_jobs.get(job_id, {}).get('started_at') or datetime.now().isoformat()
    
    try:
        # 1. Select Template
        script_map = {
            'linkedin': 'linkedin_scraper.py',
            'rubyonremote': 'rubyonremote_scraper.py',
            'wantedly': 'wantedly_scraper.py',
        }
        script_template = script_map.get(platform_name)
        
        if not script_template or not os.path.exists(script_template):
            raise FileNotFoundError(f"Script template {script_template} not found")
        
        # 2. Prepare Configured Script
        with open(script_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Inject Variables
        content = re.sub(r'JOB_KEYWORDS\s*=\s*["\'].*?["\']', f'JOB_KEYWORDS = "{data.get("job_keywords")}"', content)
        content = re.sub(r'JOB_LOCATION\s*=\s*["\'].*?["\']', f'JOB_LOCATION = "{data.get("job_location")}"', content)
        content = re.sub(r'MAX_PAGES_TO_SCRAPE\s*=\s*\d+', f'MAX_PAGES_TO_SCRAPE = {data.get("max_pages", 1)}', content)
        content = re.sub(r'HEADLESS\s*=\s*(True|False)', f'HEADLESS = {data.get("headless", False)}', content)
        content = re.sub(r'BROWSER\s*=\s*["\'].*?["\']', f'BROWSER = "{browser}"', content)
        content = re.sub(r'BRAVE_BINARY_PATH\s*=\s*["\'].*?["\']', f'BRAVE_BINARY_PATH = "{brave_binary_path}"', content)
        content = re.sub(r'RUN_TIMESTAMP\s*=\s*["\'].*?["\']', f'RUN_TIMESTAMP = "{run_timestamp}"', content)
        content = re.sub(r'JOB_WORKPLACE_TYPE\s*=\s*["\'].*?["\']', f'JOB_WORKPLACE_TYPE = "{data.get("workplace_type", "remote")}"', content)
        content = re.sub(r'INDUSTRY_FILTER\s*=\s*["\'].*?["\']', f'INDUSTRY_FILTER = "{data.get("industry_filter", "")}"', content)
        content = re.sub(r'TIME_POSTED_FILTER\s*=\s*["\'].*?["\']', f'TIME_POSTED_FILTER = "{data.get("time_posted", "")}"', content)
        content = re.sub(r'SORT_BY\s*=\s*["\'].*?["\']', f'SORT_BY = "{data.get("sort_by", "R")}"', content)
        content = re.sub(r'HIRING_TYPE\s*=\s*["\'].*?["\']', f'HIRING_TYPE = "{data.get("hiring_type", "mid_career")}"', content)
        content = re.sub(r'ORDER\s*=\s*["\'].*?["\']', f'ORDER = "{data.get("wantedly_order", "mixed")}"', content)
        content = re.sub(r'ONLY_NEW\s*=\s*(True|False)', f'ONLY_NEW = {data.get("only_new", True)}', content)
        
        temp_script = f'temp_{platform_name}_{job_id}.py'
        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(content)
            
        # 3. Execute with UNBUFFERED Output (-u)
        scraping_jobs[job_id]['progress'] = f'Launching browser ({browser})...'
        
        process = subprocess.Popen(
            [sys.executable, '-u', temp_script], # Keep child process in same env as Flask app
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # Line buffered
            universal_newlines=True
        )
        
        # 4. Monitor Output Loop
        start_time = time.time()
        timeout = 900 # 15 minutes max
        
        while True:
            # Check for timeout
            if time.time() - start_time > timeout:
                process.kill()
                raise TimeoutError("Script timed out.")

            # Non-blocking read
            output = process.stdout.readline()
            
            if output == '' and process.poll() is not None:
                break
            
            if output:
                line = output.strip()
                print(f"[JOB {job_id}] {line}") # Server log
                
                # --- Real-time Progress Parsing ---
                
                # 1. Page Loading
                if "Scraping Page" in line:
                    scraping_jobs[job_id]['progress'] = line
                elif "Loading jobs" in line:
                    scraping_jobs[job_id]['progress'] = "Loading job list..."
                elif "Loaded" in line and "jobs" in line:
                    # Example: "Loaded 15 jobs..."
                    scraping_jobs[job_id]['progress'] = line

                # 2. Processing Individual Jobs
                # LinkedIn: "[5/25] Processing ID: 123"
                elif "Processing ID" in line:
                    scraping_jobs[job_id]['progress'] = f"Analyzing job..."
                
                # 3. Successful Scrape or Skip
                # LinkedIn: "   -> Scraped: Senior Engineer at Company"
                # Ruby: "Scraped: Senior Engineer"
                # Skip: "   -> Skipped duplicate: Title at Company"
                elif "Scraped:" in line:
                    scraping_jobs[job_id]['jobs_processed'] += 1
                    count = scraping_jobs[job_id]['jobs_processed']
                    # Extract just the title (before " at ")
                    after_colon = line.split(":", 1)[1].strip()
                    title = after_colon.split(" at ")[0][:30] if " at " in after_colon else after_colon[:30]
                    scraping_jobs[job_id]['progress'] = f"Saved: {title}..."
                elif "Skipped duplicate:" in line:
                    scraping_jobs[job_id]['progress'] = "Skipping duplicate..."

        # 5. Check Exit Code
        stderr_output = process.stderr.read()
        
        if process.returncode == 0:
            scraping_jobs[job_id]['status'] = 'completed'
            scraping_jobs[job_id]['progress'] = 'Completed successfully.'
            
            # Move File logic
            # Determine expected filename based on scraper logic
            clean_kw = data.get('job_keywords', '').replace(' ', '_').replace('/', '-')
            clean_loc = data.get('job_location', '').replace(' ', '_').replace('/', '-')
            
            # Format: platform_KEYWORDS_LOCATION.csv (keep original format for download)
            old_name = f"{platform_name}_{clean_kw}_{clean_loc}.csv"
            new_name = f"{platform_name}_{clean_kw}_{clean_loc}.csv"
            new_path = os.path.join(OUTPUT_DIR, new_name)
            
            if os.path.exists(old_name):
                import shutil
                shutil.move(old_name, new_path)
                scraping_jobs[job_id]['output_file'] = new_path
                scraping_jobs[job_id]['output_filename'] = new_name
                # Count
                with open(new_path, 'r', encoding='utf-8') as f:
                    scraping_jobs[job_id]['results_count'] = sum(1 for _ in f) - 1
            else:
                # If file not found, try finding ANY csv created recently (fallback)
                scraping_jobs[job_id]['error'] = "Output file could not be renamed automatically."
                
        else:
            raise Exception(f"Script Error: {stderr_output}")

    except Exception as e:
        scraping_jobs[job_id]['status'] = 'error'
        scraping_jobs[job_id]['error'] = str(e)
        print(f"[JOB {job_id} ERROR] {e}")
    
    finally:
        if temp_script and os.path.exists(temp_script):
            try: os.remove(temp_script)
            except: pass

@app.route('/api/status/<int:job_id>')
def get_status(job_id):
    return jsonify(scraping_jobs.get(job_id, {'error': 'Not found'}))

@app.route('/api/download/<int:job_id>')
def download_results(job_id):
    job = scraping_jobs.get(job_id)
    if not job or not job.get('output_file'): return jsonify({'error': 'File not found'}), 404
    
    # Use the stored filename or extract from path
    download_name = job.get('output_filename') or os.path.basename(job['output_file'])
    return send_file(job['output_file'], as_attachment=True, download_name=download_name)

@app.route('/api/jobs')
def list_jobs():
    # Build a lookup of latest contact job by source scraping job
    latest_contact_by_scrape = {}
    for cid, cjob in sorted(contact_jobs.items(), key=lambda item: item[0]):
        src = cjob.get('source_scraping_job')
        if src is not None:
            latest_contact_by_scrape[src] = {
                'contact_job_id': cid,
                'status': cjob.get('status'),
                'progress': cjob.get('progress'),
                'started_at': cjob.get('started_at'),
                'output_csv': cjob.get('output_csv')
            }

    jobs_payload = []
    for k, v in sorted(scraping_jobs.items(), key=lambda item: item[0], reverse=True):
        latest_contact = latest_contact_by_scrape.get(k)
        scrape_status = str(v.get('status', '')).lower()
        jobs_payload.append({
            **v,
            'job_id': k,
            'can_find_contacts': scrape_status == 'completed',
            'latest_contact_job': latest_contact
        })

    return jsonify({'jobs': jobs_payload})

# --- CEO/CTO Contact Finder Integration ---
contact_jobs = {}  # Track contact finding jobs
contact_counter = 0
contact_lock = threading.Lock()

@app.route('/api/find-contacts/<int:job_id>', methods=['POST'])
def find_contacts_for_job(job_id):
    """
    Find CEO/CTO contacts for a completed scraping job
    """
    global contact_counter
    
    job = scraping_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Scraping job not found'}), 404
    
    if job['status'] != 'completed':
        return jsonify({'error': f'Scraping job not completed (status: {job["status"]})'}), 400
    
    input_csv = job.get('output_file')
    if not input_csv or not os.path.exists(input_csv):
        return jsonify({'error': 'Scraping output CSV not found'}), 404
    
    with contact_lock:
        contact_counter += 1
        contact_job_id = contact_counter
    
    # Initialize contact job
    contact_jobs[contact_job_id] = {
        'status': 'running',
        'progress': 'Initializing contact finder...',
        'source_scraping_job': job_id,
        'input_csv': input_csv,
        'output_csv': None,
        'started_at': datetime.now().isoformat(),
        'contacts_found': 0,
        'total_companies': 0,
        'api_calls': 0,
        'error': None
    }
    
    # Start contact finding in background
    thread = threading.Thread(
        target=run_contact_finder,
        args=(contact_job_id, input_csv)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'contact_job_id': contact_job_id, 'status': 'started'})

def run_contact_finder(contact_job_id, input_csv):
    """
    Run the contact finder agent in background
    """
    try:
        from contact_extractor import ContactExtractor
        
        contact_jobs[contact_job_id]['progress'] = 'Loading CSV...'
        
        extractor = ContactExtractor(input_csv, OUTPUT_DIR)
        
        contact_jobs[contact_job_id]['progress'] = 'Extracting executive contacts...'
        
        # Extract contacts (set a reasonable sample if too large)
        import pandas as pd
        df = pd.read_csv(input_csv)
        sample_size = min(100, len(df))  # Limit to 100 companies for API rate limits
        
        enriched_records = extractor.extract_contacts(sample_size=sample_size)
        
        if enriched_records:
            contact_jobs[contact_job_id]['progress'] = 'Saving enriched CSV...'
            output_path = extractor.save_enriched_csv(enriched_records)
            
            contact_jobs[contact_job_id]['output_csv'] = output_path
            contact_jobs[contact_job_id]['contacts_found'] = extractor.stats['contacts_found']
            contact_jobs[contact_job_id]['total_companies'] = extractor.stats['total_companies']
            contact_jobs[contact_job_id]['api_calls'] = extractor.stats['api_calls']
            contact_jobs[contact_job_id]['status'] = 'completed'
            contact_jobs[contact_job_id]['progress'] = 'Completed'
        else:
            contact_jobs[contact_job_id]['status'] = 'error'
            contact_jobs[contact_job_id]['error'] = 'No records were enriched'
    
    except Exception as e:
        contact_jobs[contact_job_id]['status'] = 'error'
        contact_jobs[contact_job_id]['error'] = str(e)
        print(f"[CONTACT JOB {contact_job_id} ERROR] {e}")

@app.route('/api/find-contacts/status/<int:contact_job_id>')
def get_contact_job_status(contact_job_id):
    """
    Get status of a contact finding job
    """
    job = contact_jobs.get(contact_job_id)
    if not job:
        return jsonify({'error': 'Contact job not found'}), 404
    return jsonify(job)

@app.route('/api/find-contacts/download/<int:contact_job_id>')
def download_contact_results(contact_job_id):
    """
    Download enriched CSV with contact information
    """
    job = contact_jobs.get(contact_job_id)
    if not job or not job.get('output_csv'):
        return jsonify({'error': 'Enriched CSV not found'}), 404
    
    output_csv = job['output_csv']
    if not os.path.exists(output_csv):
        return jsonify({'error': 'File not found'}), 404
    
    download_name = os.path.basename(output_csv)
    return send_file(output_csv, as_attachment=True, download_name=download_name)

if __name__ == '__main__':
    start_cleanup_thread()
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '5050'))
    app.run(host=host, port=port)