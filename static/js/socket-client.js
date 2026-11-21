/*
  socket-client.js
  Initialises the SocketIO connection and handles incoming real-time events.
  Popups, banners and badge counts are managed here.
*/
(function () {
  /* ── Initialise Socket ─────────────────────────────────── */
  const socket = io({ transports: ['polling'] });

  socket.on('connect', () => {
    console.log('[WS] Connected:', socket.id);
  });

  socket.on('connected', (data) => {
    console.log('[WS] Joined room:', data.room);
  });

  /* ── Emergency Alert (Blood Bank side) ─────────────────── */
  socket.on('emergency_alert', (data) => {
    showEmergencyPopup(data);
    updateEmergencyBanner(1);
    bumpSidebarPulse();
  });

  /* ── Inventory Low-Stock (Blood Bank side) ──────────────── */
  socket.on('inventory_update', (data) => {
    showToast(
      data.type === 'critical' ? 'danger' : 'warning',
      `Stock Alert: ${data.blood_group} ${data.component}`,
      data.message
    );
    updateNotifBadge(1);
  });

  /* ── Response Received (Hospital side) ──────────────────── */
  socket.on('response_received', (data) => {
    const badge = data.availability_status === 'Available' ? 'success' : 'info';
    showToast(badge,
      `Response from ${data.bank_name}`,
      `${data.availability_status} – ${data.units_available} units available.`
    );
    updateNotifBadge(1);
    // Optionally refresh request list
    if (typeof refreshRequests === 'function') refreshRequests();
  });

  /* ── Emergency Popup ────────────────────────────────────── */
  window._activeEmergencyPopup = null;

  function showEmergencyPopup(data) {
    // Remove existing popup if any
    if (window._activeEmergencyPopup) window._activeEmergencyPopup.remove();

    const hintClass  = data.status_hint.includes('Potentially') ? '' : 'unavailable';
    const reqBy      = data.required_by ? new Date(data.required_by).toLocaleString() : 'ASAP';
    const urgClass   = data.urgency_level === 'Critical' ? 'badge-critical' : (data.urgency_level === 'High' ? 'badge-high' : 'badge-medium');

    const overlay = document.createElement('div');
    overlay.className = 'emergency-popup-overlay';
    overlay.id = 'ep-overlay';
    overlay.innerHTML = `
      <div class="emergency-popup" role="dialog" aria-modal="true" aria-label="Emergency Blood Request">
        <div class="emergency-popup-header">
          <div class="ep-icon">🚨</div>
          <div>
            <h3>Emergency Blood Request</h3>
            <p>Requires immediate attention</p>
          </div>
        </div>
        <div class="emergency-popup-body">
          <div class="ep-row">
            <label>Requesting Hospital</label>
            <strong>${escHtml(data.hospital_name)}</strong>
          </div>
          <div class="ep-row">
            <label>Blood Group</label>
            <strong style="color:var(--primary);font-size:1.1rem;">${escHtml(data.blood_group)}</strong>
          </div>
          <div class="ep-row">
            <label>Component</label>
            <strong>${escHtml(data.component)}</strong>
          </div>
          <div class="ep-row">
            <label>Units Required</label>
            <strong>${data.units_required}</strong>
          </div>
          <div class="ep-row">
            <label>Urgency</label>
            <span class="badge ${urgClass}"><span class="badge-dot"></span>${escHtml(data.urgency_level)}</span>
          </div>
          <div class="ep-row">
            <label>Required By</label>
            <strong>${reqBy}</strong>
          </div>
          <div class="ep-hint ${hintClass}">
            <i class="fa-solid fa-${hintClass ? 'circle-question' : 'circle-check'}" style="margin-right:6px;"></i>
            ${escHtml(data.status_hint)}
          </div>
        </div>
        <div class="emergency-popup-footer">
          <a href="/bloodbank/emergency/${data.request_id}" class="btn btn-primary btn-sm">
            <i class="fa-solid fa-eye"></i> View Request
          </a>
          <button class="btn btn-ghost btn-sm" id="ep-dismiss">Dismiss</button>
        </div>
      </div>`;

    document.body.appendChild(overlay);
    window._activeEmergencyPopup = overlay;

    overlay.querySelector('#ep-dismiss').addEventListener('click', () => {
      overlay.remove();
      window._activeEmergencyPopup = null;
      // Notify server of dismiss
      if (data.notification_id) {
        fetch(`/api/notifications/${data.notification_id}/dismiss`, { method: 'POST' });
      }
    });
  }

  /* ── Toast Notifications ────────────────────────────────── */
  let toastContainer = null;
  function ensureToastContainer() {
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.id = 'toast-container';
      toastContainer.style.cssText = `
        position:fixed; bottom:24px; right:24px; z-index:8000;
        display:flex; flex-direction:column; gap:10px; align-items:flex-end;
      `;
      document.body.appendChild(toastContainer);
    }
    return toastContainer;
  }

  window.showToast = function(type, title, message, duration = 5000) {
    const c = ensureToastContainer();
    const icons = { success:'circle-check', danger:'circle-exclamation', warning:'triangle-exclamation', info:'circle-info' };
    const toast = document.createElement('div');
    toast.className = `alert alert-${type}`;
    toast.style.cssText = 'min-width:300px;max-width:380px;animation:slideDown 0.25s ease;box-shadow:var(--shadow-lg);';
    toast.innerHTML = `
      <i class="fa-solid fa-${icons[type]||'bell'}"></i>
      <div style="flex:1">
        <div style="font-weight:600;font-size:0.85rem;">${escHtml(title)}</div>
        <div style="font-size:0.78rem;margin-top:2px;opacity:0.85;">${escHtml(message)}</div>
      </div>
      <button class="alert-close"><i class="fa-solid fa-xmark"></i></button>`;
    toast.querySelector('.alert-close').addEventListener('click', () => toast.remove());
    c.appendChild(toast);
    if (duration > 0) setTimeout(() => toast.remove(), duration);
  };

  /* ── Badge helpers ──────────────────────────────────────── */
  function updateNotifBadge(delta) {
    const badge = document.getElementById('notif-badge');
    if (!badge) return;
    const cur = parseInt(badge.textContent) || 0;
    const next = cur + delta;
    badge.textContent = next;
    badge.style.display = next > 0 ? 'flex' : 'none';
  }

  function updateEmergencyBanner(delta) {
    const banner = document.getElementById('emergency-banner');
    if (!banner) return;
    banner.style.display = 'flex';
    const countEl = banner.querySelector('.eb-count');
    if (countEl) {
      const cur = parseInt(countEl.textContent) || 0;
      countEl.textContent = cur + delta;
    }
  }

  function bumpSidebarPulse() {
    const indicator = document.getElementById('sidebar-emergency-indicator');
    if (!indicator) return;
    indicator.style.display = 'flex';
  }

  /* ── Utility ────────────────────────────────────────────── */
  function escHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── Auto-dismiss flash alerts ──────────────────────────── */
  document.querySelectorAll('.alert .alert-close').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.alert').remove());
  });
  document.querySelectorAll('.alert[data-auto]').forEach(el => {
    setTimeout(() => el.remove(), 4000);
  });

})();
