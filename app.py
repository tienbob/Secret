from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import os
import threading
from datetime import datetime
import io
import tempfile
import uuid
import time
import re
import platform
import sys
import pandas as pd

import db

app = Flask(__name__)


@app.errorhandler(404)
def handle_404(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return err


@app.errorhandler(500)
def handle_500(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return err

# --- Configuration ---
OUTPUT_DIR = 'scraper_outputs'
os.makedirs(OUTPUT_DIR, exist_ok=True)

active_scrape_processes = {}
active_contact_cancel_flags = set()
runtime_lock = threading.Lock()

UNIFIED_OUTPUT_COLUMNS = [
    'source_platform',
    'source_job_id',
    'scrape_run_at',
    'url',
    'title',
    'company',
    'company_website',
    'date',
    'location',
    'salary_info',
    'description',
    'keywords',
    'hiring_type',
    'location_filter',
]


def format_display_date(value) -> str:
    """Convert timestamps to dd/mm/yyyy for CSV readability."""
    if value is None:
        return ''

    text = str(value).strip()
    if not text:
        return ''

    for parser in (datetime.fromisoformat,):
        try:
            normalized = text.replace('Z', '+00:00')
            return parser(normalized).strftime('%d/%m/%Y')
        except ValueError:
            continue

    for pattern in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, pattern).strftime('%d/%m/%Y')
        except ValueError:
            continue

    return text


def normalize_output_csv(csv_path: str, platform_name: str, job_keywords: str, job_location: str) -> int:
    """Normalize scraper-specific CSV columns into one unified output schema."""
    df = pd.read_csv(csv_path)

    if 'source_platform' not in df.columns:
        df['source_platform'] = platform_name

    # Normalize platform-specific ID fields to source_job_id
    if 'source_job_id' not in df.columns:
        df['source_job_id'] = ''
    if 'wantedly_project_id' in df.columns:
        df['source_job_id'] = df['source_job_id'].where(df['source_job_id'].astype(str).str.len() > 0, df['wantedly_project_id'])
    if 'linkedin_job_id' in df.columns:
        df['source_job_id'] = df['source_job_id'].where(df['source_job_id'].astype(str).str.len() > 0, df['linkedin_job_id'])
    if 'rubyonremote_job_id' in df.columns:
        df['source_job_id'] = df['source_job_id'].where(df['source_job_id'].astype(str).str.len() > 0, df['rubyonremote_job_id'])

    # Normalize company naming
    if 'company' not in df.columns:
        if 'company_name' in df.columns:
            df['company'] = df['company_name']
        else:
            df['company'] = ''

    # Normalize date/location naming
    if 'date' not in df.columns:
        if 'posted_date' in df.columns:
            df['date'] = df['posted_date']
        else:
            df['date'] = ''

    if 'location' not in df.columns:
        if 'job_location' in df.columns:
            df['location'] = df['job_location']
        elif 'location_filter' in df.columns:
            df['location'] = df['location_filter']
        else:
            df['location'] = ''

    # Fill optional metadata defaults
    if 'keywords' not in df.columns:
        df['keywords'] = job_keywords or ''
    else:
        df['keywords'] = df['keywords'].fillna(job_keywords or '')

    if 'hiring_type' not in df.columns:
        df['hiring_type'] = ''

    if 'location_filter' not in df.columns:
        df['location_filter'] = job_location or ''
    else:
        df['location_filter'] = df['location_filter'].fillna(job_location or '')

    if 'salary_info' not in df.columns:
        df['salary_info'] = ''

    if 'company_website' not in df.columns:
        df['company_website'] = ''

    if 'url' not in df.columns:
        df['url'] = ''

    if 'title' not in df.columns:
        df['title'] = ''

    if 'description' not in df.columns:
        df['description'] = ''

    if 'scrape_run_at' not in df.columns:
        df['scrape_run_at'] = datetime.now().isoformat()
    df['scrape_run_at'] = df['scrape_run_at'].apply(format_display_date)

    for col in UNIFIED_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ''

    normalized = df[UNIFIED_OUTPUT_COLUMNS].copy()
    normalized.to_csv(csv_path, index=False)
    return len(normalized)

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


def safe_remove_file(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path) and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def read_text_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


def build_csv_download(content: str, filename: str):
    return send_file(
        io.BytesIO(content.encode('utf-8')),
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv; charset=utf-8',
    )

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
    data = request.json
    file_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    job_id = db.create_scrape_job({
        'platform': data.get('platform', 'linkedin'),
        'job_keywords': data.get('job_keywords', ''),
        'job_location': data.get('job_location', ''),
        'file_id': file_id,
        'timestamp': timestamp,
        'started_at': datetime.now(),
    })

    thread = threading.Thread(target=run_scraper, args=(job_id, data))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'started'})

def run_scraper(job_id, data):
    temp_script = None
    platform_name = data.get('platform')
    browser = data.get('browser') or os.getenv('BROWSER') or ('brave' if platform.system() == 'Darwin' else 'chrome')
    brave_binary_path = data.get('brave_binary_path') or os.getenv('BRAVE_BINARY_PATH', '')
    job = db.get_scrape_job(job_id)
    run_timestamp = (job or {}).get('started_at', '') or datetime.now().isoformat()
    
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
        db.update_scrape_job(job_id, progress=f'Launching browser ({browser})...')
        
        process = subprocess.Popen(
            [sys.executable, '-u', temp_script], # Keep child process in same env as Flask app
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # Line buffered
            universal_newlines=True
        )
        with runtime_lock:
            active_scrape_processes[job_id] = process
        
        # 4. Monitor Output Loop
        start_time = time.time()
        timeout = 900 # 15 minutes max
        local_jobs_processed = 0
        
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
                    db.update_scrape_job(job_id, progress=line)
                elif "Loading jobs" in line:
                    db.update_scrape_job(job_id, progress="Loading job list...")
                elif "Loaded" in line and "jobs" in line:
                    # Example: "Loaded 15 jobs..."
                    db.update_scrape_job(job_id, progress=line)

                # 2. Processing Individual Jobs
                # LinkedIn: "[5/25] Processing ID: 123"
                elif "Processing ID" in line:
                    db.update_scrape_job(job_id, progress="Analyzing job...")
                
                # 3. Successful Scrape or Skip
                # LinkedIn: "   -> Scraped: Senior Engineer at Company"
                # Ruby: "Scraped: Senior Engineer"
                # Skip: "   -> Skipped duplicate: Title at Company"
                elif "Scraped:" in line:
                    local_jobs_processed += 1
                    # Extract just the title (before " at ")
                    after_colon = line.split(":", 1)[1].strip()
                    title = after_colon.split(" at ")[0][:30] if " at " in after_colon else after_colon[:30]
                    db.update_scrape_job(job_id, jobs_processed=local_jobs_processed, progress=f"Saved: {title}...")
                elif "Skipped duplicate:" in line:
                    db.update_scrape_job(job_id, progress="Skipping duplicate...")

        # 5. Check Exit Code
        stderr_output = process.stderr.read()
        latest_job = db.get_scrape_job(job_id) or {}
        if latest_job.get('status') == 'cancelled':
            db.update_scrape_job(job_id, progress='Cancelled by user.')
            return
        
        if process.returncode == 0:
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
                results_count = normalize_output_csv(
                    new_path,
                    platform_name=platform_name,
                    job_keywords=data.get('job_keywords', ''),
                    job_location=data.get('job_location', ''),
                )
                output_csv_content = read_text_file(new_path)
                db.update_scrape_job(job_id,
                    status='completed',
                    progress='Completed successfully.',
                    output_file=None,
                    output_filename=new_name,
                    output_csv_content=output_csv_content,
                    results_count=results_count,
                )
                safe_remove_file(new_path)
            else:
                # If file not found, try finding ANY csv created recently (fallback)
                db.update_scrape_job(job_id,
                    status='completed',
                    progress='Completed successfully.',
                    error='Output file could not be renamed automatically.',
                )
                
        else:
            raise Exception(f"Script Error: {stderr_output}")

    except Exception as e:
        latest_job = db.get_scrape_job(job_id) or {}
        if latest_job.get('status') == 'cancelled':
            db.update_scrape_job(job_id, progress='Cancelled by user.')
            print(f"[JOB {job_id}] Cancelled")
        else:
            db.update_scrape_job(job_id, status='error', error=str(e))
            print(f"[JOB {job_id} ERROR] {e}")
    
    finally:
        with runtime_lock:
            active_scrape_processes.pop(job_id, None)
        if temp_script and os.path.exists(temp_script):
            try: os.remove(temp_script)
            except: pass


@app.route('/api/cancel/<int:job_id>', methods=['POST'])
def cancel_scrape_job(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job.get('status') != 'running':
        return jsonify({'error': f"Job is not running (status: {job.get('status')})"}), 400

    db.update_scrape_job(job_id, status='cancelled', progress='Cancelling...')
    with runtime_lock:
        process = active_scrape_processes.get(job_id)
    if process and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
    return jsonify({'status': 'cancelled'})


@app.route('/api/jobs/<int:job_id>', methods=['DELETE'])
def delete_scrape_job(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job.get('status') == 'running':
        return jsonify({'error': 'Cancel the running job before deleting it'}), 400

    related_contact_jobs = [
        contact_job for contact_job in db.list_contact_jobs()
        if contact_job.get('source_scraping_job') == job_id
    ]

    for contact_job in related_contact_jobs:
        if contact_job.get('status') == 'running':
            return jsonify({'error': 'Cancel the running contact job before deleting this scrape record'}), 400

    safe_remove_file(job.get('output_file'))
    for contact_job in related_contact_jobs:
        safe_remove_file(contact_job.get('output_csv'))

    db.delete_contact_jobs_for_scrape(job_id)
    db.delete_scrape_job(job_id)
    return jsonify({'status': 'deleted'})

@app.route('/api/status/<int:job_id>')
def get_status(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(job)

@app.route('/api/download/<int:job_id>')
def download_results(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({'error': 'File not found'}), 404
    csv_content = job.get('output_csv_content')
    download_name = job.get('output_filename') or f'scrape_job_{job_id}.csv'
    if csv_content:
        return build_csv_download(csv_content, download_name)
    if job.get('output_file') and os.path.exists(job['output_file']):
        return send_file(job['output_file'], as_attachment=True, download_name=download_name)
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/jobs')
def list_jobs():
    jobs = db.list_scrape_jobs()
    contacts = db.list_contact_jobs()

    latest_contact_by_scrape = {}
    for cjob in contacts:
        src = cjob.get('source_scraping_job')
        if src is not None:
            latest_contact_by_scrape[src] = {
                'contact_job_id': cjob['id'],
                'status': cjob['status'],
                'progress': cjob['progress'],
                'started_at': cjob['started_at'],
                'output_csv': cjob['output_csv'],
            }

    jobs_payload = []
    for job in jobs:
        latest_contact = latest_contact_by_scrape.get(job['id'])
        jobs_payload.append({
            **job,
            'job_id': job['id'],
            'can_find_contacts': job['status'] == 'completed',
            'latest_contact_job': latest_contact,
        })

    return jsonify({'jobs': jobs_payload})

# --- CEO/CTO Contact Finder Integration ---

@app.route('/api/find-contacts/<int:job_id>', methods=['POST'])
def find_contacts_for_job(job_id):
    job = db.get_scrape_job(job_id)
    if not job:
        return jsonify({'error': 'Scraping job not found'}), 404

    if job['status'] != 'completed':
        return jsonify({'error': f'Scraping job not completed (status: {job["status"]})'}), 400

    csv_content = job.get('output_csv_content')
    input_csv = job.get('output_file')
    if csv_content:
        temp_input = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8')
        temp_input.write(csv_content)
        temp_input.flush()
        temp_input.close()
        input_csv = temp_input.name
    elif input_csv and os.path.exists(input_csv):
        normalize_output_csv(
            input_csv,
            platform_name=job.get('platform', ''),
            job_keywords=job.get('job_keywords', ''),
            job_location=job.get('job_location', ''),
        )
        csv_content = read_text_file(input_csv)
    else:
        return jsonify({'error': 'Scraping output CSV not found'}), 404

    contact_job_id = db.create_contact_job({
        'source_scraping_job': job_id,
        'input_csv': input_csv,
        'input_csv_content': csv_content,
        'started_at': datetime.now(),
    })

    thread = threading.Thread(target=run_contact_finder, args=(contact_job_id, input_csv))
    thread.daemon = True
    thread.start()

    return jsonify({'contact_job_id': contact_job_id, 'status': 'started'})

def run_contact_finder(contact_job_id, input_csv):
    try:
        from contact_extractor import ContactExtractor, ContactExtractionCancelled

        db.update_contact_job(contact_job_id, progress='Loading CSV...')
        extractor = ContactExtractor(
            input_csv,
            OUTPUT_DIR,
            should_cancel=lambda: contact_job_id in active_contact_cancel_flags,
        )

        db.update_contact_job(contact_job_id, progress='Extracting executive contacts...')

        # Extract contacts (set a reasonable sample if too large)
        import pandas as pd
        df = pd.read_csv(input_csv)
        sample_size = min(100, len(df))  # Limit to 100 companies for API rate limits

        enriched_records = extractor.extract_contacts(sample_size=sample_size)

        if contact_job_id in active_contact_cancel_flags:
            db.update_contact_job(contact_job_id, status='cancelled', progress='Cancelled by user.')
            return

        if enriched_records:
            db.update_contact_job(contact_job_id, progress='Saving enriched CSV...')
            output_path = extractor.save_enriched_csv(enriched_records)
            output_csv_content = read_text_file(output_path) if output_path and os.path.exists(output_path) else None
            db.update_contact_job(contact_job_id,
                output_csv=os.path.basename(output_path) if output_path else None,
                output_csv_content=output_csv_content,
                contacts_found=extractor.stats['contacts_found'],
                total_companies=extractor.stats['total_companies'],
                api_calls=extractor.stats['api_calls'],
                status='completed',
                progress='Completed',
            )
            safe_remove_file(output_path)
        else:
            db.update_contact_job(contact_job_id, status='error', error='No records were enriched')

    except ContactExtractionCancelled:
        db.update_contact_job(contact_job_id, status='cancelled', progress='Cancelled by user.')

    except Exception as e:
        db.update_contact_job(contact_job_id, status='error', error=str(e))
        print(f"[CONTACT JOB {contact_job_id} ERROR] {e}")
    finally:
        with runtime_lock:
            active_contact_cancel_flags.discard(contact_job_id)
        if input_csv and os.path.exists(input_csv) and input_csv.startswith(tempfile.gettempdir()):
            safe_remove_file(input_csv)

@app.route('/api/find-contacts/status/<int:contact_job_id>')
def get_contact_job_status(contact_job_id):
    job = db.get_contact_job(contact_job_id)
    if not job:
        return jsonify({'error': 'Contact job not found'}), 404
    return jsonify(job)

@app.route('/api/find-contacts/download/<int:contact_job_id>')
def download_contact_results(contact_job_id):
    job = db.get_contact_job(contact_job_id)
    if not job:
        return jsonify({'error': 'Enriched CSV not found'}), 404
    csv_content = job.get('output_csv_content')
    filename = os.path.basename(job.get('output_csv') or f'contact_job_{contact_job_id}.csv')
    if csv_content:
        return build_csv_download(csv_content, filename)
    output_csv = job.get('output_csv')
    if output_csv and os.path.exists(output_csv):
        return send_file(output_csv, as_attachment=True, download_name=filename)
    return jsonify({'error': 'File not found'}), 404


@app.route('/api/find-contacts/cancel/<int:contact_job_id>', methods=['POST'])
def cancel_contact_job(contact_job_id):
    job = db.get_contact_job(contact_job_id)
    if not job:
        return jsonify({'error': 'Contact job not found'}), 404
    if job.get('status') != 'running':
        return jsonify({'error': f"Contact job is not running (status: {job.get('status')})"}), 400

    with runtime_lock:
        active_contact_cancel_flags.add(contact_job_id)
    db.update_contact_job(contact_job_id, status='cancelled', progress='Cancelling...')
    return jsonify({'status': 'cancelled'})


@app.route('/api/find-contacts/<int:contact_job_id>', methods=['DELETE'])
def delete_contact_job(contact_job_id):
    job = db.get_contact_job(contact_job_id)
    if not job:
        return jsonify({'error': 'Contact job not found'}), 404
    if job.get('status') == 'running':
        return jsonify({'error': 'Cancel the running contact job before deleting it'}), 400

    safe_remove_file(job.get('output_csv'))
    db.delete_contact_job(contact_job_id)
    return jsonify({'status': 'deleted'})

if __name__ == '__main__':
    db.init()
    start_cleanup_thread()
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '5050'))
    app.run(host=host, port=port)