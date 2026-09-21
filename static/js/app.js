// Global state management
let activeTab = 'tab1';
let loadedSymbols = [];
let selectedAnalysisSymbol = '';
let seenAlertIds = new Set();
let pageLoadTime = new Date();

// Chart instances
let barChart = null;
let scatterChart = null;
let lineChart = null;

// Initial bootstrap
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initOverviewPolling();
    initTabPolling();
    setupFilters();
    
    // Set default dates for download fields (today's date)
    const today = new Date().toISOString().split('T')[0];
    document.querySelectorAll('input[type="date"]').forEach(el => {
        el.value = today;
    });
});

// ─── Tab Navigation Logic ───────────────────────────────────────────────────
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            
            // Toggle buttons
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Toggle panes
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            document.getElementById(targetTab).classList.add('active');
            
            activeTab = targetTab;
            
            // Instantly fetch data for target tab
            fetchActiveTabData();
        });
    });
}

function switchSubTab(btn, targetSubtabId) {
    const parentPane = btn.closest('.tab-pane');
    
    // Toggle active tab buttons inside the parent pane
    parentPane.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    
    // Toggle sub-tab content panels
    parentPane.querySelectorAll('.sub-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(targetSubtabId).classList.add('active');
}

// ─── Polling Loop ───────────────────────────────────────────────────────────
function initOverviewPolling() {
    // Poll top-level stats every 5s
    fetchOverview();
    setInterval(fetchOverview, 5000);
}

function initTabPolling() {
    // Poll active tab data every 5s
    fetchActiveTabData();
    setInterval(() => {
        fetchActiveTabData();
    }, 5000);
}

function fetchActiveTabData() {
    if (activeTab === 'tab1') {
        fetchLeaderboardData();
    } else if (activeTab === 'tab2') {
        fetchBreakoutScannerData();
    } else if (activeTab === 'tab3') {
        fetchV1AlertsData();
    } else if (activeTab === 'tab4') {
        fetchV2AlertsData();
    } else if (activeTab === 'tab5') {
        fetchFrozenRetestData();
    } else if (activeTab === 'tab6') {
        fetchPriceOiScannerData();
    }
}

// Setup change event listeners for filters
function setupFilters() {
    // Tab 1 filters
    document.getElementById('leaderboard-search').addEventListener('input', fetchLeaderboardData);
    document.getElementById('leaderboard-limit').addEventListener('input', fetchLeaderboardData);
    document.getElementById('leaderboard-min-iv').addEventListener('input', fetchLeaderboardData);
    
    // Tab 2 filters
    document.getElementById('breakout-filter-sig')?.addEventListener('change', () => {
        breakoutCurrentPage = 1;
        renderBreakoutScannerRows();
    });
    document.getElementById('breakout-sort-by')?.addEventListener('change', () => {
        breakoutCurrentPage = 1;
        renderBreakoutScannerRows();
    });
    
    // Tab 6 filters
    const categorySelect = document.getElementById('poi-category-filter');
    const minOiInput = document.getElementById('poi-min-oi-input');
    const refreshBtn = document.getElementById('poi-refresh-btn');
    const prevDayBtn = document.getElementById('poi-prev-day-btn');
    const nextDayBtn = document.getElementById('poi-next-day-btn');
    
    // Instantaneous in-memory filtering (0ms lag)
    if (categorySelect) categorySelect.addEventListener('change', renderPoiScannerRows);
    if (minOiInput) minOiInput.addEventListener('input', renderPoiScannerRows);
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            const icon = refreshBtn.querySelector('i');
            if (icon) icon.classList.add('fa-spin');
            fetchPriceOiScannerData().finally(() => {
                setTimeout(() => {
                    if (icon) icon.classList.remove('fa-spin');
                }, 400);
            });
        });
    }

    if (prevDayBtn) prevDayBtn.addEventListener('click', () => navigatePoiDay(1));
    if (nextDayBtn) nextDayBtn.addEventListener('click', () => navigatePoiDay(-1));
    
    updatePoiDateNavigatorUI();
    
    // Selected analysis symbol
    document.getElementById('select-stock-analysis').addEventListener('change', (e) => {
        selectedAnalysisSymbol = e.target.value;
        fetchIntradayTrajectory();
    });
}

// ─── API Fetchers ────────────────────────────────────────────────────────────

// 1. Overview API
async function fetchOverview() {
    try {
        const res = await fetch('/api/overview');
        const data = await res.json();
        
        document.getElementById('stat-total-stocks').innerText = data.total || 0;
        document.getElementById('stat-highest-iv').innerText = (data.highest_iv || 0) + '%';
        document.getElementById('stat-avg-iv').innerText = (data.avg_iv || 0) + '%';
        document.getElementById('stat-high-vol').innerText = data.high_vol_count || 0;
        
        document.getElementById('last-sync-time').innerText = `Last sync: ${data.ts_ist || '—'}`;
    } catch (err) {
        console.error('Error fetching overview stats:', err);
    }
}

// 2. Leaderboard API
let lastLeaderboardRaw = [];
async function fetchLeaderboardData() {
    try {
        const search = document.getElementById('leaderboard-search').value;
        const limit = document.getElementById('leaderboard-limit').value || 50;
        const minIv = document.getElementById('leaderboard-min-iv').value || 0;
        
        const res = await fetch(`/api/leaderboard?search=${encodeURIComponent(search)}&limit=${limit}&min_iv=${minIv}`);
        const data = await res.json();
        
        renderLeaderboardRows(data);
        updateTopmovers();
        
        // Handle symbol list updates for the Trajectory Selector
        if (data.length > 0) {
            updateSymbolSelect(data);
        }
        
        // Render Chart.js plots
        renderCharts(data);
    } catch (err) {
        console.error('Error fetching leaderboard data:', err);
    }
}

// Movers Spikes / Crushes API
async function updateTopmovers() {
    try {
        const res = await fetch('/api/movers');
        const data = await res.json();
        
        // Render spikes table
        const spikesBody = document.getElementById('spikes-table-body');
        spikesBody.innerHTML = '';
        if (data.spikes.length === 0) {
            spikesBody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">No volatility spikes tracked yet.</td></tr>`;
        } else {
            data.spikes.forEach(s => {
                spikesBody.innerHTML += `
                    <tr>
                        <td class="font-bold text-green">${s.underlying_symbol}</td>
                        <td class="font-mono">${s.iv4.toFixed(2)}</td>
                        <td class="font-mono text-green">+${s.iv4_change_5m.toFixed(2)}</td>
                        <td style="font-size:0.75rem">${s.top_strike_iv_change_5m || '—'}</td>
                    </tr>
                `;
            });
        }
        
        // Render crushes table
        const crushesBody = document.getElementById('crushes-table-body');
        crushesBody.innerHTML = '';
        if (data.crushes.length === 0) {
            crushesBody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">No volatility crushes tracked yet.</td></tr>`;
        } else {
            data.crushes.forEach(c => {
                crushesBody.innerHTML += `
                    <tr>
                        <td class="font-bold text-red">${c.underlying_symbol}</td>
                        <td class="font-mono">${c.iv4.toFixed(2)}</td>
                        <td class="font-mono text-red">${c.iv4_change_5m.toFixed(2)}</td>
                        <td style="font-size:0.75rem">${c.top_strike_iv_change_5m || '—'}</td>
                    </tr>
                `;
            });
        }
    } catch (err) {
        console.error('Error updating top movers:', err);
    }
}

// 3. Intraday Trajectory API
async function fetchIntradayTrajectory() {
    if (!selectedAnalysisSymbol) return;
    try {
        const res = await fetch(`/api/history/${selectedAnalysisSymbol}`);
        const data = await res.json();
        renderTrajectoryLineChart(data);
    } catch (err) {
        console.error('Error fetching intraday trajectory:', err);
    }
}

// 4. Tab 2: Breakout Scanner API
let rawBreakoutScannerAlerts = [];
async function fetchBreakoutScannerData() {
    try {
        const res = await fetch('/api/alerts/breakout');
        const data = await res.json();
        rawBreakoutScannerAlerts = data;
        
        // Alert checking/toasting
        processNewAlertsToasts(data, 'BREAKOUT', '🎯 Breakout Scanner Alert');
        
        renderBreakoutScannerRows();
    } catch (err) {
        console.error('Error fetching breakout scanner signals:', err);
    }
}

// 5. Tab 3: Live Alerts Log V1 API
async function fetchV1AlertsData() {
    try {
        const res = await fetch('/api/alerts/v1');
        const data = await res.json();
        
        // Alert checking/toasting
        processNewAlertsToasts(data, 'V1', '🚨 V1 Breakout Crossing Alert');
        
        renderV1AlertsRows(data);
    } catch (err) {
        console.error('Error fetching V1 alerts:', err);
    }
}

// 6. Tab 4: Early Breakouts V2 API
async function fetchV2AlertsData() {
    try {
        const res = await fetch('/api/alerts/v2');
        const data = await res.json();
        
        // Alert checking/toasting
        processNewAlertsToasts(data, 'V2', '🔥 V2 Early Breakout Alert');
        
        renderV2AlertsRows(data);
    } catch (err) {
        console.error('Error fetching V2 alerts:', err);
    }
}

// 7. Tab 5: Frozen Retest API
async function fetchFrozenRetestData() {
    try {
        const res = await fetch('/api/frozen/summary');
        const data = await res.json();
        renderFrozenRetestSummary(data);
    } catch (err) {
        console.error('Error fetching frozen retest data:', err);
    }
}

// ─── DOM Renderers & Chart Plotters ──────────────────────────────────────────

// Update selected symbol options list
function updateSymbolSelect(data) {
    const select = document.getElementById('select-stock-analysis');
    const currentSelection = select.value;
    
    // Sort symbols alphabetically
    const symbols = [...new Set(data.map(d => d.underlying_symbol))].sort();
    
    // Re-fill options if count or options differ
    if (symbols.length !== loadedSymbols.length) {
        loadedSymbols = symbols;
        select.innerHTML = '<option value="">-- SELECT UNDERLYING --</option>';
        symbols.forEach(s => {
            select.innerHTML += `<option value="${s}">${s}</option>`;
        });
        
        // Restore selection or select first symbol as default
        if (symbols.includes(currentSelection)) {
            select.value = currentSelection;
        } else if (symbols.length > 0) {
            select.value = symbols[0];
            selectedAnalysisSymbol = symbols[0];
            fetchIntradayTrajectory();
        }
    }
}

// Render Volatility Leaderboard table rows
function renderLeaderboardRows(data) {
    const tbody = document.getElementById('leaderboard-table-body');
    tbody.innerHTML = '';
    
    // Update podium
    const podiumContainer = document.getElementById('podium-container');
    podiumContainer.innerHTML = '';
    
    // Render top 3 podium cards
    for (let i = 0; i < Math.min(3, data.length); i++) {
        const item = data[i];
        const changeClass = item.iv4_change_5m > 0 ? 'text-green' : (item.iv4_change_5m < 0 ? 'text-red' : '');
        const changeSign = item.iv4_change_5m > 0 ? '+' : '';
        
        podiumContainer.innerHTML += `
            <div class="podium-card rank-${i + 1}">
                <div class="podium-rank-badge">${i + 1}</div>
                <div class="podium-symbol">${item.underlying_symbol}</div>
                <div class="podium-iv text-blue">${item.iv4.toFixed(2)}</div>
                <div class="podium-change ${changeClass}">${changeSign}${item.iv4_change_5m.toFixed(2)}</div>
                <div class="podium-driver">${item.top_strike_iv_change_5m || '—'}</div>
            </div>
        `;
    }
    
    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--text-muted)">No matching records found.</td></tr>`;
        return;
    }
    
    data.forEach(item => {
        const changeClass = item.iv4_change_5m > 0 ? 'text-green' : (item.iv4_change_5m < 0 ? 'text-red' : '');
        const changeSign = item.iv4_change_5m > 0 ? '+' : '';
        
        tbody.innerHTML += `
            <tr>
                <td class="font-bold">${item.rank}</td>
                <td class="font-bold text-accent">${item.underlying_symbol}</td>
                <td class="font-mono">${item.last_price.toFixed(2)}</td>
                <td class="font-mono font-bold">${item.iv4.toFixed(2)}</td>
                <td class="font-mono ${changeClass}">${changeSign}${item.iv4_change_5m.toFixed(2)}</td>
                <td style="font-size:0.75rem">${item.top_strike_iv_change_5m || '—'}</td>
                <td class="font-mono">${item.ce_iv_oi_weighted.toFixed(2)}</td>
                <td class="font-mono">${item.pe_iv_oi_weighted.toFixed(2)}</td>
                <td class="font-mono">${item.iv_skew.toFixed(2)}</td>
                <td class="font-mono">${item.iv_ratio.toFixed(2)}</td>
                <td>${item.expiry || '—'}</td>
            </tr>
        `;
    });
}

// Render Chart.js Plots
function renderCharts(data) {
    const top30 = data.slice(0, 30);
    const labels = top30.map(d => d.underlying_symbol);
    const ivs = top30.map(d => d.iv4);
    
    // 1. Leaderboard bar chart
    if (!barChart) {
        const ctx = document.getElementById('barChart').getContext('2d');
        barChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Overall IV4 (%)',
                    data: ivs,
                    backgroundColor: 'rgba(59, 130, 246, 0.65)',
                    borderColor: '#3b82f6',
                    borderWidth: 1.5,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { family: 'Inter', weight: 600 } }
                    }
                }
            }
        });
    } else {
        barChart.data.labels = labels;
        barChart.data.datasets[0].data = ivs;
        barChart.update('none');
    }
    
    // 2. CE vs PE Dispersion Scatter Chart
    const scatterPoints = data.map(d => ({
        x: d.ce_iv_oi_weighted,
        y: d.pe_iv_oi_weighted,
        label: d.underlying_symbol
    }));
    
    if (!scatterChart) {
        const ctx = document.getElementById('scatterChart').getContext('2d');
        scatterChart = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'Dispersion Points',
                    data: scatterPoints,
                    backgroundColor: 'rgba(139, 92, 246, 0.7)',
                    borderColor: '#8b5cf6',
                    borderWidth: 1,
                    pointRadius: 6,
                    pointHoverRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const pt = ctx.raw;
                                return `${pt.label} (CE: ${pt.x.toFixed(1)}, PE: ${pt.y.toFixed(1)})`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        title: { display: true, text: 'Put Weighted IV (%)', color: '#94a3b8' },
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    },
                    x: {
                        title: { display: true, text: 'Call Weighted IV (%)', color: '#94a3b8' },
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    }
                }
            }
        });
    } else {
        scatterChart.data.datasets[0].data = scatterPoints;
        scatterChart.update('none');
    }
}

// 3. Render Trajectory Line Plot
function renderTrajectoryLineChart(data) {
    const labels = data.map(d => d.ts_ist.split(' ')[1] || d.ts_ist);
    const overall = data.map(d => d.iv4);
    const ce = data.map(d => d.ce_iv_oi_weighted);
    const pe = data.map(d => d.pe_iv_oi_weighted);
    
    if (!lineChart) {
        const ctx = document.getElementById('lineChart').getContext('2d');
        lineChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Overall IV4',
                        data: overall,
                        borderColor: '#3b82f6',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        tension: 0.1,
                        pointRadius: 2
                    },
                    {
                        label: 'CE IV (Weighted)',
                        data: ce,
                        borderColor: '#10b981',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        tension: 0.1,
                        pointRadius: 0
                    },
                    {
                        label: 'PE IV (Weighted)',
                        data: pe,
                        borderColor: '#ef4444',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        tension: 0.1,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#f8fafc' } }
                },
                scales: {
                    y: {
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    },
                    x: {
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    }
                }
            }
        });
    } else {
        lineChart.data.labels = labels;
        lineChart.data.datasets[0].data = overall;
        lineChart.data.datasets[1].data = ce;
        lineChart.data.datasets[2].data = pe;
        lineChart.update('none');
    }
}

// ─── Numbered Pagination Helper (1 to 10 Pages Window + Prev/Next Arrows) ────
function renderNumberedPagination(containerId, currentPage, totalPages, onPageChangeFnName) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    totalPages = Math.max(1, totalPages || 1);
    currentPage = Math.max(1, Math.min(currentPage || 1, totalPages));
    
    let html = '';
    
    // Left Arrow (< Prev)
    const prevDisabled = currentPage <= 1 ? 'disabled' : '';
    const prevClick = currentPage > 1 ? `${onPageChangeFnName}(${currentPage - 1})` : '';
    html += `<button class="page-btn page-arrow" ${prevDisabled} ${prevClick ? `onclick="${prevClick}"` : ''} title="Previous Page">
        <i class="fa-solid fa-chevron-left"></i>
    </button>`;
    
    // Calculate page window (show up to 10 numbered buttons: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    let startPage = 1;
    let endPage = Math.min(totalPages, 10);
    
    if (totalPages > 10) {
        startPage = Math.max(1, currentPage - 4);
        endPage = Math.min(totalPages, startPage + 9);
        if (endPage - startPage < 9) {
            startPage = Math.max(1, endPage - 9);
        }
    }
    
    // First Page Jump + Ellipsis (if window shifted past page 1)
    if (startPage > 1) {
        html += `<button class="page-btn ${currentPage === 1 ? 'active' : ''}" onclick="${onPageChangeFnName}(1)">1</button>`;
        if (startPage > 2) {
            html += `<span class="page-dots">...</span>`;
        }
    }
    
    // Numbered Buttons (1 to 10)
    for (let p = startPage; p <= endPage; p++) {
        const activeClass = p === currentPage ? 'active' : '';
        html += `<button class="page-btn ${activeClass}" onclick="${onPageChangeFnName}(${p})">${p}</button>`;
    }
    
    // Ellipsis + Last Page Jump (if window doesn't reach totalPages)
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            html += `<span class="page-dots">...</span>`;
        }
        html += `<button class="page-btn ${currentPage === totalPages ? 'active' : ''}" onclick="${onPageChangeFnName}(${totalPages})">${totalPages}</button>`;
    }
    
    // Right Arrow (Next >)
    const nextDisabled = currentPage >= totalPages ? 'disabled' : '';
    const nextClick = currentPage < totalPages ? `${onPageChangeFnName}(${currentPage + 1})` : '';
    html += `<button class="page-btn page-arrow" ${nextDisabled} ${nextClick ? `onclick="${nextClick}"` : ''} title="Next Page">
        <i class="fa-solid fa-chevron-right"></i>
    </button>`;
    
    container.innerHTML = html;
}


// 4. Render Tab 2: Breakout Scanner Rows (Fast Paginated Renderer - 15 alerts/page)
let breakoutCurrentPage = 1;
const BREAKOUT_PAGE_SIZE = 15;

window.goToBreakoutPage = function(page) {
    breakoutCurrentPage = page;
    renderBreakoutScannerRows();
    const tableEl = document.querySelector('#tab2 .table-container');
    if (tableEl) tableEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
};

function renderBreakoutScannerRows() {
    const tbody = document.getElementById('breakout-table-body');
    if (!tbody) return;
    
    const filterSig = document.getElementById('breakout-filter-sig')?.value || 'ALL SIGNALS';
    const sortBy = document.getElementById('breakout-sort-by')?.value || 'time-desc';
    
    let processed = [...rawBreakoutScannerAlerts];
    
    // Filter
    if (filterSig !== 'ALL SIGNALS') {
        processed = processed.filter(a => a.edge_signal === filterSig);
    }
    
    // Sort
    processed.sort((a, b) => {
        if (sortBy === 'time-desc') return new Date(b.timestamp) - new Date(a.timestamp);
        if (sortBy === 'time-asc') return new Date(a.timestamp) - new Date(b.timestamp);
        if (sortBy === 'ratio-desc') return b.iv_ratio - a.iv_ratio;
        if (sortBy === 'ratio-asc') return a.iv_ratio - b.iv_ratio;
        if (sortBy === 'skew-desc') return b.iv_skew - a.iv_skew;
        if (sortBy === 'skew-asc') return a.iv_skew - b.iv_skew;
        return 0;
    });
    
    const totalCount = processed.length;
    const totalPages = Math.max(1, Math.ceil(totalCount / BREAKOUT_PAGE_SIZE));
    
    // Clamp current page
    if (breakoutCurrentPage > totalPages) breakoutCurrentPage = totalPages;
    if (breakoutCurrentPage < 1) breakoutCurrentPage = 1;
    
    // Update pagination UI elements
    const startIdx = (breakoutCurrentPage - 1) * BREAKOUT_PAGE_SIZE;
    const endIdx = Math.min(startIdx + BREAKOUT_PAGE_SIZE, totalCount);
    
    const rangeTextEl = document.getElementById('breakout-range-text');
    const totalTextEl = document.getElementById('breakout-total-text');
    const paginationBar = document.getElementById('breakout-pagination-bar');
    
    if (totalCount === 0) {
        if (paginationBar) paginationBar.style.display = 'none';
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:32px 16px;"><i class="fa-regular fa-bell-slash" style="margin-right:8px;"></i> No breakout scanner alerts found.</td></tr>`;
        return;
    }
    
    if (paginationBar) paginationBar.style.display = 'flex';
    if (rangeTextEl) rangeTextEl.textContent = `${startIdx + 1}-${endIdx}`;
    if (totalTextEl) totalTextEl.textContent = totalCount.toLocaleString();
    
    // Render 1 to 10 numbered buttons
    renderNumberedPagination('breakout-pagination-controls', breakoutCurrentPage, totalPages, 'goToBreakoutPage');
    
    // Slice only the 15 alerts for the active page
    const pageItems = processed.slice(startIdx, endIdx);
    
    let html = '';
    pageItems.forEach((item, index) => {
        let sigClass = 'badge-blue';
        if (item.edge_signal && item.edge_signal.includes('BULLISH')) sigClass = 'badge-green';
        if (item.edge_signal && item.edge_signal.includes('BEARISH')) sigClass = 'badge-red';
        
        const globalRowIdx = startIdx + index + 1;
        
        html += `
            <tr>
                <td class="font-bold">${globalRowIdx}</td>
                <td class="font-mono" style="font-size:0.8rem;color:#38bdf8;">${item.timestamp}</td>
                <td class="font-bold text-accent">${item.symbol}</td>
                <td class="font-mono">₹${(item.spot_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td><span class="badge ${sigClass}">${item.edge_signal}</span></td>
                <td class="font-mono font-bold">${(item.iv_ratio || 0).toFixed(2)}</td>
                <td class="font-mono">${(item.iv_skew || 0).toFixed(2)}</td>
                <td class="font-mono">${(item.vw_iv_call || 0).toFixed(2)}</td>
                <td class="font-mono">${(item.vw_iv_put || 0).toFixed(2)}</td>
                <td class="font-mono ${item.call_flow_net > 0 ? 'text-green' : (item.call_flow_net < 0 ? 'text-red' : '')}">${(item.call_flow_net || 0).toFixed(0)}</td>
                <td class="font-mono ${item.put_flow_net > 0 ? 'text-green' : (item.put_flow_net < 0 ? 'text-red' : '')}">${(item.put_flow_net || 0).toFixed(0)}</td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

// 5. Render Tab 3: Live Alerts Log V1 Rows
function renderV1AlertsRows(alerts) {
    const intradayBody = document.getElementById('alerts-v1-intraday-body');
    const positionalBody = document.getElementById('alerts-v1-positional-body');
    if (!intradayBody || !positionalBody) return;
    
    const intradayAlerts = alerts.filter(a => a.mode === 'INTRADAY');
    const positionalAlerts = alerts.filter(a => a.mode === 'POSITIONAL');
    
    if (intradayAlerts.length === 0) {
        intradayBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No V1 Intraday alerts triggered yet today.</td></tr>`;
    } else {
        let html = '';
        intradayAlerts.forEach((a, idx) => {
            const dirBadge = a.direction === 'UP' ? 'badge-green' : 'badge-red';
            html += `
                <tr>
                    <td class="font-bold">${idx + 1}</td>
                    <td class="font-mono" style="font-size:0.8rem">${a.timestamp}</td>
                    <td class="font-bold text-accent">${a.symbol}</td>
                    <td><span class="badge badge-blue">${a.timeframe}</span></td>
                    <td><span class="badge ${dirBadge}">${a.direction}</span></td>
                    <td class="font-mono">₹${(a.spot || 0).toFixed(2)}</td>
                    <td style="font-size:0.8rem;color:var(--text-secondary)">${a.details || '—'}</td>
                </tr>
            `;
        });
        intradayBody.innerHTML = html;
    }
    
    if (positionalAlerts.length === 0) {
        positionalBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No V1 Positional alerts triggered yet today.</td></tr>`;
    } else {
        let html = '';
        positionalAlerts.forEach((a, idx) => {
            const dirBadge = a.direction === 'UP' ? 'badge-green' : 'badge-red';
            html += `
                <tr>
                    <td class="font-bold">${idx + 1}</td>
                    <td class="font-mono" style="font-size:0.8rem">${a.timestamp}</td>
                    <td class="font-bold text-accent">${a.symbol}</td>
                    <td><span class="badge badge-blue">${a.timeframe}</span></td>
                    <td><span class="badge ${dirBadge}">${a.direction}</span></td>
                    <td class="font-mono">₹${(a.spot || 0).toFixed(2)}</td>
                    <td style="font-size:0.8rem;color:var(--text-secondary)">${a.details || '—'}</td>
                </tr>
            `;
        });
        positionalBody.innerHTML = html;
    }
}

// 6. Render Tab 4: Early Breakouts V2 Rows
function renderV2AlertsRows(alerts) {
    const intradayBody = document.getElementById('alerts-v2-intraday-body');
    const positionalBody = document.getElementById('alerts-v2-positional-body');
    if (!intradayBody || !positionalBody) return;
    
    const intradayAlerts = alerts.filter(a => a.mode === 'INTRADAY');
    const positionalAlerts = alerts.filter(a => a.mode === 'POSITIONAL');
    
    if (intradayAlerts.length === 0) {
        intradayBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No V2 Intraday alerts triggered yet today.</td></tr>`;
    } else {
        let html = '';
        intradayAlerts.forEach((a, idx) => {
            const dirBadge = a.direction === 'UP' ? 'badge-green' : 'badge-red';
            html += `
                <tr>
                    <td class="font-bold">${idx + 1}</td>
                    <td class="font-mono" style="font-size:0.8rem">${a.timestamp}</td>
                    <td class="font-bold text-accent">${a.symbol}</td>
                    <td><span class="badge badge-blue">${a.timeframe}</span></td>
                    <td><span class="badge ${dirBadge}">${a.direction}</span></td>
                    <td class="font-mono">₹${(a.spot || 0).toFixed(2)}</td>
                    <td style="font-size:0.8rem;color:var(--text-secondary)">${a.details || '—'}</td>
                </tr>
            `;
        });
        intradayBody.innerHTML = html;
    }
    
    if (positionalAlerts.length === 0) {
        positionalBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No V2 Positional alerts triggered yet today.</td></tr>`;
    } else {
        let html = '';
        positionalAlerts.forEach((a, idx) => {
            const dirBadge = a.direction === 'UP' ? 'badge-green' : 'badge-red';
            html += `
                <tr>
                    <td class="font-bold">${idx + 1}</td>
                    <td class="font-mono" style="font-size:0.8rem">${a.timestamp}</td>
                    <td class="font-bold text-accent">${a.symbol}</td>
                    <td><span class="badge badge-blue">${a.timeframe}</span></td>
                    <td><span class="badge ${dirBadge}">${a.direction}</span></td>
                    <td class="font-mono">₹${(a.spot || 0).toFixed(2)}</td>
                    <td style="font-size:0.8rem;color:var(--text-secondary)">${a.details || '—'}</td>
                </tr>
            `;
        });
        positionalBody.innerHTML = html;
    }
}

// 7. Render Tab 5: Frozen Retest Rows
function renderFrozenRetestSummary(data) {
    const banner = document.getElementById('frozen-freshness-banner');
    const stats = document.getElementById('frozen-metrics-strip');
    const s = data.summary || {};

    if (Object.keys(s).length === 0) {
        banner.className = 'frozen-monitor-banner text-red';
        banner.innerText = '⚠️ Frozen Scanner output directory is empty or not yet initialized.';
        stats.innerHTML = '';
        return;
    }

    // scanner_summary.json exposes data freshness + scanner timestamps.
    // Do not rely on non-existent fields such as is_running/last_run_time_ist/total_runs_today.
    const dataStatus = String(s.data_status || 'UNKNOWN').toUpperCase();
    const isFresh = dataStatus === 'FRESH';
    const statusText = isFresh ? '🟢 FRESH / ACTIVE' : `🔴 ${dataStatus}`;
    const lastRun = s.as_of_ist || '—';
    const latestBucket = s.latest_completed_bucket_ist || '—';

    banner.className = `frozen-monitor-banner${isFresh ? '' : ' text-red'}`;
    banner.innerHTML =
        `📡 Frozen Scanner Data Status: &nbsp;<b>${statusText}</b>` +
        ` &nbsp;·&nbsp; Last successful scan: <b>${lastRun}</b>` +
        ` &nbsp;·&nbsp; Latest completed 5m bucket: <b>${latestBucket}</b>`;

    stats.innerHTML = `
        <div class="stat-box">
            <div class="stat-num text-blue">${s.symbols_scanned || 0}</div>
            <div class="stat-lbl">Symbols Scanned</div>
        </div>
        <div class="stat-box">
            <div class="stat-num text-purple">${s.active_states || 0}</div>
            <div class="stat-lbl">Active States</div>
        </div>
        <div class="stat-box">
            <div class="stat-num text-green">${s.new_signals_this_run || 0}</div>
            <div class="stat-lbl">New Signals (Latest Run)</div>
        </div>
        <div class="stat-box">
            <div class="stat-num text-red">${s.paper_entries || 0}</div>
            <div class="stat-lbl">Paper Trades Executed</div>
        </div>
    `;

    // Fill the 5 sub-tab tables

    // Sub-tab 1: New signals
    const newBody = document.getElementById('frozen-new-signals-body');
    newBody.innerHTML = '';
    if (!Array.isArray(data.new_signals) || data.new_signals.length === 0) {
        newBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No new signals generated in the last scanner cycle.</td></tr>`;
    } else {
        data.new_signals.forEach(r => {
            const sideClass = r.side === 'BUY' ? 'badge-green' : 'badge-red';
            newBody.innerHTML += `
                <tr>
                    <td class="font-mono">${r.event_time_ist || ''}</td>
                    <td class="font-bold text-accent">${r.symbol || ''}</td>
                    <td><span class="badge ${sideClass}">${r.side || ''}</span></td>
                    <td class="font-mono">${Number.isFinite(Number(r.retest_price)) ? Number(r.retest_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.pullback_volume_ratio)) ? Number(r.pullback_volume_ratio).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.target_price)) ? Number(r.target_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.stop_price)) ? Number(r.stop_price).toFixed(2) : '—'}</td>
                    <td class="font-mono" style="font-size:0.75rem">${r.signal_id || ''}</td>
                </tr>
            `;
        });
    }

    // Sub-tab 2: Current States
    const statesBody = document.getElementById('frozen-states-body');
    statesBody.innerHTML = '';
    if (!Array.isArray(data.states) || data.states.length === 0) {
        statesBody.innerHTML = `<tr><td colspan="12" style="text-align:center;color:var(--text-muted)">No active states currently in progress.</td></tr>`;
    } else {
        data.states.forEach(r => {
            statesBody.innerHTML += `
                <tr>
                    <td class="font-bold text-accent">${r.symbol || ''}</td>
                    <td><span class="badge badge-purple">${r.stage || ''}</span></td>
                    <td class="font-mono">${Number.isFinite(Number(r.resistance_level)) ? Number(r.resistance_level).toFixed(2) : '—'}</td>
                    <td class="font-mono" style="font-size:0.72rem">${r.state1_time_ist || '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.state1_price)) ? Number(r.state1_price).toFixed(2) : '—'}</td>
                    <td class="font-mono" style="font-size:0.72rem">${r.state2_time_ist || '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.state2_price)) ? Number(r.state2_price).toFixed(2) : '—'}</td>
                    <td class="font-mono" style="font-size:0.72rem">${r.state3_time_ist || '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.state3_price)) ? Number(r.state3_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.pullback_volume_ratio)) ? Number(r.pullback_volume_ratio).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.target_price)) ? Number(r.target_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.stop_price)) ? Number(r.stop_price).toFixed(2) : '—'}</td>
                </tr>
            `;
        });
    }

    // Sub-tab 3: Forward Signals
    const forwardBody = document.getElementById('frozen-forward-body');
    forwardBody.innerHTML = '';
    if (!Array.isArray(data.forward_signals) || data.forward_signals.length === 0) {
        forwardBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No forward signals recorded in the current session.</td></tr>`;
    } else {
        data.forward_signals.forEach(r => {
            const sideClass = r.side === 'BUY' ? 'badge-green' : 'badge-red';
            forwardBody.innerHTML += `
                <tr>
                    <td class="font-mono">${r.event_time_ist || ''}</td>
                    <td class="font-bold text-accent">${r.symbol || ''}</td>
                    <td><span class="badge ${sideClass}">${r.side || ''}</span></td>
                    <td class="font-mono">${Number.isFinite(Number(r.retest_price)) ? Number(r.retest_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.pullback_volume_ratio)) ? Number(r.pullback_volume_ratio).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.target_price)) ? Number(r.target_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.stop_price)) ? Number(r.stop_price).toFixed(2) : '—'}</td>
                    <td class="font-mono" style="font-size:0.75rem">${r.signal_id || ''}</td>
                </tr>
            `;
        });
    }

    // Sub-tab 4: Paper Trades
    const tradesBody = document.getElementById('frozen-trades-body');
    tradesBody.innerHTML = '';
    if (!Array.isArray(data.trades) || data.trades.length === 0) {
        tradesBody.innerHTML = `<tr><td colspan="10" style="text-align:center;color:var(--text-muted)">No paper-trade events recorded.</td></tr>`;
    } else {
        data.trades.forEach(r => {
            const sideClass = r.side === 'BUY' ? 'badge-green' : 'badge-red';
            tradesBody.innerHTML += `
                <tr>
                    <td class="font-mono">${r.event_time_ist || ''}</td>
                    <td class="font-bold text-accent">${r.symbol || ''}</td>
                    <td><span class="badge badge-purple">${r.event_type || ''}</span></td>
                    <td><span class="badge ${sideClass}">${r.side || ''}</span></td>
                    <td class="font-mono">${Number.isFinite(Number(r.entry_price)) ? Number(r.entry_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.exit_price)) ? Number(r.exit_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.target_price)) ? Number(r.target_price).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.stop_price)) ? Number(r.stop_price).toFixed(2) : '—'}</td>
                    <td>${r.exit_reason || '—'}</td>
                    <td class="font-mono font-bold ${Number(r.pnl_bps) > 0 ? 'text-green' : (Number(r.pnl_bps) < 0 ? 'text-red' : '')}">${Number.isFinite(Number(r.pnl_bps)) ? Number(r.pnl_bps).toFixed(1) : '—'}</td>
                </tr>
            `;
        });
    }

    // Sub-tab 5: Event Log
    const eventsBody = document.getElementById('frozen-events-body');
    eventsBody.innerHTML = '';
    if (!Array.isArray(data.events) || data.events.length === 0) {
        eventsBody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-muted)">Event log is currently empty.</td></tr>`;
    } else {
        data.events.forEach(r => {
            eventsBody.innerHTML += `
                <tr>
                    <td class="font-mono">${r.event_time_ist || ''}</td>
                    <td class="font-bold text-accent">${r.symbol || ''}</td>
                    <td><span class="badge badge-blue">${r.event_type || ''}</span></td>
                    <td class="font-mono">${Number.isFinite(Number(r.price)) ? Number(r.price).toFixed(2) : '—'}</td>
                    <td style="font-size:0.8rem">${r.reason || '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.resistance_level)) ? Number(r.resistance_level).toFixed(2) : '—'}</td>
                    <td class="font-mono">${Number.isFinite(Number(r.pullback_volume_ratio)) ? Number(r.pullback_volume_ratio).toFixed(2) : '—'}</td>
                    <td class="font-mono font-bold ${Number(r.pnl_bps) > 0 ? 'text-green' : (Number(r.pnl_bps) < 0 ? 'text-red' : '')}">${Number.isFinite(Number(r.pnl_bps)) ? Number(r.pnl_bps).toFixed(1) : '—'}</td>
                    <td class="font-mono" style="font-size:0.75rem">${r.signal_id || '—'}</td>
                </tr>
            `;
        });
    }
}

// ─── Real-Time Alert Toast Notification engine ───────────────────────────────
function processNewAlertsToasts(alertsList, alertTypeLabel, toastHeading) {
    if (!alertsList || !Array.isArray(alertsList)) return;
    
    // Check if this is the very first fetch on page load
    const isFirstRun = seenAlertIds.size === 0;
    
    alertsList.forEach(a => {
        const uniqueKey = `${alertTypeLabel}_${a.symbol}_${a.direction || a.edge_signal}_${a.timestamp || a.ts_ist}`;
        if (!seenAlertIds.has(uniqueKey)) {
            seenAlertIds.add(uniqueKey);
            
            // Do not show popup spam on initial page load
            if (isFirstRun) return;

            showToast(toastHeading, `🚨 ${a.symbol} [${a.direction || a.edge_signal}] at ₹${a.spot || a.spot_price || ''}`, alertTypeLabel.toLowerCase());
        }
    });
}

function showToast(title, msg, typeClass) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    // Limit maximum active toasts to 2 to prevent screen clutter
    while (container.children.length >= 2) {
        container.firstElementChild.remove();
    }

    const toast = document.createElement('div');
    toast.className = `custom-toast ${typeClass}`;
    
    let icon = '<i class="fa-solid fa-circle-exclamation text-blue"></i>';
    if (typeClass === 'v2') icon = '<i class="fa-solid fa-fire text-purple"></i>';
    if (typeClass === 'v1') icon = '<i class="fa-solid fa-circle-check text-green"></i>';
    
    toast.innerHTML = `
        ${icon}
        <div class="toast-body">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${msg}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()"><i class="fa-solid fa-xmark"></i></button>
    `;
    
    container.appendChild(toast);
    
    // Automatically remove after 3.5 seconds
    setTimeout(() => {
        if (toast && toast.parentElement) {
            toast.style.animation = 'fadeOut 0.3s ease forwards';
            setTimeout(() => toast.remove(), 300);
        }
    }, 3500);
}

// ─── CSV Download & Clearing Alert APIs ──────────────────────────────────────
async function clearLiveAlerts(collection, mode, activeTabTag) {
    if (!confirm(`Are you sure you want to clear ${mode || ''} alerts from ${collection}? This cannot be undone.`)) {
        return;
    }
    
    try {
        const res = await fetch('/api/alerts/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ collection, mode })
        });
        const result = await res.json();
        if (result.status === 'success') {
            showToast('Success', 'Alerts cleared successfully', 'v1');
            fetchActiveTabData();
        } else {
            showToast('Error', result.message || 'Failed to clear alerts', 'crossing');
        }
    } catch (err) {
        console.error('Error clearing alerts:', err);
    }
}

function downloadCSV(collection, startInputId, endInputId, mode) {
    const startDate = document.getElementById(startInputId).value;
    const endDate = document.getElementById(endInputId).value;
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates.');
        return;
    }
    
    let url = `/api/alerts/download?collection=${collection}&start_date=${startDate}&end_date=${endDate}`;
    if (mode) {
        url += `&mode=${mode}`;
    }
    
    window.open(url, '_blank');
}

// ─── Price & OI Combination Scanner Logic & Date Navigator ──────────────────
function getRecentTradingDays(count = 5) {
    const days = [];
    let d = new Date();
    while (days.length < count) {
        const dayOfWeek = d.getDay(); // 0 = Sun, 6 = Sat
        if (dayOfWeek !== 0 && dayOfWeek !== 6) {
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            days.push(`${y}-${m}-${day}`);
        }
        d.setDate(d.getDate() - 1);
    }
    return days;
}

let poiTradingDays = getRecentTradingDays(5);
let poiDayIndex = 0; // 0 = Today (max date)
let rawPoiScannerAlerts = [];
let rawPoiSummary = {};

function updatePoiDateNavigatorUI() {
    const dateTextEl = document.getElementById('poi-current-date-text');
    const prevBtn = document.getElementById('poi-prev-day-btn');
    const nextBtn = document.getElementById('poi-next-day-btn');
    
    const curDateStr = poiTradingDays[poiDayIndex] || '';
    if (dateTextEl) {
        if (poiDayIndex === 0) {
            dateTextEl.textContent = `Today (${curDateStr})`;
        } else {
            const dt = new Date(curDateStr + 'T00:00:00');
            const dayName = dt.toLocaleDateString('en-US', { weekday: 'short' });
            dateTextEl.textContent = `${dayName} (${curDateStr})`;
        }
    }
    
    if (nextBtn) {
        // Can't go into tomorrow
        nextBtn.disabled = (poiDayIndex <= 0);
    }
    if (prevBtn) {
        // Max 5 past days
        prevBtn.disabled = (poiDayIndex >= poiTradingDays.length - 1);
    }
}

function navigatePoiDay(delta) {
    const newIndex = poiDayIndex + delta;
    if (newIndex >= 0 && newIndex < poiTradingDays.length) {
        poiDayIndex = newIndex;
        updatePoiDateNavigatorUI();
        fetchPriceOiScannerData();
    }
}

let poiCurrentPage = 1;
const POI_PAGE_SIZE = 15;

window.goToPoiPage = function(page) {
    poiCurrentPage = page;
    renderPoiScannerRows();
    const tableEl = document.querySelector('#tab6 .table-container');
    if (tableEl) tableEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
};

// 0ms Instant Client-Side Filter & Renderer (with Numbered Pagination)
function renderPoiScannerRows() {
    const category = document.getElementById('poi-category-filter')?.value || '';
    const minOi = parseFloat(document.getElementById('poi-min-oi-input')?.value || 0);

    let filtered = [...rawPoiScannerAlerts];

    if (category) {
        filtered = filtered.filter(x => x.quadrant === category);
    }
    if (minOi > 0) {
        filtered = filtered.filter(x => Math.abs(x.oi_change_pct) >= minOi);
    }

    // Update Summary Stat Cards from raw data
    const summary = rawPoiSummary || {};
    const elLong = document.getElementById('stat-poi-long-buildup');
    const elSC = document.getElementById('stat-poi-short-covering');
    const elSB = document.getElementById('stat-poi-short-buildup');
    const elLU = document.getElementById('stat-poi-long-unwinding');

    if (elLong) elLong.textContent = summary.long_buildup || 0;
    if (elSC) elSC.textContent = summary.short_covering || 0;
    if (elSB) elSB.textContent = summary.short_buildup || 0;
    if (elLU) elLU.textContent = summary.long_unwinding || 0;

    // Render Table Rows
    const tbody = document.getElementById('poi-table-body');
    if (!tbody) return;

    const totalCount = filtered.length;
    const totalPages = Math.max(1, Math.ceil(totalCount / POI_PAGE_SIZE));

    if (poiCurrentPage > totalPages) poiCurrentPage = totalPages;
    if (poiCurrentPage < 1) poiCurrentPage = 1;

    const startIdx = (poiCurrentPage - 1) * POI_PAGE_SIZE;
    const endIdx = Math.min(startIdx + POI_PAGE_SIZE, totalCount);

    const paginationBar = document.getElementById('poi-pagination-bar');
    const rangeTextEl = document.getElementById('poi-range-text');
    const totalTextEl = document.getElementById('poi-total-text');

    if (totalCount === 0) {
        if (paginationBar) paginationBar.style.display = 'none';
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 36px 20px; font-size: 0.92rem;"><i class="fa-regular fa-calendar-xmark" style="margin-right: 8px; font-size: 1.1rem; color: var(--text-secondary);"></i> No alerts recorded for this date.</td></tr>`;
        return;
    }

    if (totalPages > 1) {
        if (paginationBar) paginationBar.style.display = 'flex';
        if (rangeTextEl) rangeTextEl.textContent = `${startIdx + 1}-${endIdx}`;
        if (totalTextEl) totalTextEl.textContent = totalCount.toLocaleString();
        renderNumberedPagination('poi-pagination-controls', poiCurrentPage, totalPages, 'goToPoiPage');
    } else {
        if (paginationBar) paginationBar.style.display = 'none';
    }

    const pageItems = filtered.slice(startIdx, endIdx);

    let html = '';
    pageItems.forEach(item => {
        const priceChgClass = item.price_change_pct >= 0 ? 'text-green' : 'text-red';
        const oiChgClass = item.oi_change_pct >= 0 ? 'text-green' : 'text-red';
        const pricePrefix = item.price_change >= 0 ? '+' : '';
        const oiPrefix = item.oi_change >= 0 ? '+' : '';

        const formattedTime = formatAlertTime(item.ts_ist);

        html += `
            <tr>
                <td><strong>${item.symbol}</strong></td>
                <td>₹${(item.spot_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td class="${priceChgClass}">${pricePrefix}${item.price_change_pct}% <small>(${pricePrefix}${item.price_change})</small></td>
                <td>${(item.total_oi || 0).toLocaleString('en-IN')}</td>
                <td class="${oiChgClass}">${oiPrefix}${item.oi_change_pct}% <small>(${oiPrefix}${(item.oi_change || 0).toLocaleString('en-IN')})</small></td>
                <td><span class="badge ${item.badge_class}"><i class="fa-solid ${item.icon}"></i> ${item.label}</span></td>
                <td>${item.pcr || 0}</td>
                <td><small style="color: var(--text-secondary);">${item.top_strike || '—'}</small></td>
                <td>${formattedTime}</td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

async function fetchPriceOiScannerData() {
    const dateStr = poiTradingDays[poiDayIndex] || '';

    try {
        const url = `/api/scanners/price-oi?date=${encodeURIComponent(dateStr)}`;
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();

        rawPoiSummary = data.summary || {};
        rawPoiScannerAlerts = data.items || [];

        renderPoiScannerRows();
    } catch (err) {
        console.error('Error fetching Price & OI scanner data:', err);
    }
}

function formatAlertTime(tsStr) {
    if (!tsStr) return '—';
    const timeMatch = tsStr.match(/(\d{2}:\d{2}:\d{2})/);
    const dateMatch = tsStr.match(/(\d{4}-\d{2}-\d{2})/);
    const timeStr = timeMatch ? timeMatch[1] : tsStr;
    const dateStr = dateMatch ? dateMatch[1] : '';
    return `<div style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #38bdf8; font-size: 0.88rem;">${timeStr} IST</div><div style="color: var(--text-muted); font-size: 0.72rem;">${dateStr}</div>`;
}

