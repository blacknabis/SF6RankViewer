// Dashboard JavaScript for SF6 Viewer

document.addEventListener('DOMContentLoaded', () => {
    // Element references
    const authStatusEl = document.getElementById('auth-status');
    const dbStatusEl = document.getElementById('db-status');
    const connStatusEl = document.getElementById('connection-status');
    const lastUpdateEl = document.getElementById('last-update');
    const playerDataEl = document.getElementById('player-data');
    const btnLogin = document.getElementById('btn-login');
    const btnRefresh = document.getElementById('btn-refresh');
    const btnCollectMatches = document.getElementById('btn-collect-matches');
    const collectStatusEl = document.getElementById('collect-status');
    const btnStartCollect = document.getElementById('btn-start-collect');
    const collectIntervalInput = document.getElementById('collect-interval');
    const btnApplyFilter = document.getElementById('btn-apply-filter');
    const characterFilterInput = document.getElementById('character-filter');
    const btnDeleteDb = document.getElementById('btn-delete-db');
    const btnOpenStats = document.getElementById('btn-open-stats');
    const btnCopyStatsUrl = document.getElementById('btn-copy-stats-url');
    const matchHistoryContainer = document.getElementById('match-history');

    console.log("Dashboard script loaded. VERSION: 2.1 (Fixed Buttons)");
    console.log("Initializing dashboard...");

    // Helper to update status badges
    function updateStatus(element, status, text) {
        element.className = `value ${status}`;
        element.textContent = text;
    }

    // Fetch system status from /api/status
    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (!res.ok) throw new Error('Network response was not ok');
            const data = await res.json();

            connStatusEl.textContent = 'Connected';
            connStatusEl.className = 'status-badge connected';

            updateStatus(authStatusEl, data.auth_exists ? 'success' : 'error', data.auth_exists ? 'Found' : 'Missing');
            updateStatus(dbStatusEl, data.db_exists ? 'success' : 'error', data.db_exists ? 'Connected' : 'Error');

            if (data.latest_player) {
                renderPlayerData(data.latest_player);
                lastUpdateEl.textContent = new Date(data.latest_player.last_updated).toLocaleString();
            }
        } catch (e) {
            console.error(e);
            connStatusEl.textContent = 'Disconnected';
            connStatusEl.className = 'status-badge disconnected';
        }
    }

    // Render player information block
    function renderPlayerData(player) {
        if (!player) return;
        playerDataEl.innerHTML = `
            <div class="player-info">
                <div class="info-row"><span class="label">Name:</span> <span class="val">${player.name}</span></div>
                <div class="info-row"><span class="label">Rank:</span> <span class="val rank">${player.rank}</span></div>
                <div class="info-row"><span class="label">LP:</span> <span class="val">${player.lp.toLocaleString()}</span></div>
                <div class="info-row"><span class="label">Character:</span> <span class="val">${player.character}</span></div>
            </div>
        `;
    }

    // Login action – opens browser on server
    btnLogin.addEventListener('click', async () => {
        if (confirm('This will open a browser window on the server. Continue?')) {
            try {
                btnLogin.disabled = true;
                btnLogin.textContent = 'Opening Browser...';
                const res = await fetch('/api/login', { method: 'POST' });
                const data = await res.json();
                alert(data.message);
            } catch (e) {
                alert('Failed to start login process');
            } finally {
                btnLogin.disabled = false;
                btnLogin.innerHTML = '<span class="icon">🔑</span> Open Login Browser';
                setTimeout(fetchStatus, 2000);
            }
        }
    });

    // Refresh data action
    btnRefresh.addEventListener('click', async () => {
        try {
            btnRefresh.disabled = true;
            btnRefresh.textContent = 'Scraping...';
            const res = await fetch('/api/refresh', { method: 'POST' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Unknown error');
            }
            const data = await res.json();
            alert('Data refreshed successfully!');
            fetchStatus();
        } catch (e) {
            alert(`Failed to refresh data: ${e.message}`);
        } finally {
            btnRefresh.disabled = false;
            btnRefresh.innerHTML = '<span class="icon">🔄</span> Refresh Data';
        }
    });

    // Log message to the dashboard
    function logMessage(msg) {
        const logContainer = document.getElementById('collection-log');
        if (!logContainer) return;

        const entry = document.createElement('div');
        entry.className = 'log-entry';

        const time = new Date().toLocaleTimeString();
        entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-message">${msg}</span>`;

        logContainer.appendChild(entry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    // Single match collection (used by both manual and interval)
    async function collectMatchesOnce() {
        btnCollectMatches.disabled = true;
        btnCollectMatches.innerHTML = '<span class="icon">⏳</span> Collecting...';
        if (collectStatusEl) collectStatusEl.textContent = 'Collecting...';

        try {
            const res = await fetch('/api/collect_matches', { method: 'POST' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Unknown error');
            }
            const data = await res.json();

            // Log success instead of alert
            logMessage(`${data.message} (New: ${data.new_count})`);

            displayMatchHistory();
        } catch (e) {
            logMessage(`Error: ${e.message}`);
            // alert(`Failed to collect matches: ${e.message}`); // Optional: keep alert for errors or log them too
        } finally {
            btnCollectMatches.disabled = false;
            btnCollectMatches.innerHTML = '<span class="icon">📊</span> Collect Matches';
            if (collectStatusEl) collectStatusEl.textContent = '';
        }
    }

    // Manual collect button
    btnCollectMatches.addEventListener('click', collectMatchesOnce);

    // Periodic collection logic
    let collectIntervalId = null;


    btnStartCollect.addEventListener('click', () => {
        if (collectIntervalId) {
            // Stop Collection
            clearInterval(collectIntervalId);
            collectIntervalId = null;
            btnStartCollect.textContent = 'Start Collect';
            btnStartCollect.classList.remove('danger');
            btnStartCollect.classList.add('primary');
            if (collectStatusEl) collectStatusEl.textContent = 'Stopped';
            logMessage('Periodic collection stopped.');
        } else {
            // Start Collection
            const intervalSec = Number(collectIntervalInput.value) || 30;

            // Immediate collection
            collectMatchesOnce();

            collectStatusEl.textContent = `Running every ${intervalSec}s`;
            logMessage(`Periodic collection started (every ${intervalSec}s).`);

            btnStartCollect.textContent = 'Stop Collect';
            btnStartCollect.classList.remove('primary');
            btnStartCollect.classList.add('danger');

            collectIntervalId = setInterval(collectMatchesOnce, intervalSec * 1000);
        }
    });

    // Display match history with optional character filter
    async function displayMatchHistory() {
        try {
            const res = await fetch('/api/matches?limit=10');
            if (!res.ok) return;
            const matches = await res.json();
            const filter = localStorage.getItem('characterFilter') || '';
            const filtered = filter ? matches.filter(m => m.my_character && m.my_character.toLowerCase() === filter.toLowerCase()) : matches;
            if (!filtered.length) {
                matchHistoryContainer.innerHTML = '<div class="empty-state">No matches found.</div>';
                return;
            }
            let html = '<table class="match-table"><thead><tr>';
            html += '<th>Date</th><th>Result</th><th>My Char</th><th>Opponent</th><th>Opp Char</th><th>MR/LP</th>';
            html += '</tr></thead><tbody>';
            filtered.forEach(m => {
                const resultClass = m.result === 'WIN' ? 'win' : 'lose';
                const mrLp = m.my_mr ? `${m.my_mr} MR` : `${m.my_lp} LP`;
                html += `<tr class="${resultClass}">`;
                html += `<td>${new Date(m.match_date).toLocaleString()}</td>`;
                html += `<td><strong>${m.result}</strong></td>`;
                html += `<td>${m.my_character}</td>`;
                html += `<td>${m.opponent_name}</td>`;
                html += `<td>${m.opponent_character}</td>`;
                html += `<td>${mrLp}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table>';
            matchHistoryContainer.innerHTML = html;
        } catch (e) {
            console.error('Failed to display match history:', e);
        }
    }

    // Apply character filter
    btnApplyFilter.addEventListener('click', () => {
        const filter = characterFilterInput.value.trim();
        if (filter) {
            localStorage.setItem('characterFilter', filter);
            alert(`Character filter set to "${filter}". Refreshing match history.`);
        } else {
            localStorage.removeItem('characterFilter');
            alert('Character filter cleared.');
        }
        displayMatchHistory();
    });

    // Delete database with single confirmation
    btnDeleteDb.addEventListener('click', async () => {
        console.log('Delete Database button clicked');
        if (!confirm('⚠️ WARNING: This will permanently delete ALL match history and player data!\n\nAre you sure you want to continue?')) {
            return;
        }

        btnDeleteDb.disabled = true;
        btnDeleteDb.innerHTML = '<span class="icon">⏳</span> Deleting...';
        try {
            const res = await fetch('/api/delete_database', { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Unknown error');
            }
            const data = await res.json();
            alert(`✅ ${data.message}\n\nThe page will now reload.`);
            window.location.reload();
        } catch (e) {
            console.error('Delete failed:', e);
            alert(`❌ Failed to delete database: ${e.message}`);
            btnDeleteDb.disabled = false;
            btnDeleteDb.innerHTML = '<span class="icon">🗑️</span> Delete Database';
        }
    });

    // Open stats page in new tab
    btnOpenStats.addEventListener('click', () => {
        window.open('/stats', '_blank');
    });

    // Copy stats URL to clipboard
    // Copy stats URL to clipboard
    btnCopyStatsUrl.addEventListener('click', async () => {
        console.log('Copy Stats URL button clicked');
        const statsUrl = `${window.location.protocol}//${window.location.host}/stats`;

        try {
            // Try modern API first
            await navigator.clipboard.writeText(statsUrl);
            alert(`Stats URL copied to clipboard!\n${statsUrl}`);
        } catch (e) {
            console.warn('Clipboard API failed, trying fallback:', e);
            try {
                // Fallback for older browsers or non-secure contexts
                const textarea = document.createElement('textarea');
                textarea.value = statsUrl;
                textarea.style.position = 'fixed'; // Prevent scrolling
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                const successful = document.execCommand('copy');
                document.body.removeChild(textarea);

                if (successful) {
                    alert(`Stats URL copied to clipboard!\n${statsUrl}`);
                } else {
                    throw new Error('execCommand failed');
                }
            } catch (fallbackErr) {
                console.error('Copy failed:', fallbackErr);
                prompt('Copy this URL manually:', statsUrl);
            }
        }
    });

    // Initial load
    fetchStatus();
    displayMatchHistory();
    setInterval(fetchStatus, 5000);
});
