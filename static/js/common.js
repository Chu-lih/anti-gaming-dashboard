/**
 * common.js —— 全站共用工具
 *   - Toast 通知
 *   - Manager 切換
 *   - 狀態 bar 更新
 */

// ---------- Toast ----------
function showToast(message, variant = 'info', ttl = 3600) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const palette = {
    info:    'bg-sky-500/15    border-sky-500/50    text-sky-200',
    success: 'bg-emerald-500/15 border-emerald-500/50 text-emerald-200',
    warn:    'bg-amber-500/15   border-amber-500/50  text-amber-200',
    error:   'bg-red-500/15     border-red-500/60    text-red-200',
  }[variant] || '';

  const el = document.createElement('div');
  el.className = `toast border rounded-md px-4 py-2.5 text-sm shadow-lg backdrop-blur ${palette}`;
  el.innerHTML = `<div class="flex items-center gap-2"><span class="text-xs uppercase tracking-wider opacity-70">[${variant}]</span><span>${message}</span></div>`;
  container.appendChild(el);

  setTimeout(() => {
    el.style.transition = 'opacity 240ms';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 260);
  }, ttl);
}

// ---------- Manager 切換 ----------
document.addEventListener('DOMContentLoaded', () => {
  const sel = document.getElementById('manager-switch');
  if (sel) {
    sel.addEventListener('change', async (e) => {
      const mid = e.target.value;
      try {
        const r = await fetch('/api/switch-manager', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ manager_id: mid }),
        });
        const data = await r.json();
        if (r.ok) {
          document.getElementById('sidebar-manager-name').textContent = data.manager_name;
          document.getElementById('sidebar-manager-id').textContent = data.manager_id;
          showToast(`Switched to ${data.manager_name}`, 'success');
        } else {
          showToast(data.error || 'Switch failed', 'error');
        }
      } catch (err) {
        showToast(`Network error: ${err.message}`, 'error');
      }
    });
  }
});

// ---------- 更新頂部 status bar ----------
async function refreshStatusBar() {
  try {
    const r = await fetch('/api/inbox-data?status=pending');
    if (!r.ok) return;
    const data = await r.json();
    const pend = document.getElementById('status-pending');
    if (pend) pend.textContent = data.stats.total_pending ?? 0;
    const scan = document.getElementById('status-last-scan');
    if (scan) scan.textContent = new Date().toLocaleTimeString('zh-TW', { hour12: false });
  } catch (err) {
    // 靜默失敗,status bar 非核心
  }
}

document.addEventListener('DOMContentLoaded', refreshStatusBar);
