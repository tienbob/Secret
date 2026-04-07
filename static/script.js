let currentJobId = null;
let pollInterval = null;
let currentContactJobId = null;
let contactPollInterval = null;

function formatDate(isoString) {
    if (!isoString) return '';
    return new Date(isoString).toLocaleString();
}

// 1. Submit Form
document.getElementById('scrapeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('startBtn');
    btn.disabled = true;
    btn.innerText = "Starting...";

    const payload = {
        platform: document.getElementById('platform').value,
        job_keywords: document.getElementById('job_keywords').value,
        job_location: document.getElementById('job_location').value,
        workplace_type: document.getElementById('workplace_type').value,
        industry_filter: document.getElementById('industry_filter').value,
        time_posted: document.getElementById('time_posted').value,
        sort_by: document.getElementById('sort_by').value,
        hiring_type: document.getElementById('hiring_type').value,
        wantedly_order: document.getElementById('wantedly_order').value,
        only_new: document.getElementById('only_new').checked,
        max_pages: parseInt(document.getElementById('max_pages').value),
        headless: document.getElementById('headless').checked
    };

    try {
        const res = await fetch('/api/scrape', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        
        if (data.job_id) {
            currentJobId = data.job_id;
            startPolling();
            document.getElementById('statusPanel').style.display = 'block';
        }
    } catch (err) {
        alert("Failed to start: " + err);
        btn.disabled = false;
        btn.innerText = "Start Scraping";
    }
});

// 2. Poll Status
function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(checkStatus, 1000); // Poll every second
}

async function checkStatus() {
    if (!currentJobId) return;
    
    try {
        const res = await fetch(`/api/status/${currentJobId}`);
        const status = await res.json();
        
        // Update UI
        document.getElementById('statusText').innerText = status.progress;
        document.getElementById('statusRunAt').innerText = status.started_at ? `Run time: ${formatDate(status.started_at)}` : '';
        const badge = document.getElementById('statusBadge');
        const fill = document.getElementById('progressFill');
        
        badge.className = `status-badge ${status.status}`;
        badge.innerText = status.status;

        // Visual progress bar
        if (status.status === 'running') {
            if (status.jobs_processed > 0) {
                // Rough estimate based on max pages
                const totalEst = 25 * (parseInt(document.getElementById('max_pages').value) || 1);
                const pct = Math.min((status.jobs_processed / totalEst) * 100, 95);
                fill.style.width = pct + "%";
            } else {
                fill.style.width = "10%"; // Indeterminate
            }
        }

        if (status.status === 'completed' || status.status === 'error') {
            clearInterval(pollInterval);
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').innerText = "Start Scraping";
            fill.classList.remove('pulse');
            
            if (status.status === 'completed') {
                fill.style.width = "100%";
                document.getElementById('downloadArea').style.display = 'flex';
                document.getElementById('downloadBtn').onclick = () => window.location.href = `/api/download/${currentJobId}`;
                document.getElementById('findContactsBtn').onclick = () => startContactFinder(currentJobId);
            } else {
                fill.style.backgroundColor = "var(--error)";
            }
            
            loadHistory(); // Refresh history
        }
    } catch (e) {
        console.error("Polling Error:", e);
    }
}

// 2b. Start Contact Finder for a completed scraping job
async function startContactFinder(scrapeJobId) {
    try {
        document.getElementById('contactStatusPanel').style.display = 'block';
        document.getElementById('contactStatusText').innerText = 'Starting contact finder...';
        document.getElementById('contactStatusBadge').className = 'status-badge running';
        document.getElementById('contactStatusBadge').innerText = 'running';
        document.getElementById('contactDownloadArea').style.display = 'none';
        document.getElementById('contactProgressFill').style.width = '15%';
        document.getElementById('contactProgressFill').classList.add('pulse');

        const res = await fetch(`/api/find-contacts/${scrapeJobId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();

        if (!res.ok || !data.contact_job_id) {
            throw new Error(data.error || 'Failed to start contact finder');
        }

        currentContactJobId = data.contact_job_id;
        startContactPolling();
        loadHistory();
    } catch (err) {
        document.getElementById('contactStatusBadge').className = 'status-badge error';
        document.getElementById('contactStatusBadge').innerText = 'error';
        document.getElementById('contactStatusText').innerText = `Contact finder failed to start: ${err.message || err}`;
        document.getElementById('contactProgressFill').classList.remove('pulse');
        document.getElementById('contactProgressFill').style.backgroundColor = 'var(--error)';
    }
}

function startContactPolling() {
    if (contactPollInterval) clearInterval(contactPollInterval);
    contactPollInterval = setInterval(checkContactStatus, 1200);
}

async function checkContactStatus() {
    if (!currentContactJobId) return;

    try {
        const res = await fetch(`/api/find-contacts/status/${currentContactJobId}`);
        const status = await res.json();

        if (!res.ok) throw new Error(status.error || 'Unable to fetch contact status');

        document.getElementById('contactStatusText').innerText = status.progress || 'Running...';
        const badge = document.getElementById('contactStatusBadge');
        const fill = document.getElementById('contactProgressFill');

        badge.className = `status-badge ${status.status}`;
        badge.innerText = status.status;

        if (status.status === 'running') {
            fill.style.width = Math.min((fill.style.width ? parseFloat(fill.style.width) : 15) + 6, 90) + '%';
        }

        if (status.status === 'completed' || status.status === 'error') {
            clearInterval(contactPollInterval);
            fill.classList.remove('pulse');

            if (status.status === 'completed') {
                fill.style.width = '100%';
                document.getElementById('findContactsBtn').style.display = 'none';
                document.getElementById('contactDownloadArea').style.display = 'flex';
                document.getElementById('contactDownloadBtn').onclick = () => {
                    window.location.href = `/api/find-contacts/download/${currentContactJobId}`;
                };
                if (status.contacts_found !== undefined && status.total_companies !== undefined) {
                    document.getElementById('contactStatusText').innerText =
                        `Completed: ${status.contacts_found}/${status.total_companies} companies with contacts.`;
                }
            } else {
                fill.style.backgroundColor = 'var(--error)';
                document.getElementById('contactStatusText').innerText = status.error || 'Contact finder failed';
            }

            loadHistory();
        }
    } catch (err) {
        console.error('Contact polling error:', err);
    }
}

// 3. Load History
async function loadHistory() {
    try {
        const res = await fetch('/api/jobs');
        const data = await res.json();
        const container = document.getElementById('jobHistory');
        
        if (!data.jobs || data.jobs.length === 0) {
            container.innerHTML = "<p style='color: #94a3b8; text-align: center;'>No jobs run yet.</p>";
            return;
        }

        container.innerHTML = data.jobs.map(job => `
            <div class="job-item">
                <div class="job-info">
                    <h4>${job.platform} - ${job.job_keywords}</h4>
                    <div class="meta">
                        Run time: ${formatDate(job.started_at)} • 
                        ${job.results_count !== undefined ? job.results_count + ' items' : job.status}
                        ${job.latest_contact_job ? ` • Contact: ${job.latest_contact_job.status}` : ''}
                    </div>
                </div>
                <div>
                    <span class="status-badge ${job.status}">${job.status}</span>
                    ${job.status === 'completed' ? `<a href="/api/download/${job.job_id}" class="btn btn-success" style="text-decoration:none; margin-left:8px;">⬇</a>` : ''}
                    ${job.can_find_contacts ? `<button class="btn btn-secondary js-find-contacts" data-job-id="${job.job_id}" style="margin-left:8px; width:auto; padding:0.5rem 0.75rem;">Find Contacts</button>` : ''}
                    ${job.latest_contact_job && job.latest_contact_job.status === 'completed' ? `<a href="/api/find-contacts/download/${job.latest_contact_job.contact_job_id}" class="btn btn-success" style="text-decoration:none; margin-left:8px;">Contacts ⬇</a>` : ''}
                </div>
            </div>
        `).join('');

        container.querySelectorAll('.js-find-contacts').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.getAttribute('data-job-id');
                if (id) startContactFinder(id);
            });
        });
    } catch (e) {
        console.error("History Error:", e);
    }
}

// Auto-refresh history every 5 seconds
setInterval(loadHistory, 5000);
loadHistory();