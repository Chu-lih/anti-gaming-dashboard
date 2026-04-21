/**
 * rules.js — Rules Engine 管理頁邏輯
 *   - JSON 失焦驗證 + 紅框
 *   - Save → POST /api/rules/update
 *   - Toggle → POST /api/rules/toggle
 *   - Rescan → POST /api/rescan
 */

function validateJson(text) {
  if (!text.trim()) return { ok: false, err: 'parameter_json 不可為空' };
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
      return { ok: false, err: '必須是 JSON 物件(dict),不可為陣列或 null' };
    }
    return { ok: true, parsed };
  } catch (e) {
    return { ok: false, err: e.message };
  }
}

function setJsonError(ruleId, err) {
  const ta = document.querySelector(`.parameter-editor[data-rule-id="${ruleId}"]`);
  const box = document.querySelector(`[data-error-for="${ruleId}"]`);
  const status = document.querySelector(`[data-status-for="${ruleId}"]`);
  if (err) {
    ta.classList.add('border-red-500/60');
    box.textContent = '⚠ ' + err;
    box.classList.remove('hidden');
    if (status) { status.textContent = 'invalid'; status.classList.add('text-red-400'); }
  } else {
    ta.classList.remove('border-red-500/60');
    box.classList.add('hidden');
    if (status) { status.textContent = 'valid'; status.classList.remove('text-red-400'); status.classList.add('text-emerald-500'); }
  }
}

// ---------- 失焦 / 輸入驗證 ----------
document.querySelectorAll('.parameter-editor').forEach(ta => {
  const ruleId = ta.dataset.ruleId;
  const validate = () => {
    const result = validateJson(ta.value);
    setJsonError(ruleId, result.ok ? null : result.err);
  };
  ta.addEventListener('blur', validate);
  // initial pass
  validate();
});

// ---------- Save ----------
document.querySelectorAll('.save-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const ruleId = Number(btn.dataset.ruleId);
    const ta = document.querySelector(`.parameter-editor[data-rule-id="${ruleId}"]`);
    const result = validateJson(ta.value);
    if (!result.ok) {
      setJsonError(ruleId, result.err);
      showToast(`JSON invalid for rule #${ruleId}: ${result.err}`, 'error');
      return;
    }
    btn.disabled = true;
    btn.classList.add('opacity-50');
    try {
      const r = await fetch('/api/rules/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_id: ruleId, parameter_json: result.parsed }),
      });
      const body = await r.json();
      if (r.ok) {
        if (body.unchanged) {
          showToast(`No change for ${body.rule_code}`, 'info');
        } else {
          showToast(`Saved ${body.rule_code} · rescan to re-evaluate sessions`, 'success');
        }
      } else {
        showToast(body.error || 'Save failed', 'error');
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.classList.remove('opacity-50');
    }
  });
});

// ---------- Toggle ----------
document.querySelectorAll('.rule-toggle').forEach(btn => {
  btn.addEventListener('click', async () => {
    const ruleId = Number(btn.dataset.ruleId);
    btn.disabled = true;
    try {
      const r = await fetch('/api/rules/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_id: ruleId }),
      });
      const body = await r.json();
      if (r.ok) {
        const on = body.is_active === 1;
        btn.dataset.active = on ? '1' : '0';
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        const knob = btn.querySelector('span');
        if (on) {
          btn.classList.remove('bg-slate-800', 'border-slate-700');
          btn.classList.add('bg-emerald-500/30', 'border-emerald-500/60');
          knob.classList.remove('translate-x-1');
          knob.classList.add('translate-x-6');
        } else {
          btn.classList.add('bg-slate-800', 'border-slate-700');
          btn.classList.remove('bg-emerald-500/30', 'border-emerald-500/60');
          knob.classList.add('translate-x-1');
          knob.classList.remove('translate-x-6');
        }
        const label = document.querySelector(`[data-label-for="${ruleId}"]`);
        if (label) label.textContent = on ? 'ON' : 'OFF';
        const card = btn.closest('.rule-card');
        if (card) card.classList.toggle('opacity-70', !on);
        showToast(`${body.rule_code} → ${on ? 'ENABLED' : 'DISABLED'}`, 'success');
      } else {
        showToast(body.error || 'Toggle failed', 'error');
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
    }
  });
});

// ---------- Rescan ----------
document.getElementById('btn-rescan').addEventListener('click', async () => {
  const btn = document.getElementById('btn-rescan');
  btn.disabled = true;
  btn.classList.add('opacity-60', 'cursor-wait');
  const old = btn.innerHTML;
  btn.innerHTML = `<span class="text-xs">Scanning…</span>`;
  try {
    const r = await fetch('/api/rescan', { method: 'POST' });
    const body = await r.json();
    if (r.ok) {
      showToast(`Rescan complete · ${body.hits_total} total rule hits evaluated`, 'success');
    } else {
      showToast(body.error || 'Rescan failed', 'error');
    }
  } catch (err) {
    showToast(`Network error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-60', 'cursor-wait');
    btn.innerHTML = old;
  }
});
