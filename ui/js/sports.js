// Sports ticker: results and upcoming games along the bottom edge.
// The core fetches and caches everything (GET /sports); this module only shows it.
// 2-4 games at a time rotate every 6.5 s (pause on hover). When a league's games
// have all been shown it moves on to the next league. The league menu jumps to a
// league (rotation continues afterwards) and adds/removes leagues. Clicking the
// bar opens all games with logos; a game opens ESPN/shl.se.

import { api, openExternal } from './api.js';
import { WD, MON, today0, addDays, sameDay, esc } from './calendar.js';

const $ = (id) => document.getElementById(id);
const ROTATE_MS = 6500;

function dayText(d) {
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  if (sameDay(day, today0())) return 'Idag';
  if (sameDay(day, addDays(today0(), -1))) return 'Igår';
  if (sameDay(day, addDays(today0(), 1))) return 'Imorgon';
  return `${WD[day.getDay()]} ${day.getDate()} ${MON[day.getMonth()]}`;
}
const hhmm = (d) => d.toTimeString().slice(0, 5);
const statusText = (g) => (g.state === 'pre' ? hhmm(new Date(g.start)) : g.state === 'in' ? `LIVE ${g.status}` : g.status);

export class SportsTicker {
  constructor({ onLayout } = {}) {
    this.leagues = []; this.cur = null; this.page = 0; this.timer = null; this.onLayout = onLayout; this.catalog = null;
    $('league').onclick = (e) => { e.stopPropagation(); const m = $('leagueMenu'); m.classList.toggle('open'); if (m.classList.contains('open')) this.renderMenu(); };
    $('leagueMenu').onclick = (e) => e.stopPropagation();
    $('track').onclick = (e) => { e.stopPropagation(); this.isOpen() ? this.closeScores() : this.openScores(this.current()?.key); };
    $('scores').onclick = (e) => e.stopPropagation();
    document.addEventListener('click', () => { $('leagueMenu').classList.remove('open'); if (this.isOpen()) this.closeScores(); });
    addEventListener('resize', () => { this.page = 0; this.render(); });
  }

  async refresh() {
    try { this.set((await api('/sports')).leagues || []); } catch { /* keep what we have */ }
  }

  set(leagues) {
    const before = this.leagues.length;
    this.leagues = leagues;
    const show = leagues.length > 0;
    $('sports').hidden = !show; document.body.classList.toggle('no-sports', !show);
    if (!!before !== show) this.onLayout?.();
    if (!this.leagues.some((l) => l.key === this.cur)) { this.cur = this.rotation()[0]?.key ?? null; this.page = 0; }
    this.render(); if (!this.timer) this.start();
    if ($('leagueMenu').classList.contains('open')) this.renderMenu();
    if (this.isOpen()) this.openScores($('scores').dataset.league);
  }

  /** Leagues that have games in the window (all of them if none has). */
  rotation() { const withGames = this.leagues.filter((l) => l.games.length); return withGames.length ? withGames : this.leagues; }
  current() { return this.leagues.find((l) => l.key === this.cur) || this.rotation()[0]; }
  /** The league after the current one, among those with games. */
  following() {
    const order = this.leagues, r = this.rotation(), at = order.findIndex((l) => l.key === this.cur);
    for (let i = 1; i <= order.length; i++) { const l = order[(at + i) % order.length]; if (r.includes(l)) return l; }
    return r[0];
  }
  jump(key) { this.cur = key; this.page = 0; this.render(); this.start(); }
  perPage() { return Math.max(1, Math.min(4, Math.floor($('track').clientWidth / 360))); }
  isOpen() { return $('scores').classList.contains('open'); }

  gameHTML(g) {
    const pre = g.state === 'pre', h = g.home, a = g.away;
    const hc = h.winner ? 'w' : a.winner ? 'l' : '', ac = a.winner ? 'w' : h.winner ? 'l' : '';
    return `<span class="game"><span class="dt">${esc(dayText(new Date(g.start)))}</span>`
      + `<b class="${hc}">${esc(h.short)}${pre ? '' : ` ${esc(h.score ?? '')}`}</b><span class="sep">–</span>`
      + `<b class="${ac}">${pre ? '' : `${esc(a.score ?? '')} `}${esc(a.short)}</b>`
      + `<span class="st${g.state === 'in' ? ' live' : ''}">${esc(statusText(g))}</span></span>`;
  }

  render() {
    const league = this.current();
    if (!league) return;
    const n = this.perPage(), games = league.games, pages = Math.max(1, Math.ceil(games.length / n));
    if (this.page >= pages) this.page = 0;
    $('leagueName').textContent = league.name.toUpperCase();
    $('tape').innerHTML = games.length ? games.slice(this.page * n, this.page * n + n).map((g) => this.gameHTML(g)).join('')
      : `<span class="game"><span class="x">${esc(league.error || 'Inga matcher de närmaste dagarna')}</span></span>`;
    $('pager').innerHTML = pages > 1 ? Array.from({ length: pages }, (_, i) => `<i class="${i === this.page ? 'on' : ''}"></i>`).join('') : '';
  }

  async renderMenu() {
    if (!this.catalog) { try { this.catalog = await api('/sports/catalog'); } catch { this.catalog = []; } }
    const shown = new Set(this.leagues.map((l) => l.key)), groups = {};
    for (const l of this.catalog) if (!shown.has(l.key)) (groups[l.group] = groups[l.group] || []).push(l);
    const cur = this.current()?.key;
    $('leagueMenu').innerHTML = `<p class="lm-head">Visas</p>`
      + this.leagues.map((l) => `<div class="lm-row${l.key === cur ? ' on' : ''}" data-go="${esc(l.key)}"><span>${esc(l.name)}</span>`
        + `<small>${l.games.length || '–'}</small><button class="lm-x" data-rm="${esc(l.key)}" title="Ta bort">✕</button></div>`).join('')
      + (Object.keys(groups).length ? `<p class="lm-head">Lägg till</p>` : '')
      + Object.entries(groups).map(([g, list]) => `<p class="lm-group">${esc(g)}</p>`
        + list.map((l) => `<div class="lm-row add" data-add="${esc(l.key)}"><span>+ ${esc(l.name)}</span></div>`).join('')).join('');
    const menu = $('leagueMenu');
    menu.querySelectorAll('[data-go]').forEach((d) => d.onclick = () => { this.jump(d.dataset.go); menu.classList.remove('open'); });
    menu.querySelectorAll('[data-rm]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); this.save([...shown].filter((k) => k !== b.dataset.rm)); });
    menu.querySelectorAll('[data-add]').forEach((d) => d.onclick = () => this.save([...shown, d.dataset.add], d.dataset.add));
  }

  async save(keys, jumpTo) {
    try {
      await api('/sports/leagues', { method: 'PUT', body: { leagues: keys } });
      await this.refresh();
      if (jumpTo) this.jump(jumpTo);
    } catch (err) { console.warn('Could not change leagues', err); }
  }

  next() {
    const league = this.current(); if (!league) return;
    const pages = Math.max(1, Math.ceil(league.games.length / this.perPage())), tape = $('tape');
    const following = this.following();
    if (pages === 1 && (!following || following.key === league.key)) return;   // nothing to rotate
    tape.classList.add('out');
    setTimeout(() => {
      this.page++;
      if (this.page >= pages) { this.page = 0; this.cur = following?.key ?? this.cur; }   // all shown: next league
      tape.classList.remove('out'); tape.classList.add('in'); this.render(); void tape.offsetWidth; tape.classList.remove('in');
    }, 450);
  }

  start() { clearInterval(this.timer); this.timer = setInterval(() => { if (!$('sports').matches(':hover') && !this.isOpen()) this.next(); }, ROTATE_MS); }

  teamRow(t, state, decided) {
    const logo = t.logo ? `<img src="/sports/logo/${encodeURIComponent(t.logo)}" alt="">` : `<span class="lg">${esc(t.short.slice(0, 3).toUpperCase())}</span>`;
    const cls = state === 'post' && decided ? (t.winner ? 'win' : 'lose') : '';
    return `<div class="team ${cls}">${logo}<span class="nm">${esc(t.name)}</span><span class="pt">${state === 'pre' ? '' : esc(t.score ?? '')}</span></div>`;
  }

  openScores(key) {
    const league = this.leagues.find((l) => l.key === key) || this.current(); if (!league) return;
    $('scores').dataset.league = league.key;
    $('scTabs').innerHTML = this.leagues.map((l) => `<button class="cbtn${l.key === league.key ? ' on' : ''}" data-sl="${esc(l.key)}">${esc(l.name)}</button>`).join('')
      + '<button class="cbtn close" data-sx>✕</button>';
    $('scGrid').innerHTML = league.games.length ? league.games.map((g, i) => {
      const d = new Date(g.start), when = `${dayText(d)}${g.state === 'pre' ? ' ' + hhmm(d) : ''}`;
      return `<div class="card" data-gi="${i}" role="link" tabindex="0"><div class="top"><span>${esc(when)}</span><span class="${g.state === 'in' ? 'live' : ''}">${esc(g.state === 'pre' ? '' : statusText(g))}</span></div>
        ${this.teamRow(g.home, g.state, g.home.winner || g.away.winner)}${this.teamRow(g.away, g.state, g.home.winner || g.away.winner)}<div class="note"><span class="go">${g.url.includes('espn') ? 'Öppna på ESPN ↗' : 'Öppna ↗'}</span></div></div>`;
    }).join('') : `<div class="x">${esc(league.error || 'Inga matcher de närmaste dagarna.')}</div>`;
    $('scGrid').querySelectorAll('[data-gi]').forEach((c) => c.onclick = () => openExternal(league.games[+c.dataset.gi].url));
    $('scGrid').querySelectorAll('img').forEach((img) => img.onerror = () => { img.replaceWith(Object.assign(document.createElement('span'), { className: 'lg', textContent: '•' })); });
    $('scTabs').querySelectorAll('[data-sl]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); this.openScores(b.dataset.sl); });
    $('scTabs').querySelector('[data-sx]').onclick = (e) => { e.stopPropagation(); this.closeScores(); };
    $('scores').classList.add('open');
  }

  closeScores() { $('scores').classList.remove('open'); }
}
