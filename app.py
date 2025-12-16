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

app = Flask(__name__)

# --- Configuration ---
OUTPUT_DIR = 'scraper_outputs'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Store scraping job status
scraping_jobs = {}
job_counter = 0
job_lock = threading.Lock()

# --- Helpers ---
def slugify(text):
    if not text: return ""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

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
    
    try:
        # 1. Select Template
        script_template = 'linkedin_scraper.py' if platform_name == 'linkedin' else 'rubyonremote_scraper.py'
        
        if not os.path.exists(script_template):
            raise FileNotFoundError(f"Script template {script_template} not found")
        
        # 2. Prepare Configured Script
        with open(script_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Inject Variables
        content = re.sub(r'JOB_KEYWORDS\s*=\s*["\'].*?["\']', f'JOB_KEYWORDS = "{data.get("job_keywords")}"', content)
        content = re.sub(r'JOB_LOCATION\s*=\s*["\'].*?["\']', f'JOB_LOCATION = "{data.get("job_location")}"', content)
        content = re.sub(r'MAX_PAGES_TO_SCRAPE\s*=\s*\d+', f'MAX_PAGES_TO_SCRAPE = {data.get("max_pages", 1)}', content)
        content = re.sub(r'HEADLESS\s*=\s*(True|False)', f'HEADLESS = {data.get("headless", False)}', content)
        
        temp_script = f'temp_{platform_name}_{job_id}.py'
        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(content)
            
        # 3. Execute with UNBUFFERED Output (-u)
        scraping_jobs[job_id]['progress'] = 'Launching browser...'
        
        process = subprocess.Popen(
            ['python3', '-u', temp_script], # -u IS CRITICAL FOR REAL-TIME LOGS
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
                
                # 3. Successful Scrape
                # LinkedIn: "   -> Captured: Senior Engineer"
                # Ruby: "Scraped: Senior Engineer"
                elif "Captured:" in line or "Scraped:" in line:
                    scraping_jobs[job_id]['jobs_processed'] += 1
                    count = scraping_jobs[job_id]['jobs_processed']
                    title = line.split(":", 1)[1].strip()[:30] # Get title preview
                    scraping_jobs[job_id]['progress'] = f"Saved: {title}..."

        # 5. Check Exit Code
        stderr_output = process.stderr.read()
        
        if process.returncode == 0:
            scraping_jobs[job_id]['status'] = 'completed'
            scraping_jobs[job_id]['progress'] = 'Completed successfully.'
            
            # Move File logic
            # Determine expected filename based on scraper logic
            if platform_name == 'linkedin':
                old_name = f"linkedin_{data.get('job_keywords').replace(' ', '_')[:20]}_{data.get('job_location').replace(' ', '_')[:20]}.csv"
            else:
                k_slug = slugify(data.get('job_keywords'))
                l_slug = slugify(data.get('job_location'))
                old_name = f"rubyonremote_{k_slug}_{l_slug}.csv"
            
            new_name = f"{platform_name}_{job_id}_{scraping_jobs[job_id]['timestamp']}.csv"
            new_path = os.path.join(OUTPUT_DIR, new_name)
            
            if os.path.exists(old_name):
                import shutil
                shutil.move(old_name, new_path)
                scraping_jobs[job_id]['output_file'] = new_path
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
    return send_file(job['output_file'], as_attachment=True)

@app.route('/api/jobs')
def list_jobs():
    # Return jobs sorted by ID descending
    return jsonify({'jobs': [
        {**v, 'job_id': k} 
        for k, v in sorted(scraping_jobs.items(), key=lambda item: item[0], reverse=True)
    ]})

if __name__ == '__main__':
    start_cleanup_thread()
    app.run(debug=True, port=5000)