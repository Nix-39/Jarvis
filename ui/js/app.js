// Yggdrasil desktop UI - wires the live core (API + event feed) to the visuals.
import { getToken, api, health, followEvents, openExternal } from './api.js';
import { Tree, WELLS, S as TREE_S } from './tree.js';
import { Myth, Sparks } from './runes.js';
import { Bolts } from './effects.js';
import { Calendar, today0, addDays, sameDay, dayLabel, timeSpan, MON, detailHTML, whenLabel, rangeShort } from './calendar.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const now = () => new Date().toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' });
const timeOf = (iso) => new Date(iso).toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' });

const ICONS = {
  general: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
  education: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2.5 9 2.5 12 0v-5M22 9v6"/>',
  career: '<rect x="3" y="7" width="18" height="13" rx="1.5"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
  business: '<path d="M4 20V10M10 20V5M16 20v-7M22 20H2"/><path d="M14 4h5v5"/><path d="M19 4l-6 6"/>',
  webdev: '<path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 5l-4 14"/>',
  social: '<path d="M3 10v4l11 5V5L3 10z"/><path d="M14 9a4 4 0 0 1 0 6M7 15l1.5 5h3"/>',
  content: '<rect x="3" y="6" width="13" height="12" rx="1.5"/><path d="M16 10l5-3v10l-5-3"/>',
  reminder: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
};
const LAMPS = [['ollama', 'Ollama'], ['searxng', 'Webbsök'], ['telegram', 'Telegram'], ['slack', 'Slack'], ['mail', 'Mail']];
const DOC_TYPES = ['.txt', '.md', '.pdf', '.docx'];

const state = {
  settings: null, agents: [], names: {}, stats: {}, busyAgent: null, oldestId: null,
  status: {}, securityRejected: 0, photos: new Set(),
};
const tree = new Tree($('tree'));
const myth = new Myth($('myth'));
const sparks = new Sparks($('sparks'));
const bolts = new Bolts($('guides'), $('bolts'));
const calendar = new Calendar($('cal'), { onDelete: async (ev, { whole = true } = {}) => {
  const path = ev.source === 'reminder' ? `/reminders/${ev.id}`
    : `/calendar/events/${ev.id}${ev.occurrence && !whole ? `?occurrence=${ev.occurrence}` : ''}`;
  try { await api(path, { method: 'DELETE' }); refreshCalendar(); } catch (e) { sys(`Kunde inte ta bort: ${e.message}`); }
} });
const panel = $('panel');
let anchors = {}, geo = null;

/* =====================================================================
   Boot
   ===================================================================== */
async function boot() {
  const token = await getToken();
  if (!token) { $('lockText').textContent = 'Öppna Yggdrasil via skrivbordsikonen.'; return; }
  for (;;) {
    const h = await health();
    if (h && h.ready) { state.uiVersion = h.ui; break; }
    $('lockText').textContent = h ? 'Yggdrasil vaknar (väntar på Ollama / synkar minnet)…' : 'Kärnan körs inte – startar den?';
    await new Promise((r) => setTimeout(r, 2000));
  }
  try {
    state.settings = await api('/settings');
    state.agents = await api('/agents');
    state.photos = new Set(await api('/people/photos'));
  } catch (e) { $('lockText').textContent = `Kunde inte läsa inställningar: ${e.message}`; return; }
  state.names = Object.fromEntries(state.agents.map((a) => [a.id, a.name]));
  state.names.reminder_agent = state.names.calendar_agent = state.settings.planner_name || 'Planering';
  applyNames();
  renderLamps(); renderAgents(); renderWells(); setupBackground(); setupSound(); setupSearch();
  calendar.setPeople(state.settings.people);
  layout();
  $('lock').classList.add('gone');
  await Promise.allSettled([loadHistory(), refreshStatus(), refreshCalendar(), refreshSystem(), loadBackground()]);
  followEvents(onEvent, (up) => { if (!up) setStatus('Tappade kontakten med kärnan – försöker igen…'); else setStatus(null); });
  setInterval(refreshStatus, 15000); setInterval(refreshSystem, 2000); setInterval(refreshCalendar, 60000);
  setInterval(() => { $('clock').textContent = new Date().toLocaleTimeString('sv-SE'); }, 1000);
  requestAnimationFrame(loop);
}

function applyNames() {
  const sys = (state.settings.system_name || 'Yggdrasil').toUpperCase();
  $('brandName').textContent = sys; $('titleName').textContent = sys; $('lockTitle').textContent = sys; document.title = state.settings.system_name || 'Yggdrasil';
  $('askInput').placeholder = `Fråga ${state.settings.orchestrator_name || 'Oden'}…  (Ctrl+Alt+J)`;
}
const oden = () => state.settings?.orchestrator_name || 'Oden';

/* =====================================================================
   Layout
   ===================================================================== */
function layout() {
  const stage = $('stage'), W = stage.clientWidth, H = stage.clientHeight;
  const L = 18 + 280 + 20, R = 18 + Math.min(360, W * 0.3) + 20, mid = Math.max(320, W - L - R);
  document.documentElement.style.setProperty('--mid', (L + mid / 2) + 'px');
  const agentsEl = $('agents'); agentsEl.style.left = L + 'px'; agentsEl.style.width = mid + 'px';
  const top = 140, size = Math.max(260, Math.min(mid, H - top - 40, 560));
  tree.resize(size);
  const tl = L + (mid - size) / 2, tt = top + (H - top - size) / 2 - 10, k = size / TREE_S;
  $('tree').style.left = tl + 'px'; $('tree').style.top = tt + 'px';
  const map = ([x, y]) => ({ x: tl + x * k, y: tt + y * k });
  const a = tree.anchors();
  anchors = { crown: map(a.crown), root: map(a.root) };
  for (const w of WELLS) anchors[w.id] = map(a[w.id]);
  const title = $('title'), c = map([TREE_S / 2, 0]);
  title.style.left = (c.x - 260) + 'px'; title.style.width = '520px'; title.style.top = (tt + size - 28) + 'px';
  document.querySelectorAll('.well').forEach((w) => { const p = anchors[w.dataset.well]; w.style.left = p.x + 'px'; w.style.top = p.y + 'px'; });
  const st = stage.getBoundingClientRect();
  document.querySelectorAll('#agents .node').forEach((n) => {
    const o = n.querySelector('.oct').getBoundingClientRect();
    anchors[n.dataset.id] = { x: o.left + o.width / 2 - st.left, y: o.bottom - st.top - 4 };
  });
  for (const id of ['telegram', 'slack']) {
    const chip = document.querySelector(`.chip[data-lamp="${id}"]`);
    if (chip) { const r = chip.getBoundingClientRect(); anchors[id] = { x: r.left + r.width / 2 - st.left, y: r.bottom - st.top }; }
  }
  bolts.setAnchors(anchors, state.agents.map((x) => x.id));
  geo = { cx: tl + size / 2, cy: tt + size * 0.5, s: size, midL: L, midR: L + mid };
  myth.resize(W, H, geo);
  layoutBackground();
  renderPeople();
}
addEventListener('resize', () => { if (state.settings) layout(); });

/* =====================================================================
   Header: lamps + status
   ===================================================================== */
function renderLamps() {
  $('lamps').innerHTML = LAMPS.map(([id, label]) => `<span class="chip off" data-lamp="${id}"><i></i>${label}</span>`).join('');
}
function lamp(id, mode, title) {
  const el = document.querySelector(`.chip[data-lamp="${id}"]`); if (!el) return;
  el.classList.remove('off', 'down', 'warn'); if (mode !== 'ok') el.classList.add(mode); el.title = title || '';
}
function flashLamp(id) { const el = document.querySelector(`.chip[data-lamp="${id}"]`); if (!el) return; el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400); }
async function refreshStatus() {
  // The core was restarted with a new version of the interface: load it.
  const h = await health();
  if (h && h.ready && h.ui && state.uiVersion && h.ui !== state.uiVersion) { location.reload(); return; }
  try {
    const s = await api('/status'); state.status = s;
    lamp('ollama', s.ollama ? 'ok' : 'down', s.ollama ? s.model : 'Ollama svarar inte');
    lamp('searxng', s.searxng == null ? 'off' : s.searxng ? 'ok' : 'down', s.searxng == null ? 'Webbsök avstängd' : '');
    lamp('telegram', s.telegram === 'på' ? 'ok' : s.telegram === 'av' ? 'off' : 'warn', `Telegram: ${s.telegram}`);
    lamp('slack', 'off', 'Slack är inte kopplat ännu'); lamp('mail', 'off', 'Mail är inte kopplat ännu');
    $('modelName').textContent = s.model;
  } catch { /* core briefly unavailable */ }
}
let statusOverride = null;
function setStatus(text) { statusOverride = text; renderStatus(); }
function renderStatus() {
  const chip = $('statusChip');
  if (statusOverride) { $('status').innerHTML = esc(statusOverride); chip.classList.remove('busy'); return; }
  if (state.busyAgent) { $('status').innerHTML = state.busyText || `Arbetar · <b>${esc(state.names[state.busyAgent] || state.busyAgent)}</b>`; chip.classList.add('busy'); }
  else { $('status').textContent = 'Online · redo'; chip.classList.remove('busy'); }
}
function busy(agent, html) { state.busyAgent = agent; state.busyText = html; tree.busy = !!agent; renderStatus(); }

/* =====================================================================
   Agents
   ===================================================================== */
function renderAgents() {
  $('agents').innerHTML = state.agents.map((a) => `<div class="node" data-id="${a.id}"><div class="orbit"></div><div class="oct"><div class="oct-in"><svg viewBox="0 0 24 24">${ICONS[a.icon] || ICONS.general}</svg></div><div class="ripple"></div></div><div class="label">${esc(a.name)}</div></div>`).join('');
  document.querySelectorAll('#agents .node').forEach((n) => n.onclick = (e) => {
    e.stopPropagation(); const id = n.dataset.id, st = state.stats[id] || { n: 0, t: [], last: '–' };
    const avg = st.t.length ? (st.t.reduce((x, y) => x + y, 0) / st.t.length).toFixed(1) + ' s' : '–';
    const p = $('pop'); p.innerHTML = `<b>${esc(state.names[id])}</b><br><small>Idag:</small> ${st.n} uppdrag · snitt ${avg}<br><small>Senast:</small> ${esc(st.last)}`;
    const r = n.getBoundingClientRect(), sr = $('stage').getBoundingClientRect();
    p.style.display = 'block'; p.style.left = (r.left - sr.left - 60) + 'px'; p.style.top = (r.bottom - sr.top + 8) + 'px';
  });
}
const agentNode = (id) => document.querySelector(`#agents .node[data-id="${id}"]`);
function lightAgent(id, on) { agentNode(id)?.classList.toggle('active', on); }
bolts.onImpact = (key) => {
  const n = agentNode(key); if (n) { n.classList.remove('hit'); void n.offsetWidth; n.classList.add('hit'); }
  tree.pulseWell(key); if (key === 'crown' || key === 'root') tree.burst();
};
function fire(from, to, n) { bolts.fire(from, to, n); play('fx'); }

/* =====================================================================
   Wells + panels
   ===================================================================== */
function renderWells() {
  $('wells').innerHTML = WELLS.map((w) => `<div class="well" data-well="${w.id}"><div class="hit"></div><span>${w.name}${w.id === 'hvergelmer' ? '<em class="badge" id="secBadge" hidden>0</em>' : ''}</span><small>${w.role}</small></div>`).join('');
  document.querySelectorAll('.well').forEach((w) => w.onclick = (e) => {
    e.stopPropagation(); tree.pulseWell(w.dataset.well);
    if (w.dataset.well === 'urd') { closePanel(); calendar.open(); }
    else if (w.dataset.well === 'mimer') openMimer();
    else openHvergelmer();
  });
}
function openPanel(html) {
  panel.innerHTML = html; panel.classList.add('open');
  panel.querySelector('[data-close]')?.addEventListener('click', closePanel);
}
function closePanel() { panel.classList.remove('open'); }
panel.addEventListener('click', (e) => e.stopPropagation());

async function openMimer() {
  let stats = null, folders = [];
  try { [stats, folders] = await Promise.all([api('/memory/stats'), api('/documents/folders')]); } catch { /* shown as unknown */ }
  openPanel(`<h3><span>MIMER · MINNE</span><button data-close>✕</button></h3>
    <div class="stat"><span>Samtal i minnet</span><b>${stats ? stats.conversations : '–'}</b></div>
    <div class="stat"><span>Dokumentdelar</span><b>${stats ? stats.document_chunks : '–'}</b></div>
    <div class="stat"><span>Mappar</span><b>${folders.length ? esc(folders.slice(0, 8).join(' · ')) : '–'}</b></div>
    <div class="dropzone">Dra och släpp dokument (txt, md, pdf, docx) var som helst i fönstret – ${esc(oden())} frågar var de ska sparas och lär sig innehållet.</div>`);
}
function openHvergelmer() {
  openPanel(`<h3><span>HVERGELMER · SÄKERHET</span><button data-close>✕</button></h3>
    <div class="chk"><span>🛡️</span><div>Säkerhetskontrollerna byggs i ett senare steg<small>Brandvägg, öppna portar, Defender, autostart och uppdateringar – med förslag du kan skjuta upp eller ignorera.</small></div></div>
    <div class="chk"><span>${state.securityRejected ? '⚠️' : '✅'}</span><div>Okända avsändare på Telegram sedan start: ${state.securityRejected}<small>Yggdrasil svarar bara din egen chatt.</small></div></div>`);
}

/* =====================================================================
   Family nodes (rolling 7 days)
   ===================================================================== */
const photoCache = {};
function renderPeople() {
  const people = state.settings?.people || [], box = $('people'); if (!people.length) { box.innerHTML = ''; return; }
  box.innerHTML = people.map((p) => `<div class="person" data-person="${p.id}" style="--pc:${p.color}"><div class="pnode"><b>${esc(p.name[0] || '?')}</b></div><div class="pinfo"><div class="pname">${esc(p.name)}</div><div class="plist"></div></div></div>`).join('');
  const per = box.clientHeight / people.length, fit = Math.max(1, Math.floor((per - 30) / 19));
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
  box.querySelectorAll('.person').forEach((el) => {
    const pid = el.dataset.person, ev = calendar.upcoming(pid, 7), list = el.querySelector('.plist');
    el.style.height = per + 'px';
    el.classList.toggle('soon', ev.some((e) => { if (e.allDay || !sameDay(e.date, today0())) return false; const [h, m] = e.start.split(':').map(Number); const t = h * 60 + m; return t >= nowMin && t - nowMin <= 120; }));
    const show = ev.length > fit ? fit - 1 : fit;
    list.innerHTML = ev.length ? ev.slice(0, show).map((e) => `<div class="pev${sameDay(e.date, today0()) ? ' today' : ''}"><small>${whenLabel(e)}</small>${esc(e.short || e.title)}</div>`).join('') + (ev.length > show ? `<div class="pmore">+${ev.length - show} till</div>` : '')
      : '<div class="pev none">Inget de närmaste 7 dagarna</div>';
    el.onclick = (e) => { e.stopPropagation(); personPanel(pid); };
    const node = el.querySelector('.pnode'), b = node.querySelector('b');
    if (photoCache[pid]) { b.style.backgroundImage = `url(${photoCache[pid]})`; b.classList.add('photo'); }
    else if (photoCache[pid] === undefined && state.photos.has(pid)) loadPhoto(pid);
    node.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); };
    node.ondrop = (e) => { e.preventDefault(); e.stopPropagation(); document.body.classList.remove('dragging'); uploadPhoto(pid, e.dataTransfer.files[0]); };
  });
}
async function loadPhoto(pid) {
  photoCache[pid] = null;
  try { const blob = await api(`/people/${pid}/photo`); photoCache[pid] = URL.createObjectURL(blob); renderPeople(); } catch { /* no photo yet */ }
}
async function uploadPhoto(pid, file) {
  if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) { sys('Profilbilder måste vara PNG, JPG eller WebP.'); return; }
  try { await api(`/people/${pid}/photo`, { method: 'PUT', raw: file }); state.photos.add(pid); photoCache[pid] = undefined; renderPeople(); sys('Profilbilden är sparad.'); }
  catch (e) { sys(`Kunde inte spara bilden: ${e.message}`); }
}
function personPanel(pid) {
  const p = state.settings.people.find((x) => x.id === pid), ev = calendar.upcoming(pid, 7);
  openPanel(`<h3><span style="color:${p.color}">${esc(p.name.toUpperCase())} · 7 DAGAR</span><button data-close>✕</button></h3>` +
    (ev.length ? ev.map((e, i) => `<div class="chk pitem" data-i="${i}" style="border-left:3px solid ${p.color};cursor:pointer"><div>${esc(e.short || e.title)}<small>${e.allDay ? rangeShort(e) : `${dayLabel(e.date)} ${e.date.getDate()} ${MON[e.date.getMonth()]} · ${timeSpan(e)}`}${e.recurrenceLabel ? ' · ↻' : ''}${e.location ? ' · ' + esc(e.location) : ''}</small></div></div>`).join('')
      : '<div class="chk"><div>Inget planerat de närmaste 7 dagarna.</div></div>') +
    '<button class="cbtn openbtn" id="openCal">Öppna kalender</button>');
  $('openCal').onclick = (e) => { e.stopPropagation(); closePanel(); calendar.open(pid); };
  panel.querySelectorAll('.pitem').forEach((el) => el.onclick = () => {
    const item = ev[+el.dataset.i];
    openPanel(`<h3><span style="color:${p.color}">${esc(p.name.toUpperCase())}</span><button data-close>✕</button></h3><div class="evd-inline" style="--pc:${p.color}">${detailHTML(item, p.name)}</div><button class="cbtn openbtn" id="backBtn">Tillbaka</button>`);
    $('backBtn').onclick = (e) => { e.stopPropagation(); personPanel(pid); };
  });
}
async function refreshCalendar() {
  const day = (iso) => { const d = new Date(iso); d.setHours(0, 0, 0, 0); return d; };
  const hhmm = (iso) => new Date(iso).toTimeString().slice(0, 5);
  const from = addDays(today0(), -45), to = addDays(today0(), 120);
  const [rem, cal] = await Promise.allSettled([
    api('/reminders/upcoming?days=120'),
    api(`/calendar/events?start=${encodeURIComponent(from.toISOString())}&end=${encodeURIComponent(to.toISOString())}`),
  ]);
  const events = [];
  if (rem.status === 'fulfilled') for (const r of rem.value) events.push({ id: r.id, key: `r${r.id}`, source: 'reminder', kind: 'reminder', person: r.person, date: day(r.due), endDate: addDays(day(r.due), 1), allDay: false, start: hhmm(r.due), end: '', title: r.text, short: `⏰ ${r.text}`, note: r.recurrence_label || '', location: '' });
  if (cal.status === 'fulfilled') for (const e of cal.value) {
    const d0 = day(e.start_at), allDay = !!e.all_day;
    events.push({ id: e.id, key: e.key, source: 'calendar', kind: e.kind, person: e.person, date: d0, endDate: allDay && e.end_at ? day(e.end_at) : addDays(d0, 1), allDay,
      start: hhmm(e.start_at), end: e.end_at && !allDay ? hhmm(e.end_at) : '', title: e.title, short: e.short, icon: e.icon, location: e.location, details: e.details,
      note: (e.details || {}).note || '', occurrence: e.occurrence || '', recurrenceLabel: e.recurrence_label || '' });
  }
  if (rem.status === 'fulfilled' || cal.status === 'fulfilled') { calendar.setEvents(events); renderPeople(); }
}

/* =====================================================================
   Log + chat
   ===================================================================== */
const logEl = $('log');
function add(el, prepend = false) {
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 60;
  if (prepend) logEl.insertBefore(el, logEl.firstChild.nextSibling); else logEl.appendChild(el);
  if (!prepend && atBottom) logEl.scrollTop = logEl.scrollHeight;
  applySearch(el);
}
function md(text) {
  const lines = esc(text).split('\n'); let html = '', list = null;
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
    const bullet = line.match(/^\s*[-*•]\s+(.*)/), num = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (bullet || num) { const tag = bullet ? 'ul' : 'ol'; if (list !== tag) { if (list) html += `</${list}>`; html += `<${tag}>`; list = tag; } html += `<li>${(bullet || num)[1]}</li>`; continue; }
    if (list) { html += `</${list}>`; list = null; }
    if (line.trim()) html += `<p>${line}</p>`;
  }
  if (list) html += `</${list}>`;
  return html;
}
function msg(who, text, meta, time, opts = {}) {
  if (who === 'jarvis' && meta && meta !== oden()) meta = `${oden()} · ${meta}`;   // Oden answers, the agent did the work
  const m = document.createElement('div'); m.className = `msg ${who}${opts.err ? ' err' : ''}`;
  m.innerHTML = `<small><span>${esc(meta)}</span><span>${time || now()}</span></small><div class="md">${md(text)}</div>`;
  add(m, opts.prepend); return m;
}
function step(text) { const s = document.createElement('div'); s.className = 'step'; s.innerHTML = `<b>›</b> ${esc(text)}`; add(s); }
function sys(text) { const s = document.createElement('div'); s.className = 'sysmsg'; s.textContent = text; add(s); }

async function loadHistory(beforeId) {
  try {
    const rows = await api(`/history?limit=40${beforeId ? `&before_id=${beforeId}` : ''}`);
    if (!rows.length) return;
    state.oldestId = rows[0].id;
    const frag = [];
    for (const r of rows) frag.push(r);
    if (beforeId) { for (const r of frag.reverse()) histMsg(r, true); }
    else { const day = document.createElement('div'); day.className = 'day'; day.textContent = 'TIDIGARE'; logEl.appendChild(day); frag.forEach((r) => histMsg(r)); }
    let more = logEl.querySelector('.more-hist');
    if (!more) { more = document.createElement('div'); more.className = 'more-hist'; more.textContent = 'Visa äldre'; logEl.insertBefore(more, logEl.firstChild); more.onclick = () => loadHistory(state.oldestId); }
    if (rows.length < 40) more.remove();
    if (!beforeId) logEl.scrollTop = logEl.scrollHeight;
  } catch { /* history is optional */ }
}
function histMsg(r, prepend = false) {
  const d = new Date(r.created_at), t = sameDay(d, new Date()) ? timeOf(r.created_at) : `${d.getDate()} ${MON[d.getMonth()]} ${timeOf(r.created_at)}`;
  if (r.role === 'user') msg('user', r.content, 'Du', t, { prepend });
  else msg('jarvis', r.content, state.names[r.agent_id] || r.agent_id || oden(), t, { prepend });
}

let waiting = false;
$('ask').addEventListener('submit', async (e) => {
  e.preventDefault(); const input = $('askInput'), text = input.value.trim(); if (!text || waiting) return;
  input.value = ''; waiting = true; msg('user', text, 'Du');
  const typing = document.createElement('div'); typing.className = 'typing'; typing.textContent = `${oden().toUpperCase()} TÄNKER…`; add(typing);
  try {
    const res = await api('/chat', { method: 'POST', body: { message: text, channel: 'ui' } });
    typing.remove(); msg('jarvis', res.reply, state.names[res.agent] || res.agent, null, { err: !res.success }); play('reply');
  } catch (err) { typing.remove(); msg('jarvis', `Något gick fel: ${err.message}`, oden(), null, { err: true }); }
  finally { waiting = false; }
});

function setupSearch() {
  $('search').addEventListener('input', () => logEl.querySelectorAll('.msg,.step,.sysmsg').forEach(applySearch));
  $('steps').checked = state.settings.show_steps !== false;
  document.body.classList.toggle('hide-steps', !$('steps').checked);
  $('steps').addEventListener('change', (e) => { document.body.classList.toggle('hide-steps', !e.target.checked); saveSettings({ show_steps: e.target.checked }); });
}
function applySearch(el) {
  if (!el.classList || !(el.classList.contains('msg') || el.classList.contains('step') || el.classList.contains('sysmsg'))) return;
  const q = $('search').value.trim().toLowerCase(); el.style.display = !q || el.textContent.toLowerCase().includes(q) ? '' : 'none';
}

/* =====================================================================
   Live events -> visuals
   ===================================================================== */
const CHANNEL = { terminal: 'Terminal', telegram: '✈ Telegram', ui: 'Chatt', debug: 'Felsökning' };
function onEvent(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case 'query.received':
      if (d.channel === 'telegram') { flashLamp('telegram'); fire('telegram', 'crown'); }
      if (d.channel !== 'ui' && d.text) msg('user', d.text, CHANNEL[d.channel] || d.channel);
      busy('__oden', `<b>${esc(oden())}</b> analyserar`);
      break;
    case 'query.queued': step(ev.message); break;
    case 'agent.selected': {
      const label = state.names[d.agent] || d.agent;
      step(d.reason === 'pending_reply' ? `${oden()}: svar på väntande fråga → ${label}` : `${oden()}: '${d.category}' → ${label}`);
      busy(d.agent, `Arbetar · <b>${esc(label)}</b>`);
      if (d.agent === 'reminder_agent' || d.agent === 'calendar_agent') fire('root', 'urd'); else { fire('crown', d.agent); lightAgent(d.agent, true); }
      break; }
    case 'memory.lookup':
      step(ev.message); fire('root', 'mimer', 2); setTimeout(() => fire('mimer', 'root', 2), 650); break;
    case 'websearch.query':
      step(ev.message); flashLamp('searxng'); agentNode(state.busyAgent)?.classList.add('searching'); busy(state.busyAgent, 'Söker på <b>webben</b>'); break;
    case 'websearch.results': case 'websearch.failed':
      step(ev.message); agentNode(state.busyAgent)?.classList.remove('searching'); break;
    case 'query.completed': {
      const id = d.agent; step(d.success === false ? `${state.names[id] || id} misslyckades` : `${state.names[id] || id} svarade på ${d.seconds} s`);
      if (id && id !== 'reminder_agent' && id !== 'calendar_agent') { fire(id, 'crown'); setTimeout(() => lightAgent(id, false), 500); }
      agentNode(id)?.classList.remove('searching');
      const st = state.stats[id] = state.stats[id] || { n: 0, t: [], last: '' }; st.n++; st.t.push(d.seconds || 0); st.last = d.text || st.last;
      if (d.channel && d.channel !== 'ui' && d.reply) { msg('jarvis', d.reply, state.names[id] || id); play('reply'); }
      if (d.channel === 'telegram') setTimeout(() => { fire('crown', 'telegram'); flashLamp('telegram'); }, 300);
      busy(null); break; }
    case 'reminder.created': case 'reminder.cancelled': sys(`⏰ ${ev.message}`); fire('root', 'urd'); refreshCalendar(); break;
    case 'calendar.created': case 'calendar.updated': case 'calendar.cancelled': sys(`📅 ${ev.message}`); fire('root', 'urd'); refreshCalendar(); break;
    case 'reminder.delivered': sys(`⏰ ${ev.message}`); tree.pulseWell('urd'); toast('⏰ PÅMINNELSE', ev.message.replace(/^Påminnelse skickad: /, '')); play('reminder'); refreshCalendar(); break;
    case 'memory.synced': sys('Långtidsminnet uppdaterat'); tree.pulseWell('mimer'); break;
    case 'memory.document_added': sys(`📄 ${ev.message}`); tree.pulseWell('mimer'); break;
    case 'security.rejected': { state.securityRejected++; const b = $('secBadge'); b.hidden = false; b.textContent = state.securityRejected; sys(`🛡️ ${ev.message}`); tree.pulseWell('hvergelmer'); break; }
    case 'core.online': sys('🟢 Yggdrasil är online'); refreshStatus(); break;
    case 'core.offline': sys('Yggdrasil stängs av'); break;
    default: break;
  }
}
function toast(head, text) {
  const t = $('toast'); t.innerHTML = `<small>${esc(head)}</small>${esc(text)}`; t.style.setProperty('--tx', ((geo?.cx || 400) - 150) + 'px');
  t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), 6000);
}

/* =====================================================================
   File drop -> Mimer (Oden asks where it belongs)
   ===================================================================== */
let dragDepth = 0;
addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; document.body.classList.add('dragging'); });
addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove('dragging'); } });
addEventListener('dragover', (e) => e.preventDefault());
addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; document.body.classList.remove('dragging'); for (const f of e.dataTransfer.files) intake(f); });
async function intake(file) {
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (!DOC_TYPES.includes(ext)) { sys(`${file.name}: bara ${DOC_TYPES.join(', ')} kan läras in.`); return; }
  if (file.size > 25 * 1024 * 1024) { sys(`${file.name} är större än 25 MB.`); return; }
  let folders = [];
  try { folders = await api('/documents/folders'); } catch { /* none */ }
  const m = msg('jarvis', `Var vill du att jag sparar **${file.name}**?`, oden());
  const box = document.createElement('div'); box.className = 'secbtns'; box.style.marginTop = '8px';
  box.innerHTML = folders.map((f) => `<button data-folder="${esc(f)}">${esc(f)}</button>`).join('') + '<button data-folder="__new">Ny mapp…</button>';
  m.appendChild(box);
  box.querySelectorAll('button').forEach((b) => b.onclick = async () => {
    let folder = b.dataset.folder;
    if (folder === '__new') { folder = (window.prompt('Namn på ny mapp (t.ex. skola/kurs1):') || '').trim(); if (!folder) return; }
    box.remove(); msg('user', folder, 'Du');
    try {
      const r = await api(`/documents?folder=${encodeURIComponent(folder)}&name=${encodeURIComponent(file.name)}`, { method: 'PUT', raw: file });
      msg('jarvis', `Sparad som **${r.path}**. Jag lär mig innehållet nu.`, oden()); fire('root', 'mimer');
    } catch (err) { msg('jarvis', `Kunde inte spara filen: ${err.message}`, oden(), null, { err: true }); }
  });
}

/* =====================================================================
   Background image
   ===================================================================== */
const BG_INPUTS = { bgStrength: 'strength', bgSize: 'size', bgX: 'x', bgY: 'y', bgDim: 'dim', bgEdgeW: 'edge_width', bgEdgeS: 'edge_strength' };
let bgUrl = null, bgRatio = 16 / 9;
function setupBackground() {
  const b = state.settings.background;
  for (const [id, key] of Object.entries(BG_INPUTS)) {
    $(id).value = b[key];
    $(id).addEventListener('input', () => { state.settings.background[key] = +$(id).value; applyBackground(); saveSettingsDebounced({ background: state.settings.background }); });
  }
  $('bgBtn').onclick = (e) => togglePop('bgPop', e);
  $('bgPop').addEventListener('click', (e) => e.stopPropagation());
  $('bgPick').onclick = () => $('bgFile').click();
  $('bgFile').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try { await api('/assets/background', { method: 'PUT', raw: f }); await loadBackground(); } catch (err) { sys(`Kunde inte spara bakgrunden: ${err.message}`); }
  };
  $('bgOff').onclick = async () => { try { await api('/assets/background', { method: 'DELETE' }); } catch { /* none */ } bgUrl = null; applyBackground(); };
}
async function loadBackground() {
  try {
    const blob = await api('/assets/background'); if (bgUrl) URL.revokeObjectURL(bgUrl); bgUrl = URL.createObjectURL(blob);
    const img = new Image(); img.onload = () => { bgRatio = img.width / img.height; applyBackground(); }; img.src = bgUrl;
  } catch { bgUrl = null; applyBackground(); }
}
function applyBackground() {
  const b = state.settings.background, w = $('bgwrap');
  $('bgimg').style.backgroundImage = bgUrl ? `url(${bgUrl})` : 'none';
  w.style.opacity = bgUrl ? b.strength / 100 : 0;
  const ew = b.edge_width, ea = (1 - b.edge_strength / 100).toFixed(2), e = `rgba(0,0,0,${ea})`;
  const mask = `linear-gradient(90deg,${e},#000 ${ew}%,#000 ${100 - ew}%,${e}),linear-gradient(${e},#000 ${ew * 1.2}%,#000 ${100 - ew * 1.2}%,${e})`;
  $('bgimg').style.webkitMaskImage = mask; $('bgimg').style.maskImage = mask;
  $('vS').textContent = b.strength + '%'; $('vZ').textContent = b.size + '%'; $('vX').textContent = b.x; $('vY').textContent = b.y;
  $('vD').textContent = b.dim + '%'; $('vEW').textContent = b.edge_width + '%'; $('vES').textContent = b.edge_strength + '%';
  layoutBackground();
}
function layoutBackground() {
  if (!geo || !state.settings) return; const b = state.settings.background, w = $('bgwrap'), mid = geo.midR - geo.midL;
  const W = mid * b.size / 100, H = W / bgRatio, cx = geo.midL + mid / 2 + (b.x / 100) * mid, cy = geo.cy + (b.y / 100) * geo.s;
  Object.assign(w.style, { width: W + 'px', height: H + 'px', left: (cx - W / 2) + 'px', top: (cy - H / 2) + 'px' });
  const dx = ((geo.cx - (cx - W / 2)) / W * 100).toFixed(1), dy = ((geo.cy - geo.s * 0.12 - (cy - H / 2)) / H * 100).toFixed(1);
  $('bgdim').style.background = `radial-gradient(ellipse 20% 30% at ${dx}% ${dy}%,rgba(0,0,0,${b.dim / 100}),transparent 100%)`;
}

/* =====================================================================
   Sound
   ===================================================================== */
const SOUND = [['voice', '🗣', 'Odens röst', 'Uppläsning av svar (kommer med röststeget)'], ['reply', '💬', 'Svar', 'Ljud när ett svar kommer'],
  ['reminder', '⏰', 'Påminnelser', ''], ['mail', '✉', 'Mail-notiser', ''], ['fx', '✦', 'Effekter', 'Skott och pulser']];
let audio = null;
function setupSound() {
  SOUND[0][2] = `${oden()}s röst`;
  $('soundBtn').onclick = (e) => togglePop('soundPop', e);
  $('soundPop').addEventListener('click', (e) => e.stopPropagation());
  $('masterMute').checked = !!state.settings.sound.master_mute;
  $('masterMute').onchange = (e) => { state.settings.sound.master_mute = e.target.checked; renderSound(); saveSettings({ sound: state.settings.sound }); };
  renderSound();
}
function renderSound() {
  const s = state.settings.sound, off = s.master_mute;
  $('soundBtn').textContent = off ? 'Tyst' : 'Ljud'; $('soundBtn').classList.toggle('silent', off); $('soundRows').classList.toggle('off', off);
  $('soundRows').innerHTML = SOUND.map(([k, ic, name, desc]) => { const v = s.levels[k] ?? 0, m = s.muted[k] || !v;
    return `<div class="srow${m ? ' muted' : ''}"><button data-mute="${k}">${m ? '🔇' : ic}</button><span>${esc(name)}${desc ? `<small>${esc(desc)}</small>` : ''}</span><input type="range" min="0" max="100" value="${v}" data-vol="${k}"><span class="v">${v}%</span></div>`; }).join('');
  $('soundRows').querySelectorAll('[data-vol]').forEach((r) => {
    r.oninput = () => { s.levels[r.dataset.vol] = +r.value; r.nextElementSibling.textContent = r.value + '%'; };
    r.onchange = () => { renderSound(); play(r.dataset.vol); saveSettings({ sound: s }); };
  });
  $('soundRows').querySelectorAll('[data-mute]').forEach((b) => b.onclick = () => { s.muted[b.dataset.mute] = !s.muted[b.dataset.mute]; renderSound(); saveSettings({ sound: s }); });
}
function play(cat) {
  const s = state.settings?.sound; if (!s || s.master_mute || s.muted[cat]) return;
  const v = (s.levels[cat] ?? 0) / 100; if (!v) return;
  try {
    audio = audio || new AudioContext(); const o = audio.createOscillator(), g = audio.createGain();
    const f = { reply: 880, reminder: 990, mail: 660, fx: 1400, voice: 520 }[cat] || 800;
    o.type = cat === 'fx' ? 'square' : 'sine'; o.frequency.setValueAtTime(f, audio.currentTime);
    if (cat === 'fx') o.frequency.exponentialRampToValueAtTime(f * 0.3, audio.currentTime + 0.09);
    g.gain.value = 0.06 * v; g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + (cat === 'fx' ? 0.1 : 0.35));
    o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.36);
  } catch { /* audio unavailable */ }
}

/* =====================================================================
   Settings persistence, popups, system meter, keyboard
   ===================================================================== */
async function saveSettings(patch) { try { state.settings = await api('/settings', { method: 'PATCH', body: patch }); } catch (e) { sys(`Kunde inte spara inställningen: ${e.message}`); } }
let saveTimer = null;
function saveSettingsDebounced(patch) { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveSettings(patch), 600); }
function togglePop(id, e) { e.stopPropagation(); for (const p of ['bgPop', 'soundPop']) if (p !== id) $(p).classList.remove('open'); $(id).classList.toggle('open'); }
addEventListener('click', () => { $('bgPop').classList.remove('open'); $('soundPop').classList.remove('open'); closePanel(); calendar.close(); $('pop').style.display = 'none'; });

const spark = $('spark'); for (let i = 0; i < 16; i++) spark.appendChild(document.createElement('span'));
async function refreshSystem() {
  try {
    const s = await api('/system');
    if (s.gpu_percent == null) { $('gpuPct').textContent = 'n/a'; return; }
    $('gpuPct').textContent = s.gpu_percent + '%'; $('gpuBar').style.width = s.gpu_percent + '%';
    $('vram').textContent = s.vram_used_gb.toFixed(1); $('vramTotal').textContent = Math.round(s.vram_total_gb);
    spark.appendChild(spark.firstElementChild); spark.lastElementChild.style.height = Math.max(8, s.gpu_percent) + '%';
  } catch { /* ignore */ }
}

addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closePanel(); calendar.close(); }
  if (e.ctrlKey && !e.altKey && e.key.toLowerCase() === 'f') { e.preventDefault(); $('search').focus(); }
  if (e.ctrlKey && e.altKey && e.key.toLowerCase() === 'j') { e.preventDefault(); $('askInput').focus(); }
});
// Called by the desktop app when the global hotkey (Ctrl+Alt+J) brings the window up.
window.ygg = { focusAsk: () => $('askInput').focus() };

/* =====================================================================
   Animation loop
   ===================================================================== */
function loop(t) { sparks.draw(); myth.draw(t, tree.level); tree.draw(t); requestAnimationFrame(loop); }

boot();
