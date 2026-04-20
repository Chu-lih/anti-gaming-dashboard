/**
 * timeline.js — SVG 視覺化 + Resolution 動作處理
 *
 * SVG 設計:
 *   *  上方實線:agent 實際 session 的事件軌跡
 *   *  下方虛線:該模組的平均完成時長參考,兩條共用同一 x scale
 *   *  事件點按 event 類型不同形狀 / 顏色,tab_switch 有脈衝動畫
 */

(() => {
  // ---------- 讀取 server 注入的資料 ----------
  const dataEl = document.getElementById('timeline-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);

  // ---------- SVG 尺寸常數(對齊 viewBox 0 0 1000 240)----------
  const VB_W = 1000;
  const VB_H = 240;
  const M    = { left: 60, right: 40, top: 40, bottom: 60 };
  const PLOT_W = VB_W - M.left - M.right;
  const Y_ACTUAL = 85;
  const Y_AVG    = 165;

  const svg = document.getElementById('timeline-svg');
  const ns  = 'http://www.w3.org/2000/svg';
  const tooltip = document.getElementById('timeline-tooltip');
  const container = document.getElementById('timeline-container');

  // ---------- 時間 scale ----------
  const actual = data.completion_seconds || 0;
  const avg    = data.module_avg_seconds || 0;
  const tMax   = Math.max(actual, avg, 60);                 // 至少 60s,避免 x 被壓扁
  const xPad   = tMax * 0.05;
  const xScale = t => M.left + (t / (tMax + xPad)) * PLOT_W;

  // ---------- 工具 ----------
  function mk(tag, attrs = {}, parent = svg) {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }
  function fmtTime(s) {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60), r = s % 60;
    return `${m}m ${r}s`;
  }

  // ============================================================
  // 畫軸線 + 刻度
  // ============================================================
  // 背景分組線
  for (let i = 0; i <= 5; i++) {
    const x = M.left + (i / 5) * PLOT_W;
    mk('line', {
      x1: x, y1: M.top, x2: x, y2: VB_H - M.bottom,
      stroke: 'rgb(var(--color-slate-800))', 'stroke-width': 1,
    });
  }

  // 上方實線(actual)
  mk('line', {
    x1: xScale(0), y1: Y_ACTUAL, x2: xScale(actual), y2: Y_ACTUAL,
    stroke: '#ef4444', 'stroke-width': 2,
  });

  // 下方虛線(avg)
  mk('line', {
    x1: xScale(0), y1: Y_AVG, x2: xScale(avg), y2: Y_AVG,
    stroke: '#64748b', 'stroke-width': 1.5, 'stroke-dasharray': '6 4',
  });

  // 標籤(左端)
  const labActual = mk('text', {
    x: M.left - 8, y: Y_ACTUAL + 4, 'text-anchor': 'end',
    fill: '#fca5a5', 'font-size': 11, 'font-family': 'ui-monospace, Menlo, monospace',
  });
  labActual.textContent = 'ACTUAL';
  const labAvg = mk('text', {
    x: M.left - 8, y: Y_AVG + 4, 'text-anchor': 'end',
    fill: '#94a3b8', 'font-size': 11, 'font-family': 'ui-monospace, Menlo, monospace',
  });
  labAvg.textContent = 'AVG';

  // 右端數值標籤
  const actualEndLabel = mk('text', {
    x: xScale(actual) + 6, y: Y_ACTUAL + 4,
    fill: '#fca5a5', 'font-size': 11, 'font-family': 'ui-monospace, Menlo, monospace',
  });
  actualEndLabel.textContent = fmtTime(actual);

  const avgEndLabel = mk('text', {
    x: xScale(avg) + 6, y: Y_AVG + 4,
    fill: '#94a3b8', 'font-size': 11, 'font-family': 'ui-monospace, Menlo, monospace',
  });
  avgEndLabel.textContent = fmtTime(avg);

  // X 軸刻度
  const numTicks = 6;
  for (let i = 0; i <= numTicks; i++) {
    const t = Math.round((tMax / numTicks) * i);
    const x = xScale(t);
    mk('line', {
      x1: x, y1: VB_H - M.bottom, x2: x, y2: VB_H - M.bottom + 5,
      stroke: 'rgb(var(--color-slate-600))', 'stroke-width': 1,
    });
    const lab = mk('text', {
      x: x, y: VB_H - M.bottom + 18, 'text-anchor': 'middle',
      fill: 'rgb(var(--color-slate-500))', 'font-size': 10,
      'font-family': 'ui-monospace, Menlo, monospace',
    });
    lab.textContent = fmtTime(t);
  }

  // X 軸標題
  const axisTitle = mk('text', {
    x: M.left + PLOT_W / 2, y: VB_H - M.bottom + 38, 'text-anchor': 'middle',
    fill: 'rgb(var(--color-slate-500))', 'font-size': 10,
    'font-family': 'ui-monospace, Menlo, monospace',
    'letter-spacing': '0.1em',
  });
  axisTitle.textContent = 'ELAPSED TIME (seconds)';

  // ============================================================
  // 畫事件點
  // ============================================================
  function showTooltip(evt, html) {
    tooltip.innerHTML = html;
    tooltip.classList.remove('hidden');
    const rect = container.getBoundingClientRect();
    tooltip.style.left = (evt.clientX - rect.left + 10) + 'px';
    tooltip.style.top  = (evt.clientY - rect.top  - 32) + 'px';
  }
  function hideTooltip() { tooltip.classList.add('hidden'); }

  function attachHover(el, html) {
    el.addEventListener('mouseenter', e => showTooltip(e, html));
    el.addEventListener('mousemove',  e => showTooltip(e, html));
    el.addEventListener('mouseleave', hideTooltip);
    el.style.cursor = 'help';
  }

  function tooltipHtml(ev) {
    const parts = [
      `<div class="font-mono text-sky-300 text-[10px] uppercase tracking-wider">t = ${ev.time}s · ${ev.event}</div>`,
    ];
    if (ev.detail) parts.push(`<div class="text-slate-200 mt-0.5">${ev.detail}</div>`);
    return parts.join('');
  }

  // 為了避免重疊,同一時刻的事件做細微 x offset
  const timeBuckets = {};
  (data.telemetry || []).forEach(ev => {
    const k = ev.time;
    timeBuckets[k] = (timeBuckets[k] || 0) + 1;
  });
  const timeSeen = {};

  (data.telemetry || []).forEach(ev => {
    timeSeen[ev.time] = (timeSeen[ev.time] || 0) + 1;
    const rank = timeSeen[ev.time] - 1;
    const cnt  = timeBuckets[ev.time];
    const xBase = xScale(ev.time);
    // 同時刻事件橫向偏移 ± ~6px
    const x = xBase + (cnt > 1 ? (rank - (cnt - 1) / 2) * 8 : 0);
    const y = Y_ACTUAL;

    let marker;
    switch (ev.event) {
      case 'session_start':
      case 'session_end':
        marker = mk('circle', { cx: x, cy: y, r: 5, fill: '#94a3b8', stroke: '#0f172a', 'stroke-width': 1.5 });
        break;

      case 'card_swiped':
      case 'all_cards_swiped':
      case 'card_viewed':
        marker = mk('rect', { x: x - 4, y: y - 4, width: 8, height: 8, fill: '#38bdf8', stroke: '#0f172a', 'stroke-width': 1.2 });
        break;

      case 'tab_switch':
        marker = mk('polygon', {
          points: `${x},${y - 7} ${x + 6},${y + 5} ${x - 6},${y + 5}`,
          fill: '#ef4444', stroke: '#0f172a', 'stroke-width': 1.2,
          class: 'tab-switch-marker',
        });
        break;

      case 'tab_return':
        marker = mk('polygon', {
          points: `${x},${y + 7} ${x + 5},${y - 4} ${x - 5},${y - 4}`,
          fill: '#fca5a5', opacity: 0.8, stroke: '#0f172a', 'stroke-width': 1,
        });
        break;

      case 'quiz_started':
        marker = mk('circle', { cx: x, cy: y, r: 4, fill: 'none', stroke: '#a78bfa', 'stroke-width': 2 });
        break;

      case 'quiz_submitted': {
        // 5 角星用 polygon
        const r1 = 8, r2 = 4;
        const pts = [];
        for (let i = 0; i < 10; i++) {
          const ang = -Math.PI / 2 + i * Math.PI / 5;
          const rr = i % 2 === 0 ? r1 : r2;
          pts.push(`${x + rr * Math.cos(ang)},${y + rr * Math.sin(ang)}`);
        }
        marker = mk('polygon', { points: pts.join(' '), fill: '#c084fc', stroke: '#0f172a', 'stroke-width': 1 });
        break;
      }

      default:
        marker = mk('circle', { cx: x, cy: y, r: 3, fill: '#64748b' });
    }

    attachHover(marker, tooltipHtml(ev));
  });

  // ============================================================
  // Resolution action bar
  // ============================================================
  const panel = document.getElementById('resolve-panel');
  if (panel) {
    const notesEl = document.getElementById('resolve-notes');
    const buttons = panel.querySelectorAll('.resolve-btn');

    buttons.forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        const notes = notesEl.value.trim();
        if (!notes) {
          showToast('Manager justification notes is required', 'warn');
          notesEl.focus();
          notesEl.classList.add('border-red-500/60');
          setTimeout(() => notesEl.classList.remove('border-red-500/60'), 1800);
          return;
        }

        buttons.forEach(b => { b.disabled = true; b.classList.add('opacity-50', 'cursor-wait'); });
        try {
          const r = await fetch('/api/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flag_id: data.flag_id, action, notes }),
          });
          const body = await r.json();
          if (r.ok) {
            showToast(`Resolution recorded · flag marked as ${body.new_status}`, 'success', 2200);
            setTimeout(() => { window.location = '/inbox'; }, 1800);
          } else {
            showToast(body.error || 'Resolve failed', 'error');
            buttons.forEach(b => { b.disabled = false; b.classList.remove('opacity-50', 'cursor-wait'); });
          }
        } catch (err) {
          showToast(`Network error: ${err.message}`, 'error');
          buttons.forEach(b => { b.disabled = false; b.classList.remove('opacity-50', 'cursor-wait'); });
        }
      });
    });
  }
})();
