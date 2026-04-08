let currentJobId = null;
let pollInterval = null;
let currentContactJobId = null;
let contactPollInterval = null;
let lastJobsSnapshot = [];

function formatDate(isoString) {
    if (!isoString) return '';
    return new Date(isoString).toLocaleString();
}

function displayPlatformName(platform) {
    if (platform === 'mynavi') return 'Tenshoku';
    return platform;
}

function updatePlatformForm() {
    const platform = document.getElementById('platform').value;
    const hint = document.getElementById('platformHint');
    const blocks = document.querySelectorAll('.form-block');

    blocks.forEach((block) => {
        const isShared = block.classList.contains('form-block-shared');
        const isLinkedIn = block.classList.contains('form-block-linkedin');
        const isWantedly = block.classList.contains('form-block-wantedly');
        const isRubyOnRemote = block.classList.contains('form-block-rubyonremote');

        let visible = isShared;
        if (platform === 'linkedin' && isLinkedIn) visible = true;
        if (platform === 'wantedly' && isWantedly) visible = true;
        if (platform === 'rubyonremote' && isRubyOnRemote) visible = true;

        block.classList.toggle('is-hidden', !visible);
    });
}

async function parseApiResponse(res) {
    const contentType = (res.headers.get('content-type') || '').toLowerCase();
    if (contentType.includes('application/json')) {
        const data = await res.json();
        return { ok: res.ok, status: res.status, data };
    }

    const text = await res.text();
    const compact = text.replace(/\s+/g, ' ').trim();
    return {
        ok: res.ok,
        status: res.status,
        data: {
            error: compact ? `HTTP ${res.status}: ${compact.slice(0, 180)}` : `HTTP ${res.status}`,
        },
    };
}

function showStatusPanel() {
    document.getElementById('statusPanel').style.display = 'block';
}

function showContactStatusPanel() {
    document.getElementById('contactStatusPanel').style.display = 'block';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function renderHistoryActions(job) {
    const scrapeActions = [];
    const contactActions = [];

    if (job.status === 'completed') {
        scrapeActions.push(`<a href="/api/download/${job.job_id}" class="btn btn-success btn-icon">Download CSV</a>`);
    }
    if (job.status === 'running') {
        scrapeActions.push(`<button class="btn btn-danger js-cancel-scrape" data-job-id="${job.job_id}">Cancel Scrape</button>`);
    }
    if (job.can_find_contacts && (!job.latest_contact_job || job.latest_contact_job.status !== 'running')) {
        scrapeActions.push(`<button class="btn btn-secondary js-find-contacts" data-job-id="${job.job_id}">Find Contacts</button>`);
    }
    if (job.status !== 'running') {
        scrapeActions.push(`<button class="btn btn-danger js-delete-scrape" data-job-id="${job.job_id}">Delete Scrape</button>`);
    }

    if (job.latest_contact_job && job.latest_contact_job.status === 'running') {
        contactActions.push(`<button class="btn btn-danger js-cancel-contact" data-contact-job-id="${job.latest_contact_job.contact_job_id}">Cancel Contact</button>`);
    }
    if (job.latest_contact_job && job.latest_contact_job.status === 'completed') {
        contactActions.push(`<a href="/api/find-contacts/download/${job.latest_contact_job.contact_job_id}" class="btn btn-success btn-icon">Download Contacts</a>`);
    }
    if (job.latest_contact_job && job.latest_contact_job.status !== 'running') {
        contactActions.push(`<button class="btn btn-danger js-delete-contact" data-contact-job-id="${job.latest_contact_job.contact_job_id}">Delete Contact</button>`);
    }

    return `
        <div class="job-action-groups">
            <div class="job-action-group">
                <div class="job-action-label">Scrape</div>
                <div class="job-actions-row">${scrapeActions.join('') || '<span class="job-action-empty">No actions</span>'}</div>
            </div>
            ${contactActions.length ? `
                <div class="job-action-group job-action-group-contact">
                    <div class="job-action-label">Contacts</div>
                    <div class="job-actions-row">${contactActions.join('')}</div>
                </div>
            ` : ''}
        </div>
    `;
}

function hideStatusPanel() {
    document.getElementById('statusPanel').style.display = 'none';
}

function hideContactStatusPanel() {
    document.getElementById('contactStatusPanel').style.display = 'none';
}

function setScrapeTerminalUI(status, jobId) {
    const badge = document.getElementById('statusBadge');
    const fill = document.getElementById('progressFill');
    const downloadArea = document.getElementById('downloadArea');
    const cancelArea = document.getElementById('cancelArea');
    const findContactsBtn = document.getElementById('findContactsBtn');

    fill.classList.remove('pulse');
    badge.className = `status-badge ${status.status}`;
    badge.innerText = status.status;
    document.getElementById('statusText').innerText = status.progress || status.error || status.status;
    document.getElementById('statusRunAt').innerText = status.started_at ? `Run time: ${formatDate(status.started_at)}` : '';

    if (status.status === 'completed') {
        cancelArea.style.display = 'none';
        fill.style.width = '100%';
        fill.style.backgroundColor = 'var(--primary)';
        downloadArea.style.display = 'flex';
        document.getElementById('downloadBtn').onclick = () => window.location.href = `/api/download/${jobId}`;
        findContactsBtn.style.display = 'inline-block';
        findContactsBtn.onclick = () => startContactFinder(jobId);
    } else if (status.status === 'error') {
        cancelArea.style.display = 'none';
        fill.style.backgroundColor = 'var(--error)';
    } else if (status.status === 'cancelled') {
        cancelArea.style.display = 'none';
        fill.style.backgroundColor = 'var(--error)';
        downloadArea.style.display = 'none';
    }

    document.getElementById('startBtn').disabled = false;
    document.getElementById('startBtn').innerText = 'Start Scraping';
}

function setContactTerminalUI(status, contactJobId) {
    const badge = document.getElementById('contactStatusBadge');
    const fill = document.getElementById('contactProgressFill');
    const findContactsBtn = document.getElementById('findContactsBtn');
    const contactCancelArea = document.getElementById('contactCancelArea');

    badge.className = `status-badge ${status.status}`;
    badge.innerText = status.status;
    fill.classList.remove('pulse');
    document.getElementById('contactStatusText').innerText = status.progress || status.error || status.status;

    if (status.status === 'completed') {
        contactCancelArea.style.display = 'none';
        fill.style.width = '100%';
        fill.style.backgroundColor = 'var(--primary)';
        if (findContactsBtn) findContactsBtn.style.display = 'none';
        document.getElementById('contactDownloadArea').style.display = 'flex';
        document.getElementById('contactDownloadBtn').onclick = () => {
            window.location.href = `/api/find-contacts/download/${contactJobId}`;
        };

        if (status.contacts_found !== undefined && status.total_companies !== undefined) {
            document.getElementById('contactStatusText').innerText =
                `Completed: ${status.contacts_found}/${status.total_companies} companies with contacts.`;
        }
    } else if (status.status === 'error') {
        contactCancelArea.style.display = 'none';
        fill.style.backgroundColor = 'var(--error)';
    } else if (status.status === 'cancelled') {
        contactCancelArea.style.display = 'none';
        fill.style.backgroundColor = 'var(--error)';
        document.getElementById('contactDownloadArea').style.display = 'none';
    }
}

async function cancelCurrentScrape() {
    if (!currentJobId) return;
    try {
        const jobId = currentJobId;
        const res = await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
        const parsed = await parseApiResponse(res);
        if (!parsed.ok) throw new Error(parsed.data.error || 'Cancel failed');
        if (pollInterval) clearInterval(pollInterval);
        currentJobId = null;
        hideStatusPanel();
        await deleteScrapeRecord(jobId, true);
        document.getElementById('statusText').innerText = 'Cancelling...';
        loadHistory();
    } catch (err) {
        alert(`Cancel failed: ${err.message || err}`);
    }
}

async function cancelContactJob(contactJobId = null) {
    const targetId = contactJobId || currentContactJobId;
    if (!targetId) return;
    try {
        const res = await fetch(`/api/find-contacts/cancel/${targetId}`, { method: 'POST' });
        const parsed = await parseApiResponse(res);
        if (!parsed.ok) throw new Error(parsed.data.error || 'Cancel failed');
        if (contactPollInterval) clearInterval(contactPollInterval);
        if (String(currentContactJobId) === String(targetId)) {
            currentContactJobId = null;
            hideContactStatusPanel();
        }
        await deleteContactRecord(targetId, true);
        document.getElementById('contactStatusText').innerText = 'Cancelling...';
        loadHistory();
    } catch (err) {
        alert(`Cancel contact failed: ${err.message || err}`);
    }
}

async function deleteScrapeRecord(jobId, silent = false) {
    const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
    const parsed = await parseApiResponse(res);
    if (!parsed.ok) {
        if (!silent) throw new Error(parsed.data.error || 'Delete failed');
        return false;
    }
    if (String(currentJobId) === String(jobId)) {
        currentJobId = null;
        hideStatusPanel();
    }
    return true;
}

async function deleteContactRecord(contactJobId, silent = false) {
    const res = await fetch(`/api/find-contacts/${contactJobId}`, { method: 'DELETE' });
    const parsed = await parseApiResponse(res);
    if (!parsed.ok) {
        if (!silent) throw new Error(parsed.data.error || 'Delete failed');
        return false;
    }
    if (String(currentContactJobId) === String(contactJobId)) {
        currentContactJobId = null;
        hideContactStatusPanel();
    }
    return true;
}

function hydrateCurrentPanels(jobs) {
    const runningScrape = jobs.find((j) => j.status === 'running');
    const runningContact = jobs
        .map((j) => ({ jobId: j.job_id, contact: j.latest_contact_job }))
        .find((entry) => entry.contact && entry.contact.status === 'running');

    if (!currentJobId && runningScrape) {
        currentJobId = runningScrape.job_id;
        showStatusPanel();
        document.getElementById('cancelArea').style.display = 'flex';
        document.getElementById('startBtn').disabled = true;
        document.getElementById('startBtn').innerText = 'Running...';
        startPolling();
    }

    if (!currentContactJobId && runningContact) {
        currentContactJobId = runningContact.contact.contact_job_id;
        showContactStatusPanel();
        document.getElementById('contactCancelArea').style.display = 'flex';
        document.getElementById('contactProgressFill').classList.add('pulse');
        startContactPolling();
    }
}

// 1. Submit Form
document.getElementById('platform').addEventListener('change', updatePlatformForm);

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
            showStatusPanel();
            document.getElementById('downloadArea').style.display = 'none';
            document.getElementById('cancelArea').style.display = 'flex';
            document.getElementById('cancelBtn').onclick = cancelCurrentScrape;
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
            document.getElementById('cancelArea').style.display = 'flex';
            document.getElementById('cancelBtn').onclick = cancelCurrentScrape;
            if (status.jobs_processed > 0) {
                // Rough estimate based on max pages
                const totalEst = 25 * (parseInt(document.getElementById('max_pages').value) || 1);
                const pct = Math.min((status.jobs_processed / totalEst) * 100, 95);
                fill.style.width = pct + "%";
            } else {
                fill.style.width = "10%"; // Indeterminate
            }
        }

        if (status.status === 'completed' || status.status === 'error' || status.status === 'cancelled') {
            clearInterval(pollInterval);
            pollInterval = null;
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').innerText = "Start Scraping";
            fill.classList.remove('pulse');
            document.getElementById('cancelArea').style.display = 'none';
            
            if (status.status === 'completed') {
                fill.style.width = "100%";
                fill.style.backgroundColor = "var(--primary)";
                document.getElementById('downloadArea').style.display = 'flex';
                document.getElementById('downloadBtn').onclick = () => window.location.href = `/api/download/${currentJobId}`;
                document.getElementById('findContactsBtn').style.display = 'inline-block';
                document.getElementById('findContactsBtn').onclick = () => startContactFinder(currentJobId);
            } else {
                fill.style.backgroundColor = "var(--error)";
                document.getElementById('downloadArea').style.display = 'none';
                document.getElementById('statusText').innerText = status.progress || status.error || status.status;
            }

            currentJobId = null;
            hideStatusPanel();
            loadHistory(); // Refresh history
        }
    } catch (e) {
        console.error("Polling Error:", e);
    }
}

// 2b. Start Contact Finder for a completed scraping job
async function startContactFinder(scrapeJobId) {
    try {
        showContactStatusPanel();
        document.getElementById('contactStatusText').innerText = 'Starting contact finder...';
        document.getElementById('contactStatusBadge').className = 'status-badge running';
        document.getElementById('contactStatusBadge').innerText = 'running';
        document.getElementById('contactDownloadArea').style.display = 'none';
        document.getElementById('contactCancelArea').style.display = 'flex';
        document.getElementById('contactCancelBtn').onclick = () => cancelContactJob(currentContactJobId);
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

        if (status.status === 'running') {
            document.getElementById('contactCancelArea').style.display = 'flex';
            document.getElementById('contactCancelBtn').onclick = () => cancelContactJob(currentContactJobId);
        }

        if (status.status === 'completed' || status.status === 'error' || status.status === 'cancelled') {
            clearInterval(contactPollInterval);
            contactPollInterval = null;
            fill.classList.remove('pulse');
            document.getElementById('contactCancelArea').style.display = 'none';

            if (status.status === 'completed') {
                setContactTerminalUI(status, currentContactJobId);
            } else {
                fill.style.backgroundColor = 'var(--error)';
                document.getElementById('contactStatusText').innerText = status.progress || status.error || 'Contact finder failed';
            }

            currentContactJobId = null;
            hideContactStatusPanel();
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
        lastJobsSnapshot = data.jobs || [];
        hydrateCurrentPanels(lastJobsSnapshot);
        
        if (!data.jobs || data.jobs.length === 0) {
            container.innerHTML = "<p class='empty-state'>No jobs run yet.</p>";
            return;
        }

        container.innerHTML = data.jobs.map(job => `
            <div class="job-item">
                <div class="job-info">
                    <div class="job-header-row">
                        <h4>${escapeHtml(displayPlatformName(job.platform))} - ${escapeHtml(job.job_keywords)}</h4>
                        <span class="status-badge ${job.status}">${escapeHtml(job.status)}</span>
                    </div>
                    <div class="meta">
                        Run time: ${formatDate(job.started_at)} • 
                        ${job.results_count !== undefined ? job.results_count + ' items' : job.status}
                        ${job.latest_contact_job ? ` • Contact: ${job.latest_contact_job.status}` : ''}
                    </div>
                </div>
                ${renderHistoryActions(job)}
            </div>
        `).join('');

        container.querySelectorAll('.js-find-contacts').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.getAttribute('data-job-id');
                if (id) startContactFinder(id);
            });
        });

        container.querySelectorAll('.js-cancel-scrape').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-job-id');
                if (!id) return;
                try {
                    const res = await fetch(`/api/cancel/${id}`, { method: 'POST' });
                    const parsed = await parseApiResponse(res);
                    if (!parsed.ok) throw new Error(parsed.data.error || 'Cancel failed');
                    if (String(currentJobId) === String(id)) {
                        currentJobId = null;
                        if (pollInterval) clearInterval(pollInterval);
                        hideStatusPanel();
                    }
                    await deleteScrapeRecord(id, true);
                    loadHistory();
                } catch (err) {
                    alert(`Cancel failed: ${err.message || err}`);
                }
            });
        });

        container.querySelectorAll('.js-cancel-contact').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-contact-job-id');
                if (!id) return;
                await cancelContactJob(id);
            });
        });

        container.querySelectorAll('.js-delete-scrape').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-job-id');
                if (!id) return;
                try {
                    await deleteScrapeRecord(id);
                    loadHistory();
                } catch (err) {
                    alert(`Delete failed: ${err.message || err}`);
                }
            });
        });

        container.querySelectorAll('.js-delete-contact').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const id = e.currentTarget.getAttribute('data-contact-job-id');
                if (!id) return;
                try {
                    await deleteContactRecord(id);
                    loadHistory();
                } catch (err) {
                    alert(`Delete contact failed: ${err.message || err}`);
                }
            });
        });
    } catch (e) {
        console.error("History Error:", e);
    }
}

document.getElementById('refreshHistoryBtn').addEventListener('click', () => {
    loadHistory();
});

// Auto-refresh history every 5 seconds
setInterval(loadHistory, 5000);
updatePlatformForm();
loadHistory();