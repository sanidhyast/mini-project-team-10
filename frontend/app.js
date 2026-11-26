// RailSearch — Frontend Client Application (Team 10)

const API_BASE = window.location.origin;

// State
let currentUser = null;
let currentSearch = { source: '', destination: '', date: '' };
let adminTrainsCache = [];
let debounceTimer = null;
let adminSearchTimer = null;

// ================= Initialization =================

document.addEventListener('DOMContentLoaded', () => {
  // Set default date to today or tomorrow
  const dateInput = document.getElementById('date-input');
  if (dateInput) {
    const today = new Date();
    dateInput.value = today.toISOString().split('T')[0];
    dateInput.min = today.toISOString().split('T')[0];
  }

  // Load user session from localStorage
  loadUserSession();

  // Setup Autocomplete
  setupAutocomplete('src-input', 'src-suggestions');
  setupAutocomplete('dst-input', 'dst-suggestions');
});

// ================= Authentication & Session =================

function loadUserSession() {
  const stored = localStorage.getItem('railsearch_user');
  if (stored) {
    try {
      currentUser = JSON.parse(stored);
    } catch (e) {
      localStorage.removeItem('railsearch_user');
      currentUser = null;
    }
  } else {
    currentUser = null;
  }
  updateNavAuthUI();
}

function updateNavAuthUI() {
  const guestNav = document.getElementById('auth-guest-nav');
  const userNav = document.getElementById('auth-user-nav');
  const nameEl = document.getElementById('nav-user-name');
  const roleEl = document.getElementById('nav-user-role');
  const avatarEl = document.getElementById('nav-user-avatar');
  const adminBtn = document.getElementById('admin-dashboard-btn');
  const authSearch = document.getElementById('irctc-auth-search');
  const guestLogin = document.getElementById('irctc-guest-login');
  const resultsContainer = document.getElementById('results-container');
  const statusBanner = document.getElementById('status-banner');
  const togetherDrawer = document.getElementById('together-merge-card');

  if (currentUser) {
    if (guestNav) guestNav.style.display = 'none';
    if (userNav) userNav.style.display = 'flex';

    if (nameEl) nameEl.textContent = currentUser.full_name || 'User';
    if (avatarEl) avatarEl.textContent = (currentUser.full_name || 'U').charAt(0).toUpperCase();

    if (currentUser.role === 'ADMIN') {
      if (roleEl) {
        roleEl.textContent = 'Administrator';
        roleEl.style.color = '#b45309';
      }
      if (adminBtn) adminBtn.style.display = 'inline-flex';
    } else {
      if (roleEl) {
        roleEl.textContent = 'Passenger';
        roleEl.style.color = '#2563eb';
      }
      if (adminBtn) adminBtn.style.display = 'none';
    }

    // Authenticated: reveal BOOK TICKET search form, hide inline guest login
    if (authSearch) authSearch.style.display = 'block';
    if (guestLogin) guestLogin.style.display = 'none';
  } else {
    // Unauthenticated: hide search option and results, display inline guest login
    if (guestNav) guestNav.style.display = 'flex';
    if (userNav) userNav.style.display = 'none';
    if (adminBtn) adminBtn.style.display = 'none';

    if (authSearch) authSearch.style.display = 'none';
    if (guestLogin) guestLogin.style.display = 'block';
    if (resultsContainer) resultsContainer.style.display = 'none';
    if (statusBanner) statusBanner.style.display = 'none';
    if (togetherDrawer) togetherDrawer.style.display = 'none';
  }
}

async function handleInlineLogin(e) {
  e.preventDefault();
  const idEl = document.getElementById('inline-login-id');
  const passEl = document.getElementById('inline-login-pass');
  const btn = document.getElementById('inline-login-btn');
  if (!idEl || !passEl) return;

  const identifier = idEl.value.trim();
  const password = passEl.value;

  btn.disabled = true;
  btn.textContent = 'Signing In...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier, password })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.textContent = 'Sign In to Search Trains';

    if (!res.ok) {
      showToast(data.message || 'Invalid credentials', 'error');
      return;
    }

    currentUser = data.user;
    localStorage.setItem('railsearch_user', JSON.stringify(data.user));
    if (data.token) localStorage.setItem('railsearch_token', data.token);

    updateNavAuthUI();
    showToast(`Welcome back, ${currentUser.full_name}! You can now search trains.`, 'success');

    if (currentUser.role === 'ADMIN') {
      showToast('Admin Mode: Click "Timetable Manager" in navbar to manage train schedules.', 'info', 5000);
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Sign In to Search Trains';
    showToast(`Error: ${err.message}`, 'error');
  }
}

function quickFillAndLoginAdmin() {
  const idEl = document.getElementById('inline-login-id');
  const passEl = document.getElementById('inline-login-pass');
  if (idEl) idEl.value = 'admin';
  if (passEl) passEl.value = 'admin123';
  const btn = document.getElementById('inline-login-btn');
  if (btn) btn.click();
}

function handleLogout() {
  currentUser = null;
  localStorage.removeItem('railsearch_user');
  localStorage.removeItem('railsearch_token');
  updateNavAuthUI();
  showToast('Logged out successfully. Please sign in to search trains.', 'info');
}

// Register Modal Flow
let pendingRegEmail = '';

function openRegisterModal() {
  closeLoginModal();
  document.getElementById('register-modal').style.display = 'flex';
  document.getElementById('register-step1-form').style.display = 'block';
  document.getElementById('register-step2-form').style.display = 'none';
  document.getElementById('register-step3-form').style.display = 'none';
  document.getElementById('register-modal-title').textContent = 'Create RailSearch Account';
  document.getElementById('register-step-sub').textContent = 'Enter your details to register';
}

function closeRegisterModal() {
  document.getElementById('register-modal').style.display = 'none';
}

async function handleRegisterStep1(e) {
  e.preventDefault();
  const fullName = document.getElementById('reg-fullname').value.trim();
  const mobile = document.getElementById('reg-mobile').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const dob = document.getElementById('reg-dob').value;
  const gender = document.getElementById('reg-gender').value;

  const btn = document.getElementById('reg-step1-btn');
  btn.disabled = true;
  btn.innerHTML = 'Sending Code...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/register-init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name: fullName, mobile, email, dob, gender })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '<span>Send Verification OTP</span>';

    if (!res.ok) {
      showToast(data.message || 'Registration failed', 'error');
      return;
    }

    pendingRegEmail = email;
    document.getElementById('otp-display-email').textContent = email;

    // Check if simulated code was returned
    const simBadge = document.getElementById('otp-simulation-hint');
    if (data.simulated_otp) {
      simBadge.style.display = 'inline-block';
      simBadge.textContent = `Test Code: ${data.simulated_otp}`;
      document.getElementById('reg-otp').value = data.simulated_otp;
      showToast(`Verification code generated: ${data.simulated_otp}`, 'info', 6000);
    } else {
      simBadge.style.display = 'none';
      showToast(data.message || 'Verification code sent to email', 'success');
    }

    // Switch to Step 2
    document.getElementById('register-step1-form').style.display = 'none';
    document.getElementById('register-step2-form').style.display = 'block';
    document.getElementById('register-modal-title').textContent = 'Verify Your Email';
    document.getElementById('register-step-sub').textContent = 'Step 2 of 3: Enter the 6-digit verification code';
    document.getElementById('reg-otp').focus();

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<span>Send Verification OTP</span>';
    showToast(`Error: ${err.message}`, 'error');
  }
}

function backToRegisterStep1() {
  document.getElementById('register-step2-form').style.display = 'none';
  document.getElementById('register-step1-form').style.display = 'block';
  document.getElementById('register-modal-title').textContent = 'Create RailSearch Account';
  document.getElementById('register-step-sub').textContent = 'Enter your details to register';
}

async function handleRegisterStep2(e) {
  e.preventDefault();
  const otp = document.getElementById('reg-otp').value.trim();
  const btn = document.getElementById('reg-step2-btn');
  btn.disabled = true;
  btn.innerHTML = 'Verifying...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/verify-otp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: pendingRegEmail, otp })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '<span>Verify OTP</span>';

    if (!res.ok) {
      showToast(data.message || 'OTP verification failed', 'error');
      return;
    }

    showToast('Email verified successfully! Now create your password.', 'success');

    // Switch to Step 3
    document.getElementById('register-step2-form').style.display = 'none';
    document.getElementById('register-step3-form').style.display = 'block';
    document.getElementById('register-modal-title').textContent = 'Set Your Password';
    document.getElementById('register-step-sub').textContent = 'Step 3 of 3: Choose a secure password';
    document.getElementById('reg-password').focus();

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<span>Verify OTP</span>';
    showToast(`Error: ${err.message}`, 'error');
  }
}

async function resendOtp() {
  if (!pendingRegEmail) return;
  showToast('Resending OTP code...', 'info');
  const eventFake = { preventDefault: () => {} };
  handleRegisterStep1(eventFake);
}

async function handleRegisterStep3(e) {
  e.preventDefault();
  const password = document.getElementById('reg-password').value;
  const confirmPassword = document.getElementById('reg-confirm-password').value;

  if (password !== confirmPassword) {
    showToast('Passwords do not match.', 'error');
    return;
  }
  if (password.length < 6) {
    showToast('Password must be at least 6 characters.', 'error');
    return;
  }

  const btn = document.getElementById('reg-step3-btn');
  btn.disabled = true;
  btn.innerHTML = 'Creating Account...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/complete-registration`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: pendingRegEmail, password, confirm_password: confirmPassword })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '<span>Complete Registration & Sign In</span>';

    if (!res.ok) {
      showToast(data.message || 'Failed to complete registration', 'error');
      return;
    }

    closeRegisterModal();
    showToast('Account created successfully! Please sign in.', 'success', 5000);

    // Open Login Modal with pre-filled email
    openLoginModal();
    document.getElementById('login-id').value = pendingRegEmail;
    document.getElementById('login-pass').focus();

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<span>Complete Registration & Sign In</span>';
    showToast(`Error: ${err.message}`, 'error');
  }
}

// Login Modal
function openLoginModal() {
  closeRegisterModal();
  document.getElementById('login-modal').style.display = 'flex';
  document.getElementById('login-id').focus();
}

function closeLoginModal() {
  document.getElementById('login-modal').style.display = 'none';
}

function switchToRegister() {
  closeLoginModal();
  openRegisterModal();
}

function fillAdminCredentials() {
  document.getElementById('login-id').value = 'admin';
  document.getElementById('login-pass').value = 'admin123';
}

async function handleLogin(e) {
  e.preventDefault();
  const identifier = document.getElementById('login-id').value.trim();
  const password = document.getElementById('login-pass').value;

  const btn = document.getElementById('login-submit-btn');
  btn.disabled = true;
  btn.innerHTML = 'Signing In...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier, password })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '<span>Sign In</span>';

    if (!res.ok) {
      showToast(data.message || 'Invalid credentials', 'error');
      return;
    }

    currentUser = data.user;
    localStorage.setItem('railsearch_user', JSON.stringify(data.user));
    if (data.token) localStorage.setItem('railsearch_token', data.token);

    closeLoginModal();
    updateNavAuthUI();
    showToast(`Welcome back, ${currentUser.full_name}!`, 'success');

    if (currentUser.role === 'ADMIN') {
      showToast('Admin Portal unlocked. Click "Timetable Manager" to manage trains.', 'info', 5000);
    }

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '<span>Sign In</span>';
    showToast(`Error: ${err.message}`, 'error');
  }
}

// ================= Unified Journey Search =================

async function handleJourneySearch(e) {
  e.preventDefault();
  if (!currentUser) {
    showToast('Please sign in or create an account to search trains.', 'warning');
    openLoginModal();
    return;
  }
  const src = document.getElementById('src-input').value.trim().toUpperCase();
  const dst = document.getElementById('dst-input').value.trim().toUpperCase();
  const date = document.getElementById('date-input').value;

  if (src === dst) {
    showToast('Source and Destination stations must be distinct.', 'error');
    return;
  }

  currentSearch = { source: src, destination: dst, date };

  // Hide co-traveler drawer on new search
  toggleTogetherDrawer(false);

  showLoading('Searching direct and smart connecting routes (E1 Worker Pool)...');

  try {
    const url = `${API_BASE}/api/v1/search/journey?source=${encodeURIComponent(src)}&destination=${encodeURIComponent(dst)}&date=${encodeURIComponent(date)}`;
    const res = await fetch(url);
    const data = await res.json();
    hideLoading();

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
    renderServerError(`Server or network unreachable: ${err.message}`);
  }
}

function renderJourneyResults(response, src, dst) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  const modeBadge = document.getElementById('banner-mode-badge');
  const bannerText = document.getElementById('banner-text');
  const bannerLatency = document.getElementById('banner-latency');

  container.style.display = 'block';
  banner.style.display = 'flex';
  bannerLatency.textContent = `${response.response_time_ms || 0} ms`;

  const results = response.data || [];
  const mode = response.mode || 'DIRECT';

  // Co-Traveler / Travel Together Callout Banner
  const coTravelerBannerHTML = `
    <div class="travel-together-invitation-card" id="together-invite-banner">
      <div class="invite-content">
        <div class="invite-icon">🤝</div>
        <div class="invite-text">
          <h4>Traveling with friends boarding from different stations?</h4>
          <p>Find shared trains heading to <strong>${dst}</strong> and coordinate where you can meet on board!</p>
        </div>
      </div>
      <button type="button" class="accent-btn" onclick="openTravelTogetherDrawer()">
        <span>+ Add Co-Travelers</span>
      </button>
    </div>
  `;

  if (mode === 'DIRECT') {
    modeBadge.className = 'mode-badge direct';
    modeBadge.textContent = 'DIRECT EXPRESS';
    bannerText.textContent = `Found ${results.length} direct train(s) from ${src} to ${dst}`;

    if (results.length === 0) {
      renderEmptyState('NO_DIRECT', 'No direct trains found.');
      return;
    }

    const cardsHTML = results.map(train => `
      <div class="result-card">
        <div class="card-top">
          <div class="train-title-group">
            <span class="train-no-badge">${train.train_no}</span>
            <span class="train-name">${train.train_name}</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            ${train.distance_formatted ? `
            <div class="distance-badge" title="Track Distance">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
              ${train.distance_formatted}
            </div>` : ''}
            <div class="duration-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              ${train.duration_formatted}
            </div>
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

        <div class="card-footer-action">
          <button type="button" class="accent-btn-sm" onclick="openTravelTogetherDrawer()">
            🤝 Coordinate Group Trip on this Corridor
          </button>
        </div>
      </div>
    `).join('');

    container.innerHTML = coTravelerBannerHTML + cardsHTML;

  } else if (mode === 'CONNECTING') {
    modeBadge.className = 'mode-badge connecting';
    modeBadge.textContent = 'CONNECTING (DEPTH 2)';
    bannerText.textContent = `No direct trains. Routed via connecting hub ranked by MINIMUM DISTANCE (Transfer Buffer ≥ 30m enforced). Found ${results.length} journey(s).`;

    if (results.length === 0) {
      renderEmptyState('NO_ROUTE', `No feasible 2-leg connecting journey found between ${src} and ${dst} with ≥ 30 min buffer.`);
      return;
    }

    const cardsHTML = results.map(j => `
      <div class="result-card">
        <div class="card-top">
          <div class="train-title-group">
            <span class="badge team-badge">Rank #${j.rank}</span>
            <span class="train-name">Via ${j.transfer_station_name} (${j.transfer_station})</span>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <div class="distance-badge" title="Total Journey Distance">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
              ${j.total_distance_formatted || ''}
            </div>
            <div class="duration-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              Total: ${j.total_duration_formatted}
            </div>
          </div>
        </div>

        <div class="connecting-timeline">
          <!-- Leg 1 -->
          <div class="leg-card">
            <div class="leg-header">
              <span>LEG 1 · Train ${j.leg1.train_no} (${j.leg1.train_name}) · ${j.leg1.distance_formatted || ''}</span>
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
              <span>LEG 2 · Train ${j.leg2.train_no} (${j.leg2.train_name}) · ${j.leg2.distance_formatted || ''}</span>
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

    container.innerHTML = coTravelerBannerHTML + cardsHTML;

  } else if (response.status === 'NO_ROUTE') {
    modeBadge.className = 'mode-badge error';
    modeBadge.textContent = 'NO_ROUTE';
    bannerText.textContent = `No direct or connecting routes found between ${src} and ${dst}.`;
    renderEmptyState('NO_ROUTE', `No route exists between station ${src} and ${dst} within depth-2 BFS with ≥ 30m transfer buffer.`);
  }
}

// ================= Integrated "Travel Together" Feature =================

function openTravelTogetherDrawer() {
  const drawer = document.getElementById('together-merge-card');
  const lockedDst = document.getElementById('together-locked-dst');
  const lockedDate = document.getElementById('together-locked-date');

  // Use current search params or fallback
  const dst = currentSearch.destination || document.getElementById('dst-input').value.trim().toUpperCase() || 'CSMT';
  const dt = currentSearch.date || document.getElementById('date-input').value;
  const src = currentSearch.source || document.getElementById('src-input').value.trim().toUpperCase() || 'SBC';

  lockedDst.textContent = dst;
  lockedDate.textContent = dt;

  // Initialize origins container with 2 origins: You (src) + Friend (e.g. UBL)
  const container = document.getElementById('origins-container');
  container.innerHTML = '';
  addOriginInput(src, 'You (Primary Origin)');
  addOriginInput(src === 'UBL' ? 'DVG' : 'UBL', 'Friend 1');

  drawer.style.display = 'block';
  drawer.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function toggleTogetherDrawer(show) {
  const drawer = document.getElementById('together-merge-card');
  if (drawer) drawer.style.display = show ? 'block' : 'none';
}

function addOriginInput(initialValue = '', label = '') {
  const container = document.getElementById('origins-container');
  const count = container.children.length;
  const row = document.createElement('div');
  row.className = 'origin-input-row';

  row.innerHTML = `
    <span class="origin-index">${count + 1}</span>
    <div class="autocomplete-wrapper" style="flex: 1;">
      <input type="text" class="together-origin-input" placeholder="e.g. ${count === 0 ? 'SBC' : 'UBL'}" autocomplete="off" value="${initialValue}" required>
      <div class="suggestions-list"></div>
    </div>
    ${count >= 2 ? `
    <button type="button" class="origin-remove-btn" title="Remove Station" onclick="removeOriginInput(this)">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
    </button>` : `<div style="width: 26px;"></div>`}
  `;

  container.appendChild(row);
  const input = row.querySelector('.together-origin-input');
  const list = row.querySelector('.suggestions-list');
  setupAutocompleteElement(input, list);
}

function removeOriginInput(btn) {
  const container = document.getElementById('origins-container');
  if (container.children.length <= 2) {
    showToast('At least 2 boarding origin stations are required for Travel Together.', 'warning');
    return;
  }
  btn.closest('.origin-input-row').remove();
  // Renumber
  Array.from(container.children).forEach((row, idx) => {
    row.querySelector('.origin-index').textContent = idx + 1;
  });
}

async function executeTogetherSearch() {
  if (!currentUser) {
    showToast('Please sign in or create an account to use Travel Together.', 'warning');
    openLoginModal();
    return;
  }
  const originInputs = document.querySelectorAll('.together-origin-input');
  const origins = Array.from(originInputs).map(i => i.value.trim().toUpperCase()).filter(Boolean);
  const dst = document.getElementById('together-locked-dst').textContent.trim();
  const date = document.getElementById('together-locked-date').textContent.trim();

  if (origins.length < 2) {
    showToast('Please specify at least 2 distinct origin stations.', 'error');
    return;
  }
  const uniqueOrigins = new Set(origins);
  if (uniqueOrigins.size !== origins.length) {
    showToast('Origin stations must be distinct from each other.', 'error');
    return;
  }
  if (origins.includes(dst)) {
    showToast(`Destination station ${dst} cannot be one of the origins.`, 'error');
    return;
  }

  showLoading('Finding common trains and optimal meeting station (Algorithm B)...');

  try {
    const res = await fetch(`${API_BASE}/api/v1/search/travel-together`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origins, destination: dst, date })
    });
    const data = await res.json();
    hideLoading();

    renderTravelTogetherResults(data, origins, dst);
  } catch (err) {
    hideLoading();
    renderServerError(`Error searching group trains: ${err.message}`);
  }
}

function renderTravelTogetherResults(response, origins, dst) {
  const container = document.getElementById('results-container');
  const banner = document.getElementById('status-banner');
  const modeBadge = document.getElementById('banner-mode-badge');
  const bannerText = document.getElementById('banner-text');
  const bannerLatency = document.getElementById('banner-latency');

  container.style.display = 'block';
  banner.style.display = 'flex';
  modeBadge.className = 'mode-badge together';
  modeBadge.textContent = 'TRAVEL TOGETHER (ALGORITHM B)';
  bannerLatency.textContent = `${response.response_time_ms || 0} ms`;

  const results = response.data || [];
  if (response.status === 'NO_COMMON' || results.length === 0) {
    bannerText.textContent = `No common trains found connecting origins [${origins.join(', ')}] to ${dst}.`;
    renderEmptyState('NO_COMMON', `None of the available trains stop at all origin stations [${origins.join(', ')}] and destination ${dst} on this date.`);
    return;
  }

  bannerText.textContent = `Found ${results.length} shared train(s) connecting all origins [${origins.join(', ')}] to ${dst}`;

  container.innerHTML = results.map(t => `
    <div class="result-card">
      <div class="card-top">
        <div class="train-title-group">
          <span class="train-no-badge">${t.train_no}</span>
          <span class="train-name">${t.train_name}</span>
        </div>
        <div class="duration-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          Combined Trip: ${t.together_duration_formatted}
        </div>
      </div>

      <!-- Optimal Joining Station & Time Badge -->
      <div class="joining-highlight-box">
        <div>
          <span class="joining-station-title">Optimal Joining Station & Time</span>
          <div class="joining-station-val">🤝 ${t.joining_station_name} (${t.joining_station})</div>
        </div>
        <div style="text-align: right;">
          <span style="font-size: 0.75rem; color: #86198f; font-weight: 700;">Departure After Joining</span>
          <div style="font-size: 1.15rem; font-weight: 800; color: #701a75;">${t.joining_time}</div>
        </div>
      </div>

      <!-- Individual Passenger Boarding Table -->
      <table class="boardings-table">
        <thead>
          <tr>
            <th>Passenger Origin</th>
            <th>Station Name</th>
            <th>Boarding Dep Time</th>
            <th>Arrival at ${dst}</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          ${(t.boardings || []).map(b => `
            <tr style="${b.is_joining_station ? 'background: #fdf4ff; font-weight: 600;' : ''}">
              <td><span class="station-code-text" style="font-weight: 700;">${b.station_code}</span></td>
              <td>${b.station_name}</td>
              <td>${b.departure_time}</td>
              <td>${t.destination_arrival_time}</td>
              <td>
                ${b.is_joining_station ? '<span class="badge" style="background: #f0abfc; color: #701a75;">★ Group Joins Here</span>' : '<span style="color: #64748b;">Early Boarder</span>'}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `).join('');
}

// ================= Autocomplete Helpers =================

function setupAutocomplete(inputId, listId) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  if (!input || !list) return;
  setupAutocompleteElement(input, list);
}

function setupAutocompleteElement(inputEl, listEl) {
  inputEl.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const val = inputEl.value.trim();
    if (val.length < 1) {
      listEl.innerHTML = '';
      listEl.classList.remove('open');
      return;
    }
    debounceTimer = setTimeout(() => fetchStationSuggestions(val, listEl, inputEl), 150);
  });

  inputEl.addEventListener('focus', () => {
    if (inputEl.value.trim().length >= 1) {
      listEl.classList.add('open');
    }
  });

  document.addEventListener('click', (e) => {
    if (!inputEl.contains(e.target) && !listEl.contains(e.target)) {
      listEl.classList.remove('open');
    }
  });
}

async function fetchStationSuggestions(query, listEl, inputEl) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/stations?query=${encodeURIComponent(query)}`);
    const stations = await res.json();
    if (!stations || stations.length === 0) {
      listEl.innerHTML = '<div style="padding: 0.75rem; color: #94a3b8; font-size: 0.8125rem;">No matching stations</div>';
      listEl.classList.add('open');
      return;
    }

    listEl.innerHTML = stations.slice(0, 10).map(s => `
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
        inputEl.value = item.dataset.code;
        listEl.classList.remove('open');
      });
    });
  } catch (e) {
    console.error('Autocomplete fetch error:', e);
  }
}

function swapStations() {
  const src = document.getElementById('src-input');
  const dst = document.getElementById('dst-input');
  const tmp = src.value;
  src.value = dst.value;
  dst.value = tmp;
}

function applyPreset(src, dst) {
  if (!currentUser) {
    showToast('Please sign in or create an account to search trains.', 'warning');
    openLoginModal();
    return;
  }
  document.getElementById('src-input').value = src;
  document.getElementById('dst-input').value = dst;
  document.getElementById('journey-submit-btn').click();
}

function resetToHome() {
  const banner = document.getElementById('status-banner');
  if (banner) banner.style.display = 'none';
  const together = document.getElementById('together-merge-card');
  if (together) together.style.display = 'none';
  const container = document.getElementById('results-container');
  if (container) {
    container.innerHTML = '';
    container.style.display = 'none';
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ================= Admin Modal & Timetable CRUD =================

function openAdminModal() {
  if (!currentUser || currentUser.role !== 'ADMIN') {
    showToast('Admin privilege required. Sign in as admin.', 'error');
    openLoginModal();
    return;
  }
  document.getElementById('admin-modal').style.display = 'flex';
  switchAdminTab('trains');
  loadAdminTrains();
}

function closeAdminModal() {
  document.getElementById('admin-modal').style.display = 'none';
}

function switchAdminTab(tab) {
  document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`admin-tab-${tab}`).classList.add('active');

  document.getElementById('admin-view-trains').style.display = tab === 'trains' ? 'block' : 'none';
  document.getElementById('admin-view-smtp').style.display = tab === 'smtp' ? 'block' : 'none';

  if (tab === 'smtp') {
    loadSmtpConfig();
  }
}

function debounceAdminTrainSearch() {
  clearTimeout(adminSearchTimer);
  adminSearchTimer = setTimeout(loadAdminTrains, 250);
}

async function loadAdminTrains() {
  const search = document.getElementById('admin-train-search').value.trim();
  const tbody = document.getElementById('admin-trains-tbody');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #94a3b8; padding: 1.5rem;">Loading timetable...</td></tr>';

  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/trains?search=${encodeURIComponent(search)}&limit=50`);
    const data = await res.json();
    adminTrainsCache = data.trains || [];

    if (adminTrainsCache.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #94a3b8; padding: 1.5rem;">No trains found.</td></tr>';
      return;
    }

    tbody.innerHTML = adminTrainsCache.map(t => `
      <tr>
        <td><strong>${t.train_no}</strong></td>
        <td>${t.train_name}</td>
        <td>${t.source} → ${t.destination}</td>
        <td><span class="badge" style="background: #f1f5f9; color: #475569;">${t.stops_count} stops</span></td>
        <td><small style="color: #64748b;">${(t.running_days || []).join(', ')}</small></td>
        <td>
          <div class="admin-row-actions">
            <button type="button" class="edit-btn-xs" onclick="editAdminTrain('${t.train_no}')">Edit</button>
            <button type="button" class="delete-btn-xs" onclick="deleteAdminTrain('${t.train_no}')">Delete</button>
          </div>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color: #dc2626; text-align: center; padding: 1rem;">Failed to load trains: ${err.message}</td></tr>`;
  }
}

async function rebuildPersistentIndex() {
  const btn = document.getElementById('admin-rebuild-btn');
  btn.disabled = true;
  btn.innerHTML = 'Rebuilding Snapshot...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/rebuild-index`, { method: 'POST' });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '⚡ Rebuild Index Snapshot';

    showToast(`Persistent Index Snapshot rebuilt in ${data.reload_ms} ms!`, 'success', 6000);
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '⚡ Rebuild Index Snapshot';
    showToast(`Rebuild failed: ${err.message}`, 'error');
  }
}

// Train Add/Edit Modal
function openTrainEditorModal(trainNo = null) {
  document.getElementById('train-editor-modal').style.display = 'flex';
  const tbody = document.getElementById('train-stops-tbody');
  tbody.innerHTML = '';

  if (!trainNo) {
    document.getElementById('train-editor-title').textContent = 'Add New Train to Timetable';
    document.getElementById('edit-train-no').value = '';
    document.getElementById('edit-train-no').readOnly = false;
    document.getElementById('edit-train-name').value = '';
    document.querySelectorAll('input[name="edit-days"]').forEach(cb => cb.checked = true);

    // Add 2 initial stop rows
    addEditorStopRow('SBC', 1, '06:00:00', '06:00:00', 1, 0.0);
    addEditorStopRow('CSMT', 2, '23:30:00', '23:30:00', 1, 1139.0);
  } else {
    document.getElementById('train-editor-title').textContent = `Edit Train ${trainNo}`;
    document.getElementById('edit-train-no').value = trainNo;
    document.getElementById('edit-train-no').readOnly = true;
    loadTrainDetailsForEdit(trainNo);
  }
}

function closeTrainEditorModal() {
  document.getElementById('train-editor-modal').style.display = 'none';
}

async function loadTrainDetailsForEdit(trainNo) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/trains/${encodeURIComponent(trainNo)}`);
    const train = await res.json();
    document.getElementById('edit-train-name').value = train.train_name;

    const running = new Set(train.running_days || []);
    document.querySelectorAll('input[name="edit-days"]').forEach(cb => {
      cb.checked = running.has(cb.value);
    });

    const tbody = document.getElementById('train-stops-tbody');
    tbody.innerHTML = '';
    (train.stops || []).forEach(s => {
      addEditorStopRow(s.station_code, s.stop_seq, s.arrival_time, s.departure_time, s.day_no, s.distance_km);
    });
  } catch (e) {
    showToast(`Failed to load train details: ${e.message}`, 'error');
  }
}

function addEditorStopRow(station = '', seq = null, arr = '00:00:00', dep = '00:00:00', day = 1, dist = 0.0) {
  const tbody = document.getElementById('train-stops-tbody');
  const count = tbody.children.length;
  const currentSeq = seq || (count + 1);

  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><strong>${currentSeq}</strong><input type="hidden" class="stop-seq-input" value="${currentSeq}"></td>
    <td><input type="text" class="stop-station-input" value="${station}" placeholder="STATION" style="text-transform: uppercase;" required></td>
    <td><input type="text" class="stop-arr-input" value="${arr}" placeholder="HH:MM:SS" required></td>
    <td><input type="text" class="stop-dep-input" value="${dep}" placeholder="HH:MM:SS" required></td>
    <td><input type="number" class="stop-day-input" value="${day}" min="1" max="5" style="width: 50px;"></td>
    <td><input type="number" step="0.1" class="stop-dist-input" value="${dist}" style="width: 70px;"></td>
    <td><button type="button" class="delete-btn-xs" onclick="removeEditorStopRow(this)">✕</button></td>
  `;
  tbody.appendChild(tr);
}

function removeEditorStopRow(btn) {
  const tbody = document.getElementById('train-stops-tbody');
  if (tbody.children.length <= 2) {
    showToast('A train must have at least 2 stops (origin and destination).', 'warning');
    return;
  }
  btn.closest('tr').remove();
  // Re-number stop sequences
  Array.from(tbody.children).forEach((row, idx) => {
    row.querySelector('strong').textContent = idx + 1;
    row.querySelector('.stop-seq-input').value = idx + 1;
  });
}

async function handleSaveTrain(e) {
  e.preventDefault();
  const trainNo = document.getElementById('edit-train-no').value.trim();
  const trainName = document.getElementById('edit-train-name').value.trim();

  const days = [];
  document.querySelectorAll('input[name="edit-days"]:checked').forEach(cb => days.push(cb.value));

  const stops = [];
  const rows = document.querySelectorAll('#train-stops-tbody tr');
  rows.forEach((r, idx) => {
    stops.push({
      station_code: r.querySelector('.stop-station-input').value.trim().toUpperCase(),
      stop_seq: idx + 1,
      arrival_time: r.querySelector('.stop-arr-input').value.trim(),
      departure_time: r.querySelector('.stop-dep-input').value.trim(),
      day_no: parseInt(r.querySelector('.stop-day-input').value) || 1,
      distance_km: parseFloat(r.querySelector('.stop-dist-input').value) || 0.0
    });
  });

  const btn = document.getElementById('save-train-btn');
  btn.disabled = true;
  btn.innerHTML = 'Saving Train...';

  try {
    const isNew = !document.getElementById('edit-train-no').readOnly;
    const method = isNew ? 'POST' : 'PUT';
    const url = isNew ? `${API_BASE}/api/v1/admin/trains` : `${API_BASE}/api/v1/admin/trains/${encodeURIComponent(trainNo)}`;

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ train_no: trainNo, train_name: trainName, running_days: days, stops })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = 'Save Train to Database & Index';

    if (!res.ok) {
      showToast(data.message || 'Failed to save train', 'error');
      return;
    }

    closeTrainEditorModal();
    showToast(`Train ${trainNo} saved & index updated successfully!`, 'success');
    loadAdminTrains();

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = 'Save Train to Database & Index';
    showToast(`Error saving train: ${err.message}`, 'error');
  }
}

function editAdminTrain(trainNo) {
  openTrainEditorModal(trainNo);
}

async function deleteAdminTrain(trainNo) {
  if (!confirm(`Are you sure you want to delete Train ${trainNo} from the timetable and index?`)) return;

  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/trains/${encodeURIComponent(trainNo)}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast(`Train ${trainNo} deleted successfully.`, 'info');
      loadAdminTrains();
    } else {
      showToast(data.detail || 'Delete failed', 'error');
    }
  } catch (e) {
    showToast(`Error deleting train: ${e.message}`, 'error');
  }
}

// SMTP Settings
async function loadSmtpConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/smtp-config`);
    const cfg = await res.json();
    document.getElementById('smtp-email').value = cfg.smtp_user || '';
    document.getElementById('smtp-app-password').value = cfg.smtp_password || '';
    document.getElementById('smtp-host').value = cfg.smtp_host || 'smtp.gmail.com';
    document.getElementById('smtp-port').value = cfg.smtp_port || 587;
  } catch (e) {
    console.error('Error fetching SMTP config:', e);
  }
}

async function handleSaveSmtp(e) {
  e.preventDefault();
  const smtpUser = document.getElementById('smtp-email').value.trim();
  const smtpPassword = document.getElementById('smtp-app-password').value.trim();
  const smtpHost = document.getElementById('smtp-host').value.trim();
  const smtpPort = parseInt(document.getElementById('smtp-port').value) || 587;

  const btn = document.getElementById('save-smtp-btn');
  btn.disabled = true;
  btn.innerHTML = 'Saving Credentials...';

  try {
    const res = await fetch(`${API_BASE}/api/v1/admin/smtp-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        smtp_user: smtpUser,
        smtp_password: smtpPassword,
        smtp_host: smtpHost,
        smtp_port: smtpPort
      })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = 'Save & Update SMTP Credentials';

    showToast('Gmail SMTP credentials updated successfully!', 'success');
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = 'Save & Update SMTP Credentials';
    showToast(`Failed to save SMTP: ${err.message}`, 'error');
  }
}

// ================= Render Helpers & Feedback =================

function showLoading(msg) {
  document.getElementById('loading-state').style.display = 'block';
  document.getElementById('loading-text').textContent = msg;
  document.getElementById('status-banner').style.display = 'none';
  document.getElementById('results-container').innerHTML = '';
}

function hideLoading() {
  document.getElementById('loading-state').style.display = 'none';
}

function renderValidationError(msg) {
  const container = document.getElementById('results-container');
  container.style.display = 'block';
  const banner = document.getElementById('status-banner');
  banner.style.display = 'flex';
  document.getElementById('banner-mode-badge').className = 'mode-badge error';
  document.getElementById('banner-mode-badge').textContent = '400 VALIDATION ERROR';
  document.getElementById('banner-text').textContent = msg;

  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon-box" style="background: #fef2f2;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <h3>Validation Error</h3>
      <p style="color: #dc2626; font-weight: 600;">${msg}</p>
    </div>
  `;
}

function renderServerError(msg) {
  const container = document.getElementById('results-container');
  container.style.display = 'block';
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon-box" style="background: #fef2f2;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      </div>
      <h3>Search Error</h3>
      <p style="color: #64748b;">${msg}</p>
    </div>
  `;
}

function renderEmptyState(code, msg) {
  const container = document.getElementById('results-container');
  container.style.display = 'block';
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon-box">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <h3>${code}</h3>
      <p>${msg}</p>
    </div>
  `;
}

function showToast(msg, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast-item ${type}`;

  const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
  toast.innerHTML = `
    <div style="display: flex; align-items: center; gap: 0.6rem;">
      <span style="font-weight: 800;">${icon}</span>
      <span>${msg}</span>
    </div>
    <button type="button" style="background: none; border: none; cursor: pointer; color: #94a3b8;" onclick="this.parentElement.remove()">✕</button>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}
