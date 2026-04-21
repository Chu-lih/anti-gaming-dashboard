/**
 * timeline.js — SVG 視覺化 + Resolution 動作處理
 *
 * 雙軸 SVG 設計:
 *   (上段 Comparative View)
 *     - ACTUAL 紅色實線:agent 實際完成時長(例 12s)
 *     - AVG 灰色虛線:模組平均完成時長(例 420s)
 *     - 共用 x scale → 長短對比一眼看到
 *     - 不放事件點(避免被壓縮)
 *
 *   (下段 Zoomed Event Timeline)
 *     - x scale 獨立:0 → actual 完整展開
 *     - 事件點按 event type 分層到主線上下(避免重疊)
 *     - 刻度依時長動態:12s→每 2s,420s→每 60s
 *     - 底部軸標題
 */

(() => {
  const dataEl = document.getElementById('timeline-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);

  // ================================================================
  // 座標系常數
  // ================================================================
  const VB_W = 1000, VB_H = 400;
  const M = { left: 70, right: 50 };
  const PLOT_W = VB_W - M.left - M.right;

  // Comparative section (top)
  const COMP_Y_ACTUAL = 55;
  const COMP_Y_AVG    = 95;
  const COMP_BOTTOM   = 135;

  // Divider / section label
  const DIVIDER_Y     = 150;
  const SECTION_LABEL_Y = 170;

  // Zoomed section (bottom)
  const ZOOM_MAIN_Y   = 270;   // 主事件線 y 位置
  const ZOOM_AXIS_Y   = 325;   // 刻度線位置
  const ZOOM_AXIS_LABEL_Y = 375;

  const actual = data.completion_seconds || 0;
  const avg    = data.module_avg_seconds || 0;

  // Comparative scale — 以兩者較大值為軸
  const tMaxComp = Math.max(actual, avg, 60);
  const xComp = t => M.left + (t / (tMaxComp * 1.05)) * PLOT_W;

  // Zoomed scale — 只覆蓋 actual 範圍
  const tMaxZoom = Math.max(actual, 10);
  const xZoom = t => M.left + (t / (tMaxZoom * 1.04)) * PLOT_W;

  const svg       = document.getElementById('timeline-svg');
  const tooltip   = document.getElementById('timeline-tooltip');
  const container = document.getElementById('timeline-container');
  const ns        = 'http://www.w3.org/2000/svg';

  // ================================================================
  // Helpers
  // ================================================================
  function mk(tag, attrs = {}, parent = svg) {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }
  function mkText(x, y, content, fill, anchor = 'start', size = 11, weight = 'normal') {
    const t = mk('text', {
      x, y, fill, 'text-anchor': anchor,
      'font-size': size, 'font-weight': weight,
      'font-family': 'ui-monospace, Menlo, Consolas, monospace',
    });
    t.textContent = content;
    return t;
  }
  function fmtTime(s) {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60), r = s % 60;
    return r === 0 ? `${m}m` : `${m}m${r}s`;
  }
  function pickTickStep(tMax) {
    if (tMax <= 15)  return 2;
    if (tMax <= 30)  return 5;
    if (tMax <= 60)  return 10;
    if (tMax <= 180) return 30;
    if (tMax <= 600) return 60;
    if (tMax <= 1800) return 300;
    return 600;
  }

  // ================================================================
  //  (1) Comparative View
  // ================================================================
  // Background rail
  mk('rect', {
    x: M.left, y: COMP_Y_ACTUAL - 14, width: PLOT_W, height: COMP_BOTTOM - COMP_Y_ACTUAL,
    fill: 'rgb(var(--color-slate-900) / 0.35)', rx: 4,
  });

  // ACTUAL line
  mk('line', {
    x1: xComp(0), y1: COMP_Y_ACTUAL, x2: xComp(actual), y2: COMP_Y_ACTUAL,
    stroke: '#ef4444', 'stroke-width': 3, 'stroke-linecap': 'round',
  });
  mk('circle', { cx: xComp(0),       cy: COMP_Y_ACTUAL, r: 4, fill: '#ef4444' });
  mk('circle', { cx: xComp(actual),  cy: COMP_Y_ACTUAL, r: 5, fill: '#ef4444', stroke: '#0f172a', 'stroke-width': 1.5 });

  // AVG line
  mk('line', {
    x1: xComp(0), y1: COMP_Y_AVG, x2: xComp(avg), y2: COMP_Y_AVG,
    stroke: '#94a3b8', 'stroke-width': 2, 'stroke-dasharray': '7 4',
  });
  mk('circle', { cx: xComp(0),    cy: COMP_Y_AVG, r: 3.5, fill: '#94a3b8' });
  mk('circle', { cx: xComp(avg),  cy: COMP_Y_AVG, r: 4,   fill: '#94a3b8' });

  // Labels (left)
  mkText(M.left - 10, COMP_Y_ACTUAL + 4, 'ACTUAL', '#fca5a5', 'end', 10, 'bold');
  mkText(M.left - 10, COMP_Y_AVG + 4,    'AVG',    '#94a3b8', 'end', 10, 'bold');

  // End labels (right of each line)
  mkText(xComp(actual) + 10, COMP_Y_ACTUAL + 4, fmtTime(actual), '#fca5a5', 'start', 12, 'bold');
  mkText(xComp(avg) + 10,    COMP_Y_AVG + 4,    fmtTime(avg),    '#cbd5e1', 'start', 11);

  // Ratio annotation
  if (avg > 0) {
    const pct = Math.floor((actual / avg) * 100);
    const warn = pct < 30;
    mkText(
      M.left + PLOT_W / 2, COMP_BOTTOM - 2,
      `${pct}% of expected duration`,
      warn ? '#fca5a5' : 'rgb(var(--color-slate-400))',
      'middle', 11, warn ? 'bold' : 'normal'
    );
  }

  // ================================================================
  //  Divider + Section label
  // ================================================================
  mk('line', {
    x1: M.left, y1: DIVIDER_Y, x2: M.left + PLOT_W, y2: DIVIDER_Y,
    stroke: 'rgb(var(--color-slate-800))', 'stroke-width': 1,
  });
  mkText(
    M.left, SECTION_LABEL_Y,
    `SESSION DETAIL — zoomed to 0s → ${fmtTime(actual)}`,
    'rgb(var(--color-slate-400))', 'start', 10, 'bold'
  );

  // ================================================================
  //  (2) Zoomed Event Timeline
  // ================================================================
  // Grid lines
  const tickStep = pickTickStep(tMaxZoom);
  for (let t = 0; t <= tMaxZoom + 0.001; t += tickStep) {
    const x = xZoom(t);
    mk('line', {
      x1: x, y1: 195, x2: x, y2: ZOOM_AXIS_Y,
      stroke: 'rgb(var(--color-slate-800) / 0.6)', 'stroke-width': 1,
    });
  }

  // Main timeline
  mk('line', {
    x1: xZoom(0), y1: ZOOM_MAIN_Y, x2: xZoom(actual), y2: ZOOM_MAIN_Y,
    stroke: 'rgb(var(--color-slate-600))', 'stroke-width': 2.5, 'stroke-linecap': 'round',
  });

  // X-axis ticks + labels
  for (let t = 0; t <= tMaxZoom + 0.001; t += tickStep) {
    const x = xZoom(t);
    mk('line', {
      x1: x, y1: ZOOM_AXIS_Y, x2: x, y2: ZOOM_AXIS_Y + 5,
      stroke: 'rgb(var(--color-slate-500))', 'stroke-width': 1,
    });
    mkText(x, ZOOM_AXIS_Y + 18, fmtTime(Math.round(t)), 'rgb(var(--color-slate-500))', 'middle', 10);
  }
  mkText(
    M.left + PLOT_W / 2, ZOOM_AXIS_LABEL_Y,
    'ELAPSED TIME',
    'rgb(var(--color-slate-600))', 'middle', 9, 'bold'
  );

  // ================================================================
  //  事件分層:不同 event type 對應到主線的不同 y-offset,避免重疊
  // ================================================================
  const Y_LAYER = {
    quiz_started:    -70,
    quiz_submitted:  -70,
    card_swiped:     -42,
    all_cards_swiped: -42,
    card_viewed:     -42,
    session_start:   -15,
    session_end:     -15,
    tab_switch:      +22,
    tab_return:      +48,
  };

  // 同 (time, event) 的事件做水平 offset,避免完全疊住
  const pairCount = {};
  const pairSeen  = {};
  (data.telemetry || []).forEach(ev => {
    const k = `${ev.time}|${ev.event}`;
    pairCount[k] = (pairCount[k] || 0) + 1;
  });

  function tooltipHtml(ev) {
    const parts = [
      `<div class="font-mono text-sky-300 text-[10px] uppercase tracking-wider">t = ${ev.time}s · ${ev.event}</div>`,
    ];
    if (ev.detail) parts.push(`<div class="text-slate-100 mt-0.5">${ev.detail}</div>`);
    return parts.join('');
  }
  function showTooltip(evt, html) {
    tooltip.innerHTML = html;
    tooltip.classList.remove('hidden');
    const rect = container.getBoundingClientRect();
    let left = evt.clientX - rect.left + 12;
    let top  = evt.clientY - rect.top  - 38;
    // 避免溢出右側
    if (left + tooltip.offsetWidth > rect.width) left = rect.width - tooltip.offsetWidth - 8;
    if (top < 0) top = evt.clientY - rect.top + 16;
    tooltip.style.left = left + 'px';
    tooltip.style.top  = top  + 'px';
  }
  function hideTooltip() { tooltip.classList.add('hidden'); }
  function attachHover(el, html) {
    el.addEventListener('mouseenter', e => showTooltip(e, html));
    el.addEventListener('mousemove',  e => showTooltip(e, html));
    el.addEventListener('mouseleave', hideTooltip);
    el.style.cursor = 'help';
  }

  (data.telemetry || []).forEach(ev => {
    const k = `${ev.time}|${ev.event}`;
    pairSeen[k] = (pairSeen[k] || 0) + 1;
    const rank = pairSeen[k] - 1;
    const cnt  = pairCount[k];
    const xBase = xZoom(ev.time);
    // 同一 (time,event) 的重複事件橫向展開
    const xOff = cnt > 1 ? (rank - (cnt - 1) / 2) * 10 : 0;
    const x = xBase + xOff;

    const yOffset = Y_LAYER[ev.event] ?? 0;
    const y = ZOOM_MAIN_Y + yOffset;

    // 細連接線(只在 |offset| > 12 時畫,避免太短看不到)
    if (Math.abs(yOffset) > 12) {
      mk('line', {
        x1: xBase, y1: ZOOM_MAIN_Y, x2: x, y2: y,
        stroke: 'rgb(var(--color-slate-700))', 'stroke-width': 0.8, opacity: 0.7,
      });
    }

    let marker;
    switch (ev.event) {
      case 'session_start':
      case 'session_end':
        marker = mk('circle', {
          cx: x, cy: y, r: 5,
          fill: 'rgb(var(--color-slate-400))',
          stroke: 'rgb(var(--color-slate-950))', 'stroke-width': 1.5,
        });
        break;

      case 'card_swiped':
      case 'all_cards_swiped':
      case 'card_viewed':
        marker = mk('rect', {
          x: x - 5, y: y - 5, width: 10, height: 10,
          fill: '#38bdf8',
          stroke: 'rgb(var(--color-slate-950))', 'stroke-width': 1.2,
          rx: 1,
        });
        break;

      case 'tab_switch':
        marker = mk('polygon', {
          points: `${x},${y - 8} ${x + 7},${y + 6} ${x - 7},${y + 6}`,
          fill: '#ef4444',
          stroke: 'rgb(var(--color-slate-950))', 'stroke-width': 1.2,
          class: 'tab-switch-marker',
        });
        break;

      case 'tab_return':
        marker = mk('polygon', {
          points: `${x},${y + 8} ${x + 6},${y - 5} ${x - 6},${y - 5}`,
          fill: '#fca5a5', opacity: 0.85,
          stroke: 'rgb(var(--color-slate-950))', 'stroke-width': 1,
        });
        break;

      case 'quiz_started':
        marker = mk('circle', {
          cx: x, cy: y, r: 5,
          fill: 'none', stroke: '#a78bfa', 'stroke-width': 2,
        });
        break;

      case 'quiz_submitted': {
        const r1 = 9, r2 = 4.2;
        const pts = [];
        for (let i = 0; i < 10; i++) {
          const ang = -Math.PI / 2 + i * Math.PI / 5;
          const rr = i % 2 === 0 ? r1 : r2;
          pts.push(`${x + rr * Math.cos(ang)},${y + rr * Math.sin(ang)}`);
        }
        marker = mk('polygon', {
          points: pts.join(' '),
          fill: '#c084fc',
          stroke: 'rgb(var(--color-slate-950))', 'stroke-width': 1,
        });
        break;
      }

      default:
        marker = mk('circle', { cx: x, cy: y, r: 3, fill: 'rgb(var(--color-slate-500))' });
    }

    attachHover(marker, tooltipHtml(ev));
  });

  // ================================================================
  //  Resolution Action Bar(pending 才有 panel)
  // ================================================================
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
