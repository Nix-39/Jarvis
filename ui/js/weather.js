// Weather button in the header + weather panel (SMHI, fetched and cached by the core).

import { api } from './api.js';
import { esc } from './calendar.js';

const $ = (id) => document.getElementById(id);
const P = 'stroke-linecap="round" stroke-linejoin="round"';
const CLOUD = 'M7 18h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6 1.6A3.2 3.2 0 0 0 7 18z';
const ICONS = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  part: '<path d="M8 3v1.5M3.5 8H2M4.6 4.6l1 1M12.4 4.6l-1 1"/><path d="M5.5 10.5a3 3 0 0 1 5.6-2"/><path d="M7 19h10a4 4 0 0 0 0-8 5 5 0 0 0-9.6 1.5A3.3 3.3 0 0 0 7 19z"/>',
  moonpart: '<path d="M11 4.5a4 4 0 0 0-5.5 5.4 4 4 0 0 0 5.5-5.4z"/><path d="M7 19h10a4 4 0 0 0 0-8 5 5 0 0 0-9.6 1.5A3.3 3.3 0 0 0 7 19z"/>',
  cloud: `<path d="${CLOUD}"/>`,
  rain: '<path d="M6 15h11a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.5 2A3.5 3.5 0 0 0 6 15z"/><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/>',
  thunder: '<path d="M6 14h11a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.5 2A3.5 3.5 0 0 0 6 14z"/><path d="M12 14l-2 4h3l-2 4"/>',
  snow: '<path d="M6 14h11a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.5 2A3.5 3.5 0 0 0 6 14z"/><path d="M8 18v.01M12 20v.01M16 18v.01M10 22v.01M14 22v.01"/>',
  sleet: '<path d="M6 14h11a4.5 4.5 0 0 0 0-9 6 6 0 0 0-11.5 2A3.5 3.5 0 0 0 6 14z"/><path d="M8 17l-1 3M14 17l-1 3M11 20v.01M17 20v.01"/>',
  fog: '<path d="M4 9h16M3 13h18M5 17h14M8 21h8"/>',
};
export const wxIcon = (key) => `<svg viewBox="0 0 24 24" ${P}>${ICONS[key] || ICONS.cloud}</svg>`;

export class WeatherWidget {
  constructor({ openPanel, isPanel }) {
    this.data = null; this.openPanel = openPanel; this.isPanel = isPanel;
    $('wxBtn').onclick = (e) => { e.stopPropagation(); this.open(); };
  }

  async refresh() {
    try { this.data = await api('/weather'); } catch { return; }
    const d = this.data, btn = $('wxBtn');
    if (!d.ok) { btn.hidden = true; return; }
    btn.hidden = false; document.body.classList.remove('no-weather');
    $('wxIcon').innerHTML = wxIcon(d.now.icon);
    $('wxTemp').textContent = `${d.now.temp}°`;
    const warn = $('wxWarn'); warn.hidden = !d.alert; warn.textContent = d.alert ? d.alert.badge : '';
    btn.title = `${d.place}: ${d.now.text}, ${d.now.temp}°`;
    if (this.isPanel('VÄDER')) this.open();
  }

  open() {
    const d = this.data;
    if (!d || !d.ok) { this.openPanel(`<h3><span>VÄDER</span><button data-close>✕</button></h3><div class="chk"><div>${esc(d?.error || 'Väderdata hämtas…')}</div></div>`); return; }
    const n = d.now, hh = (iso) => new Date(iso).toTimeString().slice(0, 2);
    const lows = d.days.map((x) => x.min), highs = d.days.map((x) => x.max);
    const lo = Math.min(...lows), span = Math.max(1, Math.max(...highs) - lo);
    const updated = new Date(d.updated).toTimeString().slice(0, 5);
    this.openPanel(`<h3><span>VÄDER · ${esc(d.place.toUpperCase())}</span><button data-close>✕</button></h3>
      <div class="wxnow">${wxIcon(n.icon)}<div><div class="t">${n.temp}°</div>
        <p>${esc(n.text)}${n.feels !== n.temp ? ` · känns som ${n.feels}°` : ''} · vind ${n.wind} m/s ${esc(n.dir)}${n.gust && n.gust >= n.wind + 4 ? ` (byar ${n.gust})` : ''}</p></div></div>
      ${d.alert ? `<div class="wxalert">${d.alert.kind === 'snow' ? '❄' : d.alert.kind === 'thunder' ? '⛈' : '🌧'} ${esc(d.alert.text)}</div>` : '<div class="wxalert dry">☀ Inget regn de närmaste 12 timmarna</div>'}
      <div class="hours">${d.hours.map((h, i) => `<div class="hour">${i === 0 ? 'Nu' : hh(h.time)}${wxIcon(h.icon)}<b>${h.temp}°</b><i>${h.rain >= 0.1 ? `${h.rain} mm` : ''}</i></div>`).join('')}</div>
      <div class="days">${d.days.map((x) => `<div class="d" title="${esc(x.text)}"><span>${esc(x.label)}</span>${wxIcon(x.icon)}
        <div class="bar2" style="margin-left:${((x.min - lo) / span) * 70}%;width:${Math.max(6, ((x.max - x.min) / span) * 70)}%"></div>
        <span class="r">${x.min}° / <b>${x.max}°</b>${x.note ? `<small>${esc(x.note)}</small>` : ''}</span></div>`).join('')}</div>
      <div class="src2">Källa: SMHI öppna data · uppdaterad ${updated}${d.error ? ` · ${esc(d.error)}` : ''}</div>`);
  }
}
