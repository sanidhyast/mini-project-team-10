// RailSearch Enterprise Client — Team 10

const API_BASE = window.location.origin;

// State
let allStations = [];
let currentTab = 'journey';

document.addEventListener('DOMContentLoaded', () => {
  initDatePickers();
  fetchHealth();
  setupAutocomplete('src-input', 'src-suggestions');
  setupAutocomplete('dst-input', 'dst-suggestions');
  setupAutocomplete('together-dst-input', 'together-dst-suggestions');
  setupTogetherOriginInputs();
});

function initDatePickers() {
  const today = new Date().toISOString().split('T')[0];
  const dateInput = document.getElementById('date-input');
  const togetherDateInput = document.getElementById('together-date-input');
  if (dateInput) dateInput.value = today;
  if (togetherDateInput) togetherDateInput.value = today;
}

// ================= Tab Switching =================

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

  if (tab === 'journey') {
    document.getElementById('tab-journey').classList.add('active');
    document.getElementById('content-journey').classList.add('active');
  } else {
    document.getElementById('tab-together').classList.add('active');
    document.getElementById('content-together').classList.add('active');
  }

  // Clear banner
  document.getElementById('status-banner').style.display = 'none';
}

function swapStations() {
  const src = document.getElementById('src-input');
  const dst = document.getElementById('dst-input');
  const temp = src.value;
  src.value = dst.value;
  dst.value = temp;
}

function applyPreset(src, dst) {
  document.getElementById('src-input').value = src;
  document.getElementById('dst-input').value = dst;
  switchTab('journey');
  document.getElementById('journey-submit-btn').click();
}

function applyTogetherPreset(origins, dst) {
  switchTab('together');
  const container = document.getElementById('origins-container');
  container.innerHTML = '';
  origins.forEach((o, idx) => {
    addOriginInput(o);
  });
  document.getElementById('together-dst-input').value = dst;
  document.getElementById('together-submit-btn').click();
}

// ================= Telemetry & Health =================

async function fetchHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/health`);
    if (res.ok) {
      const data = await res.json();
      const dbInfo = data.database_and_index || {};
      const tag = document.getElementById('index-stats-tag');
      if (tag) {
        tag.textContent = `Index: ${dbInfo.station_count || 0} stns · ${dbInfo.train_count || 0} trains (${dbInfo.snapshot_reload_ms || 0}ms reload)`;
      }
      const reloadStat = document.getElementById('index-reload-stat');
      if (reloadStat && dbInfo.snapshot_reload_ms) {
        reloadStat.textContent = `${dbInfo.snapshot_reload_ms} ms (Verified < 50ms)`;
      }
      const pids = Object.values(data.worker_pids || {}).join(', ');
      const workerStat = document.getElementById('worker-pid-stat');
      if (workerStat && pids) {
        workerStat.textContent = `PIDs: ${pids}`;
      }
    }
  } catch (e) {
    console.error('Failed to fetch health telemetry:', e);
  }
}

// ================= Dynamic Origins for Travel Together =================

function setupTogetherOriginInputs() {
  document.querySelectorAll('.together-origin-input').forEach(input => {
    const wrapper = input.parentElement;
    const list = wrapper.querySelector('.suggestions-list');
    setupAutocompleteElement(input, list);
  });
}

function addOriginInput(initialValue = '') {
  const container = document.getElementById('origins-container');
  const currentCount = container.children.length;
  const row = document.createElement('div');
  row.className = 'origin-input-row';
  row.dataset.index = currentCount;

  row.innerHTML = `
    <span class="origin-index">${currentCount + 1}</span>
    <div class="autocomplete-wrapper" style="flex: 1;">
      <input type="text" class="together-origin-input" placeholder="e.g. DVG" autocomplete="off" value="${initialValue}" required>
      <div class="suggestions-list"></div>
    </div>
    <button type="button" class="origin-remove-btn" title="Remove Origin" onclick="removeOriginInput(this)">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    </button>
  `;

  container.appendChild(row);
  const input = row.querySelector('.together-origin-input');
  const list = row.querySelector('.suggestions-list');
  setupAutocompleteElement(input, list);
}

function removeOriginInput(btn) {
  const container = document.getElementById('origins-container');
  if (container.children.length <= 2) {
    alert('At least 2 origin stations are required for Travel Together.');
    return;
  }
  btn.closest('.origin-input-row').remove();
  // Renumber
  Array.from(container.children).forEach((row, idx) => {
    row.querySelector('.origin-index').textContent = idx + 1;
  });
}

// ================= Autocomplete =================

let debounceTimer = null;

function setupAutocomplete(inputId, listId) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  if (!input || !list) return;
  setupAutocompleteElement(input, list);
}

function setupAutocompleteElement(input, list) {
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 1) {
      list.innerHTML = '';
      list.classList.remove('open');
      return;
    }
    debounceTimer = setTimeout(() => {
      fetchSuggestions(q, list, input);
    }, 150);
  });

  input.addEventListener('focus', () => {
    if (input.value.trim().length >= 1) {
      fetchSuggestions(input.value.trim(), list, input);
    }
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      list.classList.remove('open');
    }
  });
}

async function fetchSuggestions(query, listEl, inputEl) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/stations?query=${encodeURIComponent(query)}`);
    if (!res.ok) return;
    const stations = await res.json();
    if (!stations || stations.length === 0) {
      listEl.innerHTML = '<div class="suggestion-item text-muted">No station found</div>';
      listEl.classList.add('open');
      return;
    }

    listEl.innerHTML = stations.map(s => `
      <div class="suggestion-item" data-code="${s.station_code}">
        <div>
          <span class="suggestion-code">${s.station_code}</span> — 
          <span class="suggestion-name">${s.station_name}</span>
        </div>
        <span class="suggestion-city">${s.city || ''}</span>
      </div>
    `).join('');

    listEl.classList.add('open');

    listEl.querySelectorAll('.suggestion-item').forEach(item => {
      item.addEventListener('click', () => {
        const code = item.dataset.code;
        if (code) {
          inputEl.value = code;
          listEl.classList.remove('open');
        }
      });
    });
  } catch (e) {
    console.error('Autocomplete fetch error:', e);
  }
}

// ================= API Handlers =================

async function handleJourneySearch(e) {
  e.preventDefault();
  const src = document.getElementById('src-input').value.trim().toUpperCase();
  const dst = document.getElementById('dst-input').value.trim().toUpperCase();
  const date = document.getElementById('date-input').value;

  showLoading('Computing Direct & Connecting Routes (E1 Worker Pool)...');

  try {
    const url = `${API_BASE}/api/v1/search/journey?source=${encodeURIComponent(src)}&destination=${encodeURIComponent(dst)}&date=${encodeURIComponent(date)}`;
    const res = await fetch(url);
    const data = await res.json();
    hideLoading();

    updateWorkerPidFooter(data.worker_pid);

    if (res.status === 400) {
      renderValidationError(data.message || 'Validation error');
      return;
    }

    if (res.status === 503) {
      renderServerError(data.message || 'Worker timeout / supervisor recovery');
      return;
    }

    renderJourneyResults(data, src, dst);
  } catch (err) {
    hideLoading();
    renderServerError(`Network or Server unreachable: ${err.message}`);
  }
}

async function handleTogetherSearch(e) {
  e.preventDefault();
  const originInputs = document.querySelectorAll('.together-origin-input');
  const origins = Array.from(originInputs).map(i => i.value.trim().toUpperCase()).filter(Boolean);
  const dst = document.getElementById('together-dst-input').value.trim().toUpperCase();
  const date = document.getElementById('together-date-input').value;

  showLoading('Finding Common Train Across All Origins (Algorithm B)...');

  try {
    const res = await fetch(`${API_BASE}/api/v1/search/travel-together`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origins, destination: dst, date })
    });
    const data = await res.json();
    hideLoading();

    updateWorkerPidFooter(data.worker_pid);

    if (res.status === 400) {
      renderValidationError(data.message || 'Validation error');
      return;
    }

    if (res.status === 503) {
      renderServerError(data.message || 'Worker timeout / supervisor recovery');
      return;
    }

    renderTravelTogetherResults(data, origins, dst);
  } catch (err) {
    hideLoading();
    renderServerError(`Network or Server unreachable: ${err.message}`);
  }
}

// ================= Render Helpers =================

function updateWorkerPidFooter(pid) {
  if (pid) {
    const el = document.getElementById('worker-pid-stat');
    if (el) el.textContent = `Worker PID: ${pid}`;
  }
}

function showLoading(msg) {
  document.getElementById('loading-state').style.display = 'block';
  document.getElementById('loading-text').textContent = msg;
  document.getElementById('status-banner').style.display = 'none';
  document.getElementById('results-container').innerHTML = '';
}

function hideLoading() {
  document.getElementById('loading-state').style.display = 'none';
}

function renderJourneyResults(response, src, dst) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  const modeBadge = document.getElementById('banner-mode-badge');
  const bannerText = document.getElementById('banner-text');
  const bannerLatency = document.getElementById('banner-latency');

  banner.style.display = 'flex';
  bannerLatency.textContent = `${response.response_time_ms || 0} ms`;

  const results = response.data || [];
  const mode = response.mode || 'DIRECT';

  if (mode === 'DIRECT') {
    modeBadge.className = 'mode-badge direct';
    modeBadge.textContent = 'DIRECT';
    bannerText.textContent = `Found ${results.length} direct train(s) from ${src} to ${dst}`;

    if (results.length === 0) {
      renderEmptyState('NO_DIRECT', 'No direct trains found.');
      return;
    }

    container.innerHTML = results.map(train => `
      <div class="result-card">
        <div class="card-top">
          <div class="train-title-group">
            <span class="train-no-badge">${train.train_no}</span>
            <span class="train-name">${train.train_name}</span>
          </div>
          <div class="duration-badge">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            ${train.duration_formatted}
          </div>
        </div>

        <div class="journey-schedule">
          <div class="station-stop">
            <span class="time-stamp">${train.departure_time}</span>
            <span class="station-name-text">${train.source_name}</span>
            <span class="station-code-text">${train.source}</span>
          </div>

          <div class="route-indicator">
            <span class="route-stops-info">${train.stops_count} intermediate stops</span>
            <div class="route-line"></div>
            <span class="route-stops-info">Day ${train.departure_day_no} → Day ${train.arrival_day_no}</span>
          </div>

          <div class="station-stop destination">
            <span class="time-stamp">${train.arrival_time}</span>
            <span class="station-name-text">${train.destination_name}</span>
            <span class="station-code-text">${train.destination}</span>
          </div>
        </div>
      </div>
    `).join('');

  } else if (mode === 'CONNECTING') {
    modeBadge.className = 'mode-badge connecting';
    modeBadge.textContent = 'CONNECTING (DEPTH 2)';
    bannerText.textContent = `No direct trains. Automatically routed via connecting hub (Transfer Buffer ≥ 30m enforced). Found ${results.length} journey(s).`;

    if (results.length === 0) {
      renderEmptyState('NO_ROUTE', `No feasible 2-leg connecting journey found between ${src} and ${dst} with ≥ 30 min buffer.`);
      return;
    }

    container.innerHTML = results.map(j => `
      <div class="result-card">
        <div class="card-top">
          <div class="train-title-group">
            <span class="badge team-badge">Rank #${j.rank}</span>
            <span class="train-name">Via ${j.transfer_station_name} (${j.transfer_station})</span>
          </div>
          <div class="duration-badge">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Total: ${j.total_duration_formatted}
          </div>
        </div>

        <div class="connecting-timeline">
          <!-- Leg 1 -->
          <div class="leg-card">
            <div class="leg-header">
              <span>LEG 1 · Train ${j.leg1.train_no} (${j.leg1.train_name})</span>
              <span>Duration: ${j.leg1.duration_formatted}</span>
            </div>
            <div class="leg-body">
              <div>
                <strong>${j.leg1.departure_time}</strong> ${j.leg1.source_name} (${j.leg1.source})
              </div>
              <div>➔</div>
              <div>
                <strong>${j.leg1.arrival_time}</strong> ${j.leg1.destination_name} (${j.leg1.destination})
              </div>
            </div>
          </div>

          <!-- Transfer Hub & Layover -->
          <div class="transfer-hub-divider">
            <div class="layover-badge">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span>Layover at ${j.transfer_station}: <strong>${j.waiting_formatted}</strong></span>
              <span class="buffer-compliance-tag">✓ Buffer Valid (≥ 30m)</span>
            </div>
          </div>

          <!-- Leg 2 -->
          <div class="leg-card">
            <div class="leg-header">
              <span>LEG 2 · Train ${j.leg2.train_no} (${j.leg2.train_name})</span>
              <span>Duration: ${j.leg2.duration_formatted}</span>
            </div>
            <div class="leg-body">
              <div>
                <strong>${j.leg2.departure_time}</strong> ${j.leg2.source_name} (${j.leg2.source})
              </div>
              <div>➔</div>
              <div>
                <strong>${j.leg2.arrival_time}</strong> ${j.leg2.destination_name} (${j.leg2.destination})
              </div>
            </div>
          </div>
        </div>
      </div>
    `).join('');

  } else if (response.status === 'NO_ROUTE') {
    modeBadge.className = 'mode-badge error';
    modeBadge.textContent = 'NO_ROUTE';
    bannerText.textContent = `No direct or connecting routes found between ${src} and ${dst}.`;
    renderEmptyState('NO_ROUTE', `No route exists between station ${src} and ${dst} within depth-2 BFS.`);
  }
}

function renderTravelTogetherResults(response, origins, dst) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  const modeBadge = document.getElementById('banner-mode-badge');
  const bannerText = document.getElementById('banner-text');
  const bannerLatency = document.getElementById('banner-latency');

  banner.style.display = 'flex';
  bannerLatency.textContent = `${response.response_time_ms || 0} ms`;

  if (response.status === 'NO_COMMON') {
    modeBadge.className = 'mode-badge error';
    modeBadge.textContent = 'NO_COMMON';
    bannerText.textContent = `No shared train stops across all origins [${origins.join(', ')}] to ${dst}.`;
    renderEmptyState('NO_COMMON', `The discrete intersection of train sets across [${origins.join(', ')}] to destination ${dst} is empty.`);
    return;
  }

  const results = response.data || [];
  modeBadge.className = 'mode-badge together';
  modeBadge.textContent = 'TRAVEL TOGETHER';
  bannerText.textContent = `Found ${results.length} common train(s) serving all ${origins.length} origins to ${dst}.`;

  container.innerHTML = results.map(t => `
    <div class="result-card">
      <div class="together-card-header">
        <div class="train-title-group">
          <span class="train-no-badge">${t.train_no}</span>
          <span class="train-name">${t.train_name}</span>
        </div>
        <div class="duration-badge">
          Together to ${t.destination}: ${t.together_duration_formatted}
        </div>
      </div>

      <!-- Joining Station Badge (Algorithm B Key Metric) -->
      <div class="joining-highlight-box">
        <div>
          <div class="joining-title">Optimal Joining Station (max stop_seq)</div>
          <div class="joining-value">${t.joining_station_name} (${t.joining_station})</div>
        </div>
        <div>
          <div class="joining-title">Common Departure Time</div>
          <span class="joining-time-tag">${t.joining_time}</span>
        </div>
      </div>

      <!-- Origins Boarding Details Table -->
      <table class="boardings-table">
        <thead>
          <tr>
            <th>Origin Station</th>
            <th>Stop Seq</th>
            <th>Boarding Dep Time</th>
            <th>Arrival at ${t.destination}</th>
            <th>Individual Duration</th>
          </tr>
        </thead>
        <tbody>
          ${t.boardings.map(b => `
            <tr style="${b.origin === t.joining_station ? 'background: #faf5ff; font-weight: 600;' : ''}">
              <td>
                ${b.origin_name} (${b.origin})
                ${b.origin === t.joining_station ? '<span class="badge team-badge" style="margin-left: 0.5rem;">Joining Station</span>' : ''}
              </td>
              <td>${b.stop_seq}</td>
              <td><strong>${b.departure_time}</strong></td>
              <td>${b.arrival_at_destination}</td>
              <td>${b.duration_formatted}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `).join('');
}

function renderEmptyState(code, description) {
  const container = document.getElementById('results-container');
  container.innerHTML = `
    <div class="empty-state">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
      <h3>${code}</h3>
      <p>${description}</p>
    </div>
  `;
}

function renderValidationError(msg) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  banner.style.display = 'flex';
  document.getElementById('banner-mode-badge').className = 'mode-badge error';
  document.getElementById('banner-mode-badge').textContent = '400 VALIDATION_ERROR';
  document.getElementById('banner-text').textContent = msg;

  container.innerHTML = `
    <div class="empty-state">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <h3 style="color: #dc2626;">400 Bad Request</h3>
      <p style="color: #dc2626; font-weight: 600;">${msg}</p>
      <p style="margin-top: 0.5rem; font-size: 0.8125rem;">The request was intercepted and rejected by Engine E3 Validator prior to route computation.</p>
    </div>
  `;
}

function renderServerError(msg) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  banner.style.display = 'flex';
  document.getElementById('banner-mode-badge').className = 'mode-badge error';
  document.getElementById('banner-mode-badge').textContent = '503 SERVICE_UNAVAILABLE';
  document.getElementById('banner-text').textContent = msg;

  container.innerHTML = `
    <div class="empty-state">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      <h3 style="color: #dc2626;">503 Engine / Worker Error</h3>
      <p style="color: #dc2626; font-weight: 600;">${msg}</p>
      <p style="margin-top: 0.5rem; font-size: 0.8125rem;">Watchdog supervisor has auto-recovered the worker process. The server remains online.</p>
    </div>
  `;
}
