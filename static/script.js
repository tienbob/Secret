let currentJobId = null;
let pollInterval = null;

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
                document.getElementById('downloadArea').style.display = 'block';
                document.getElementById('downloadBtn').onclick = () => window.location.href = `/api/download/${currentJobId}`;
            } else {
                fill.style.backgroundColor = "var(--error)";
            }
            
            loadHistory(); // Refresh history
        }
    } catch (e) {
        console.error("Polling Error:", e);
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
                        ${formatDate(job.started_at)} • 
                        ${job.results_count !== undefined ? job.results_count + ' items' : job.status}
                    </div>
                </div>
                <div>
                    <span class="status-badge ${job.status}">${job.status}</span>
                    ${job.status === 'completed' ? `<a href="/api/download/${job.job_id}" class="btn btn-success" style="text-decoration:none; margin-left:8px;">⬇</a>` : ''}
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error("History Error:", e);
    }
}

// Auto-refresh history every 5 seconds
setInterval(loadHistory, 5000);
loadHistory();