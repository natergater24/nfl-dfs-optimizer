"""My Lineup builder — a Streamlit components v2 custom component.

Left: the 9 lineup slots. Right: the whole playable pool. Swap by clicking a slot then a player, a player
then a slot, or dragging a player onto a slot. Every change is sent back to Python as the state value
`lineup` = {"ids": [9 dk_ids or null], "t": timestamp}."""
import streamlit as st

HTML = '<div id="lb"></div>'

CSS = """
#lb { --bg2: var(--st-secondary-background-color, #262730); --fg: var(--st-text-color, #fafafa);
      --muted: color-mix(in srgb, var(--fg) 55%, transparent); --line: color-mix(in srgb, var(--fg) 14%, transparent);
      --accent: var(--st-primary-color, #ff4b4b); --ok: #21c354; --bad: #ff6b6b;
      font-family: var(--st-font, "Source Sans Pro", sans-serif); color: var(--fg); font-size: 14px; }
.lb { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 760px) { .lb { grid-template-columns: 1fr; } }
.hdr { display: flex; justify-content: space-between; align-items: baseline; margin: 0 0 8px; gap: 8px; flex-wrap: wrap; }
.hdr b { font-size: 15px; }
.cap { color: var(--muted); font-size: 13px; } .cap.over { color: var(--bad); font-weight: 600; }
.slot { display: grid; grid-template-columns: 48px 1fr auto; align-items: center; gap: 8px; padding: 8px 10px;
        margin-bottom: 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg2);
        cursor: pointer; transition: opacity .12s, border-color .12s; min-height: 44px; }
.slot .pos { font-weight: 700; font-size: 12px; color: var(--muted); }
.slot .nm { font-weight: 600; } .slot .meta { color: var(--muted); font-size: 12px; }
.slot.empty .nm { color: var(--muted); font-style: italic; font-weight: 400; }
.slot.sel, .pr.sel { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.slot.target { border-color: var(--ok); border-style: dashed; }
.slot.dropover { background: color-mix(in srgb, var(--ok) 18%, var(--bg2)); }
.dim { opacity: .28; pointer-events: none; }
.x { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.x:hover { color: var(--bad); }
.hint { color: var(--muted); font-size: 12px; margin-top: 6px; min-height: 16px; }
.bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip { border: 1px solid var(--line); background: transparent; color: var(--fg); border-radius: 999px;
        padding: 3px 11px; font-size: 13px; cursor: pointer; }
.chip.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.ctl { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; align-items: center; }
.ctl input[type=search], .ctl select { background: var(--bg2); color: var(--fg); border: 1px solid var(--line);
        border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.ctl input[type=search] { flex: 1; min-width: 120px; }
.ctl label { color: var(--muted); font-size: 13px; display: flex; gap: 4px; align-items: center; }
.list { max-height: 560px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; }
.pr { display: grid; grid-template-columns: 1fr 70px 92px 70px; gap: 8px; align-items: center; padding: 7px 10px;
      border-bottom: 1px solid var(--line); cursor: grab; border-left: 3px solid transparent; }
.pr:last-child { border-bottom: none; }
.pr:hover { background: var(--bg2); }
.pr .nm { font-weight: 600; } .pr .meta, .pr .sub { color: var(--muted); font-size: 12px; }
.pr .num { text-align: right; font-variant-numeric: tabular-nums; }
.pr.inlu { opacity: .45; cursor: default; }
.pr .left.neg { color: var(--bad); }
.tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--line); margin-left: 4px; }
.colhdr { display: grid; grid-template-columns: 1fr 70px 92px 70px; gap: 8px; padding: 0 10px 4px; color: var(--muted); font-size: 12px; }
.colhdr span:not(:first-child) { text-align: right; }
.mu { color: #fff; font-weight: 600; font-size: 11px; padding: 1px 6px; border-radius: 4px; white-space: nowrap; cursor: help; }
"""

JS = r"""
export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector('#lb');
  if (!root || !data) return;
  const UI = (globalThis.__lbUI ||= { filter: 'ALL', sort: 'score', q: '', afford: true, selSlot: null, selPlayer: null });
  if (data.focus_token != null && data.focus_token !== globalThis.__lbFocusSeen) {   // "Apply" from Outliers
    globalThis.__lbFocusSeen = data.focus_token;
    UI.selSlot = Number.isInteger(data.focus_slot) ? data.focus_slot : null;
    UI.selPlayer = null;
  }
  const SLOTS = data.slots, CAP = data.cap;
  const ELIG = { QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], FLEX: ['RB', 'WR', 'TE'], DST: ['DST'] };
  const pool = data.pool, byId = new Map(pool.map(p => [p.dk_id, p]));
  let lineup = data.lineup.map(v => (v == null ? null : Number(v)));
  const ICON = { Chalk: '🔥 Chalk', Popular: 'Popular', Moderate: 'Moderate', Contrarian: '💎 Contrarian' };
  const money = v => '$' + Math.round(v).toLocaleString();
  const k = v => money(v);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const mu = p => `<span class="mu" style="background:${p.mu_color}" title="${esc(p.mu_text)}">vs ${p.opp} · ${p.mu_label}</span>`;
  const used = () => lineup.reduce((a, id) => a + (id ? byId.get(id).salary : 0), 0);
  const fits = (i, p) => ELIG[SLOTS[i]].includes(p.position);

  function commit() { setStateValue('lineup', { ids: lineup, t: Date.now() }); }
  function place(i, id) {
    const p = byId.get(id);
    if (!p || !fits(i, p)) return;
    const from = lineup.indexOf(id);
    if (from >= 0 && from !== i) {             // moving a lineup player (e.g. RB -> FLEX): swap the two slots
      const other = lineup[i];
      lineup[from] = other != null && fits(from, byId.get(other)) ? other : null;
    }
    lineup[i] = id;
    UI.selSlot = null; UI.selPlayer = null;
    render(); commit();
  }

  function shell() {
    root.innerHTML = `
      <div class="lb">
        <div><div class="hdr"><b>Your lineup</b><span class="cap" id="cap"></span></div>
          <div id="slots"></div><div class="hint" id="hint"></div></div>
        <div><div class="hdr"><b>Player pool</b><span class="cap" id="cnt"></span></div>
          <div class="bar" id="chips"></div>
          <div class="ctl">
            <input type="search" id="q" placeholder="Search player or team">
            <select id="sort">
              <option value="score">Rank: Recommended</option><option value="median">Rank: Expected points</option>
              <option value="ceiling">Rank: Ceiling (upside)</option><option value="price_desc">Rank: Price high → low</option>
              <option value="price_asc">Rank: Price low → high</option><option value="value">Rank: Value (pts / $1K)</option>
              <option value="own">Rank: Ownership low → high</option>
            </select>
            <label><input type="checkbox" id="afford"> Only what I can afford</label>
          </div>
          <div class="colhdr"><span>Player</span><span>Salary</span><span>Median / Ceil</span><span>Own</span></div>
          <div class="list" id="list"></div></div>
      </div>`;
    root.querySelector('#chips').innerHTML = ['ALL', 'QB', 'RB', 'WR', 'TE', 'FLEX', 'DST']
      .map(f => `<button class="chip" data-f="${f}">${f === 'ALL' ? 'All' : f}</button>`).join('');
    const q = root.querySelector('#q'); q.value = UI.q;
    q.oninput = () => { UI.q = q.value; renderList(); };
    const sort = root.querySelector('#sort'); sort.value = UI.sort;
    sort.onchange = () => { UI.sort = sort.value; renderList(); };
    const af = root.querySelector('#afford'); af.checked = UI.afford;
    af.onchange = () => { UI.afford = af.checked; renderList(); };
  }

  function renderSlots() {
    const u = used(), sp = UI.selPlayer != null ? byId.get(UI.selPlayer) : null;
    const cap = root.querySelector('#cap');
    cap.textContent = `${money(u)} / ${money(CAP)} · ${u <= CAP ? money(CAP - u) + ' left' : money(u - CAP) + ' over'}`;
    cap.className = 'cap' + (u > CAP ? ' over' : '');
    root.querySelector('#slots').innerHTML = SLOTS.map((s, i) => {
      const id = lineup[i], p = id ? byId.get(id) : null;
      const cls = ['slot', p ? '' : 'empty', UI.selSlot === i ? 'sel' : '',
                   sp ? (fits(i, sp) ? 'target' : 'dim') : ''].join(' ');
      const body = p ? `<div><div class="nm">${esc(p.name)}</div><div class="meta">${p.team} ${mu(p)} · ${k(p.salary)} · ${p.median.toFixed(1)} pts · ${ICON[p.tier]}</div></div>`
                     : `<div class="nm">— empty — drop or pick a ${s === 'FLEX' ? 'RB/WR/TE' : s}</div>`;
      return `<div class="${cls}" data-i="${i}"><span class="pos">${s}</span>${body}${p ? `<button class="x" data-rm="${i}" title="Remove">×</button>` : '<span></span>'}</div>`;
    }).join('');
    const hint = root.querySelector('#hint');
    hint.textContent = sp ? `Click a highlighted slot (or drag) to put ${sp.name} in. Gray slots can't take a ${sp.position}.`
      : UI.selSlot != null ? `Pick a player on the right for ${SLOTS[UI.selSlot]} — ineligible players are grayed out.`
      : 'Click a slot or a player to start, or drag a player onto a slot.';
    root.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c.dataset.f === activeFilter()));
  }

  function activeFilter() { return UI.selSlot != null ? (SLOTS[UI.selSlot] === 'FLEX' ? 'FLEX' : SLOTS[UI.selSlot]) : UI.filter; }

  function renderList() {
    const f = activeFilter(), q = UI.q.trim().toLowerCase(), u = used();
    const selSlot = UI.selSlot, curSal = selSlot != null && lineup[selSlot] ? byId.get(lineup[selSlot]).salary : 0;
    let rows = pool.filter(p => (f === 'ALL' || (f === 'FLEX' ? ELIG.FLEX : [f]).includes(p.position))
      && (!q || (p.name + ' ' + p.team).toLowerCase().includes(q)));
    const leftAfter = p => CAP - (u - curSal) - p.salary;
    if (UI.afford && selSlot != null) rows = rows.filter(p => leftAfter(p) >= 0 || lineup.includes(p.dk_id));
    const key = { score: p => -p.score, median: p => -p.median, ceiling: p => -p.ceiling, price_desc: p => -p.salary,
                  price_asc: p => p.salary, value: p => -p.value, own: p => p.own_pct }[UI.sort];
    rows.sort((a, b) => key(a) - key(b));
    root.querySelector('#cnt').textContent = `${rows.length} players`;
    root.querySelector('#list').innerHTML = rows.map(p => {
      const inlu = lineup.includes(p.dk_id);
      const dim = selSlot != null && !fits(selSlot, p);
      const la = leftAfter(p);
      const cls = ['pr', inlu ? 'inlu' : '', dim ? 'dim' : '', UI.selPlayer === p.dk_id ? 'sel' : ''].join(' ');
      const after = selSlot != null && !inlu ? `<div class="sub left ${la < 0 ? 'neg' : ''}">${la < 0 ? money(-la) + ' over' : money(la) + ' left'}</div>` : '';
      return `<div class="${cls}" data-id="${p.dk_id}" draggable="${!inlu}">
        <div><div class="nm">${esc(p.name)}${inlu ? '<span class="tag">in lineup</span>' : ''}</div>
             <div class="meta">${p.position} · ${p.team} ${mu(p)}</div></div>
        <div class="num">${k(p.salary)}${after}</div>
        <div class="num">${p.median.toFixed(1)} / ${p.ceiling.toFixed(1)}<div class="sub">${p.value.toFixed(2)} pts/$1K</div></div>
        <div class="num">${p.own_pct.toFixed(0)}%<div class="sub">${ICON[p.tier]}</div></div></div>`;
    }).join('') || '<div class="pr"><div class="meta">No players match.</div></div>';
  }

  function render() { renderSlots(); renderList(); }

  shell(); render();

  root.onclick = (e) => {
    const rm = e.target.closest('[data-rm]');
    if (rm) { lineup[+rm.dataset.rm] = null; UI.selSlot = null; render(); commit(); return; }
    const chip = e.target.closest('.chip');
    if (chip) { UI.filter = chip.dataset.f; UI.selSlot = null; render(); return; }
    const slot = e.target.closest('.slot');
    if (slot) {
      const i = +slot.dataset.i;
      if (UI.selPlayer != null) { place(i, UI.selPlayer); return; }
      UI.selSlot = UI.selSlot === i ? null : i; UI.selPlayer = null; render(); return;
    }
    const pr = e.target.closest('.pr[data-id]');
    if (pr && !pr.classList.contains('inlu')) {
      const id = +pr.dataset.id;
      if (UI.selSlot != null) { place(UI.selSlot, id); return; }
      UI.selPlayer = UI.selPlayer === id ? null : id; render();
    }
  };
  root.onkeydown = (e) => { if (e.key === 'Escape') { UI.selSlot = null; UI.selPlayer = null; render(); } };
  root.ondragstart = (e) => {
    const pr = e.target.closest('.pr[data-id]'); if (!pr) return;
    e.dataTransfer.setData('text/plain', pr.dataset.id); e.dataTransfer.effectAllowed = 'move';
    UI.selSlot = null; UI.selPlayer = +pr.dataset.id; renderSlots();
  };
  root.ondragend = () => { if (UI.selPlayer != null) { UI.selPlayer = null; renderSlots(); renderList(); } };
  root.ondragover = (e) => {
    const s = e.target.closest('.slot'); root.querySelectorAll('.dropover').forEach(n => n !== s && n.classList.remove('dropover'));
    if (s && UI.selPlayer != null && fits(+s.dataset.i, byId.get(UI.selPlayer))) { e.preventDefault(); s.classList.add('dropover'); }
  };
  root.ondrop = (e) => {
    const s = e.target.closest('.slot'); if (!s) return; e.preventDefault();
    place(+s.dataset.i, +e.dataTransfer.getData('text/plain'));
  };
}
"""

lineup_builder = st.components.v2.component("nfldfs_lineup_builder", html=HTML, css=CSS, js=JS)
