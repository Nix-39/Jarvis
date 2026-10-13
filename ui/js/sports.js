// Sports ticker: results and upcoming games along the bottom edge.
// The core fetches and caches everything (GET /sports); this module only shows it.
// 2-4 games at a time rotate every 6.5 s (pause on hover). When a league's games
// have all been shown it moves on to the next league. The league menu jumps to a
// league (rotation continues afterwards) and adds/removes leagues. Clicking the
// bar opens all games with logos; a game opens ESPN/shl.se.
// Favourite teams: a star on their games, a "Favoriter" tab with their games and
// news, and a star on every team in the panel to add/remove them. Match mode
// (the button at the right) hides live scores until it is switched off.

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
const FAV_TAB = '__fav';

export class SportsTicker {
  constructor({ onLayout } = {}) {
    this.leagues = []; this.cur = null; this.page = 0; this.timer = null; this.onLayout = onLayout; this.catalog = null;
    this.favorites = []; this.favTeams = []; this.paused = false; this.news = []; this.liveNote = '';
    $('matchBtn').onclick = (e) => { e.stopPropagation(); this.setPause(!this.paused); };
    $('league').onclick = (e) => { e.stopPropagation(); const m = $('leagueMenu'); m.classList.toggle('open'); if (m.classList.contains('open')) this.renderMenu(); };
    $('leagueMenu').onclick = (e) => e.stopPropagation();
    $('track').onclick = (e) => { e.stopPropagation(); this.isOpen() ? this.closeScores() : this.openScores(this.current()?.key); };
    $('scores').onclick = (e) => e.stopPropagation();
    document.addEventListener('click', () => { $('leagueMenu').classList.remove('open'); if (this.isOpen()) this.closeScores(); });
    addEventListener('resize', () => { this.page = 0; this.render(); });
  }

  async refresh() {
    try {
      const d = await api('/sports');
      if (!this.catalog) { try { this.catalog = await api('/sports/catalog'); } catch { /* names fall back to keys */ } }
      this.favorites = d.favorites || []; this.favTeams = d.favorite_teams || []; this.paused = !!d.paused; this.liveNote = d.live_note || '';
      $('matchBtn').classList.toggle('on', this.paused);
      $('matchBtn').title = this.paused ? 'Matchläge på – live-ställningar dolda och inga notiser. Klicka för att stänga av.' : 'Matchläge: dölj live-ställningar och pausa notiser (t.ex. när du tittar på en match)';
      this.set(d.leagues || []);
    } catch { /* keep what we have */ }
  }

  async refreshNews() { try { this.news = await api('/news'); } catch { /* keep */ } if (this.isOpen() && $('scores').dataset.league === FAV_TAB) this.openScores(FAV_TAB); }

  async setPause(on) {
    try { await api('/sports/pause', { method: 'PUT', body: { paused: on } }); await this.refresh(); } catch (err) { console.warn('Could not change match mode', err); }
  }

  /** In match mode the score of live (and just finished) games stays hidden. */
  hidden(g) { return this.paused && (g.state === 'in' || (g.state === 'post' && Date.now() - new Date(g.start) < 5 * 3600e3)); }
  score(g, t) { return this.hidden(g) ? '' : (t.score ?? ''); }
  status(g) { return this.hidden(g) ? (g.state === 'in' ? 'LIVE' : 'Spelad') : statusText(g); }
  isFav(t, league) { const n = fold(t.name), s = fold(t.short); return this.favTeams.some((f) => f.league === league && (n.includes(fold(f.team)) || s === fold(f.team))); }

  async toggleFav(team, league) {
    const has = this.favTeams.some((f) => f.league === league && fold(f.team) === fold(team));
    const list = has ? this.favTeams.filter((f) => !(f.league === league && fold(f.team) === fold(team))) : [...this.favTeams, { team, league }];
    try { await api('/sports/favorites', { method: 'PUT', body: { favorites: list } }); await this.refresh(); this.refreshNews(); } catch (err) { console.warn('Could not change favourites', err); }
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
    const pre = g.state === 'pre' || this.hidden(g), h = g.home, a = g.away, hide = this.hidden(g);
    const hc = hide ? '' : h.winner ? 'w' : a.winner ? 'l' : '', ac = hide ? '' : a.winner ? 'w' : h.winner ? 'l' : '';
    return `<span class="game${g.fav ? ' fav' : ''}"><span class="dt">${g.fav ? '<i class="star">★</i>' : ''}${esc(dayText(new Date(g.start)))}</span>`
      + `<b class="${hc}">${esc(h.short)}${pre ? '' : ` ${esc(h.score ?? '')}`}</b><span class="sep">–</span>`
      + `<b class="${ac}">${pre ? '' : `${esc(a.score ?? '')} `}${esc(a.short)}</b>`
      + `<span class="st${g.state === 'in' ? ' live' : ''}">${esc(this.status(g))}</span></span>`;
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

  teamRow(g, t, decided) {
    const state = this.hidden(g) ? 'pre' : g.state;
    const logo = t.logo ? `<img src="/sports/logo/${encodeURIComponent(t.logo)}" alt="">` : `<span class="lg">${esc(t.short.slice(0, 3).toUpperCase())}</span>`;
    const cls = state === 'post' && decided ? (t.winner ? 'win' : 'lose') : '', fav = this.isFav(t, g.league);
    return `<div class="team ${cls}">${logo}<span class="nm">${esc(t.name)}</span>`
      + `<button class="fstar${fav ? ' on' : ''}" data-fav="${esc(t.short)}" data-fl="${esc(g.league)}" title="${fav ? 'Ta bort från favoritlag' : 'Lägg till som favoritlag'}">${fav ? '★' : '☆'}</button>`
      + `<span class="pt">${state === 'pre' ? '' : esc(t.score ?? '')}</span></div>`;
  }

  cardHTML(g, i, label = '') {
    const d = new Date(g.start), when = `${label ? label + ' · ' : ''}${dayText(d)}${g.state === 'pre' ? ' ' + hhmm(d) : ''}`;
    const decided = !this.hidden(g) && (g.home.winner || g.away.winner);
    return `<div class="card${g.fav ? ' fav' : ''}" data-gi="${i}" role="link" tabindex="0"><div class="top"><span>${esc(when)}</span><span class="${g.state === 'in' ? 'live' : ''}">${esc(g.state === 'pre' ? '' : this.status(g))}</span></div>
      ${this.teamRow(g, g.home, decided)}${this.teamRow(g, g.away, decided)}<div class="note"><span class="go">${g.url.includes('espn') ? 'Öppna på ESPN ↗' : 'Öppna ↗'}</span></div></div>`;
  }

  openScores(key) {
    const fav = key === FAV_TAB && this.favTeams.length;
    const league = fav ? null : this.leagues.find((l) => l.key === key) || this.current(); if (!fav && !league) return;
    $('scores').dataset.league = fav ? FAV_TAB : league.key;
    $('scTabs').innerHTML = (this.favTeams.length ? `<button class="cbtn favtab${fav ? ' on' : ''}" data-sl="${FAV_TAB}">★ Favoriter</button>` : '')
      + this.leagues.map((l) => `<button class="cbtn${!fav && l.key === league.key ? ' on' : ''}" data-sl="${esc(l.key)}">${esc(l.name)}</button>`).join('')
      + `${this.paused ? '<span class="paused">Matchläge – live-ställningar dolda</span>' : ''}<button class="cbtn close" data-sx>✕</button>`;
    const games = fav ? this.favorites : league.games;
    let html = games.length ? games.map((g, i) => this.cardHTML(g, i, fav ? g.league_name : '')).join('')
      : `<div class="x">${esc(fav ? 'Inga matcher för dina favoritlag de närmaste dagarna.' : league.error || 'Inga matcher de närmaste dagarna.')}</div>`;
    if (fav) {
      html += `<div class="favside"><h5>FAVORITLAG</h5>${this.favTeams.map((f) => `<span class="ftag">${esc(f.team)}<small>${esc(this.leagueName(f.league))}</small><button data-unfav="${esc(f.team)}" data-fl="${esc(f.league)}" title="Ta bort">✕</button></span>`).join('')}`
        + `${this.liveNote ? `<p class="lnote">${esc(this.liveNote)}</p>` : ''}<h5>NYHETER</h5>`
        + (this.news.length ? this.news.slice(0, 15).map((n, i) => `<div class="nitem" data-ni="${i}"><b>${esc(n.title)}</b><small>${esc(n.team)} · ${esc(n.source)} · ${esc(ago(n.published))}</small></div>`).join('')
          : '<p class="lnote">Inga nyheter om dina lag de senaste två dygnen.</p>') + '</div>';
    }
    $('scGrid').innerHTML = html;
    $('scGrid').classList.toggle('withside', !!fav);
    $('scGrid').querySelectorAll('[data-gi]').forEach((c) => c.onclick = () => openExternal(games[+c.dataset.gi].url));
    $('scGrid').querySelectorAll('[data-ni]').forEach((c) => c.onclick = () => openExternal(this.news[+c.dataset.ni].url));
    $('scGrid').querySelectorAll('[data-fav]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); this.toggleFav(b.dataset.fav, b.dataset.fl); });
    $('scGrid').querySelectorAll('[data-unfav]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); this.toggleFav(b.dataset.unfav, b.dataset.fl); });
    $('scGrid').querySelectorAll('img').forEach((img) => img.onerror = () => { img.replaceWith(Object.assign(document.createElement('span'), { className: 'lg', textContent: '•' })); });
    $('scTabs').querySelectorAll('[data-sl]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); if (b.dataset.sl === FAV_TAB) this.refreshNews(); this.openScores(b.dataset.sl); });
    $('scTabs').querySelector('[data-sx]').onclick = (e) => { e.stopPropagation(); this.closeScores(); };
    $('scores').classList.add('open');
  }

  leagueName(key) { return (this.catalog || []).find((l) => l.key === key)?.name || this.leagues.find((l) => l.key === key)?.name || key.toUpperCase(); }

  closeScores() { $('scores').classList.remove('open'); }
}

/** 'Frölunda HC' -> 'frolundahc' (same folding as the core). */
export function fold(text) { return String(text || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

function ago(iso) {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return min < 60 ? `${min} min sedan` : min < 1440 ? `${Math.round(min / 60)} tim sedan` : `${Math.round(min / 1440)} d sedan`;
}
