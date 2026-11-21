/*
  notifications.js
  Polls /api/notifications/unread every 30s and updates badges + shows toasts.
  Included after socket-client.js in base.html.
*/
(function () {
  let _knownIds = new Set();
  let _initialised = false;

  async function pollNotifications() {
    try {
      const r = await fetch('/api/notifications/unread', { credentials: 'same-origin' });
      if (!r.ok) return;
      const data = await r.json();

      // Update topbar badge
      const badge = document.getElementById('notif-badge');
      if (badge) {
        const count = data.length;
        badge.textContent = count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }

      // Update sidebar emergency indicator
      const emergencyIds = data.filter(n => n.type === 'Emergency');
      const indicator = document.getElementById('sidebar-emergency-indicator');
      if (indicator) {
        indicator.style.display = emergencyIds.length > 0 ? 'flex' : 'none';
        const countEl = indicator.querySelector('.si-count');
        if (countEl) countEl.textContent = emergencyIds.length;
      }

      // Update emergency banner count
      const banner = document.getElementById('emergency-banner');
      if (banner && emergencyIds.length > 0) {
        banner.style.display = 'flex';
        const countEl = banner.querySelector('.eb-count');
        if (countEl) countEl.textContent = emergencyIds.length;
      }

      // Show toasts only for NEW notifications (not on first load)
      if (_initialised) {
        data.forEach(n => {
          if (!_knownIds.has(n.id)) {
            const toastType = n.type === 'Emergency' ? 'danger'
                            : n.type === 'Low Stock' ? 'warning'
                            : n.type === 'Expiry'    ? 'warning'
                            : 'info';
            if (typeof window.showToast === 'function') {
              window.showToast(toastType, n.title, n.message.substring(0, 120));
            }
          }
        });
      }

      // Refresh known IDs
      _knownIds = new Set(data.map(n => n.id));
      _initialised = true;

    } catch (e) {
      // Silent fail — polling is best-effort
    }
  }

  // Run immediately on page load, then every 30 seconds
  document.addEventListener('DOMContentLoaded', () => {
    pollNotifications();
    setInterval(pollNotifications, 30000);
  });
})();
