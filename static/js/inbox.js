/**
 * inbox.js — Risk Inbox 局部更新邏輯
 *   - 篩選器 change → 不 reload,fetch /api/inbox-data → 重 render
 *   - Rescan 按鈕 → POST /api/rescan → toast + refresh
 */

const SEV_BADGE = {
  High:   'bg-red-500/15 text-red-300 border-red-500/40',
  Medium: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  Low:    'bg-yellow-500/10 text-yellow-300 border-yellow-500/30',
};

const STATUS_COLOR = {
  pending:   'text-amber-300',
  approved:  'text-emerald-400',
  voided:    'text-slate-400',
  escalated: 'text-rose-400',
};

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function buildRow(f, idx) {
  const sevCls = SEV_BADGE[f.severity_level] || '';
  const stCls  = STATUS_COLOR[f.resolution_status] || 'text-slate-400';
  const tlUrl  = `/timeline/${f.flag_id}`;
  const zebra  = idx % 2 === 0 ? 'bg-slate-900/20' : '';
  return `
    <tr class="flag-row ${zebra}" data-flag-id="${f.flag_id}" onclick="window.location='${tlUrl}'">
      <td class="px-4 py-3">
        <span class="inline-block text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded border ${sevCls}">${escapeHtml(f.severity_level)}</span>
      </td>
      <td class="px-4 py-3 font-mono text-xs text-slate-400">#${f.flag_id}</td>
      <td class="px-4 py-3">
        <div class="text-slate-200">${escapeHtml(f.agent_name)}</div>
        <div class="font-mono text-[10px] text-slate-500">${escapeHtml(f.agent_id)}</div>
      </td>
      <td class="px-4 py-3 text-slate-300 text-xs">${escapeHtml(f.module_name)}</td>
      <td class="px-4 py-3">
        <div class="font-mono text-[11px] text-slate-400">${escapeHtml(f.rule_code)}</div>
        <div class="text-[11px] text-slate-500">${escapeHtml(f.rule_name)}</div>
      </td>
      <td class="px-4 py-3 font-mono text-[11px] text-slate-500 num">${escapeHtml(f.flag_timestamp)}</td>
      <td class="px-4 py-3 text-[11px] uppercase tracking-wider font-semibold ${stCls}">${escapeHtml(f.resolution_status)}</td>
      <td class="px-4 py-3 text-right">
        <a href="${tlUrl}" onclick="event.stopPropagation()"
           class="inline-flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300">
          View Timeline
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/></svg>
        </a>
      </td>
    </tr>`;
}

function emptyRow() {
  return `
    <tr>
      <td colspan="8" class="px-4 py-16 text-center text-slate-500 text-sm">
        <div class="text-4xl mb-3">∅</div>
        No flagged sessions match your filters.
      </td>
    </tr>`;
}

function readFilters() {
  return {
    severity: document.getElementById('filter-severity').value,
    rule:     document.getElementById('filter-rule').value,
    status:   document.getElementById('filter-status').value,
    agent:    document.getElementById('filter-agent').value.trim(),
  };
}

function updateKpis(stats) {
  const map = { high: 'high_pending', medium: 'medium_pending', low: 'low_pending', total: 'total_pending' };
  for (const [key, field] of Object.entries(map)) {
    const el = document.querySelector(`[data-kpi="${key}"]`);
    if (el) el.textContent = stats[field] ?? 0;
  }
  const statusPending = document.getElementById('status-pending');
  if (statusPending) statusPending.textContent = stats.total_pending ?? 0;
}

async function loadInbox() {
  const { severity, rule, status, agent } = readFilters();
  const qs = new URLSearchParams({ severity, rule, status, agent });
  try {
    const r = await fetch(`/api/inbox-data?${qs}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const tbody = document.getElementById('flags-tbody');
    tbody.innerHTML = data.flags.length
      ? data.flags.map((f, i) => buildRow(f, i)).join('')
      : emptyRow();
    updateKpis(data.stats);
    const scan = document.getElementById('status-last-scan');
    if (scan) scan.textContent = new Date().toLocaleTimeString('zh-TW', { hour12: false });
  } catch (err) {
    showToast(`Failed to load inbox: ${err.message}`, 'error');
  }
}

async function triggerRescan() {
  const btn = document.getElementById('btn-rescan');
  btn.disabled = true;
  btn.classList.add('opacity-60', 'cursor-wait');
  const oldText = btn.innerHTML;
  btn.innerHTML = `<span class="text-xs">Scanning…</span>`;
  try {
    const r = await fetch('/api/rescan', { method: 'POST' });
    const data = await r.json();
    if (r.ok) {
      showToast(`Rescan complete · ${data.hits_total} total rule hits evaluated`, 'success');
      await loadInbox();
    } else {
      showToast(data.error || 'Rescan failed', 'error');
    }
  } catch (err) {
    showToast(`Rescan network error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-60', 'cursor-wait');
    btn.innerHTML = oldText;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  ['filter-severity', 'filter-rule', 'filter-status'].forEach(id => {
    document.getElementById(id).addEventListener('change', loadInbox);
  });

  // Agent 搜尋用 debounce,避免每一鍵就打 API
  let agentDebounce;
  document.getElementById('filter-agent').addEventListener('input', () => {
    clearTimeout(agentDebounce);
    agentDebounce = setTimeout(loadInbox, 250);
  });

  document.getElementById('filter-reset').addEventListener('click', () => {
    document.getElementById('filter-severity').value = '';
    document.getElementById('filter-rule').value = '';
    document.getElementById('filter-status').value = 'pending';
    document.getElementById('filter-agent').value = '';
    loadInbox();
  });
  document.getElementById('btn-rescan').addEventListener('click', triggerRescan);
});
