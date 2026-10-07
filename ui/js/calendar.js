// Urd - the family calendar (week and month views, person filters).
// Events today come from Yggdrasil's reminders; Google Calendar plugs in later
// with the same event shape: {person, date: Date, start: 'HH:MM', end, title, note}.

export const WD = ['Sön', 'Mån', 'Tis', 'Ons', 'Tor', 'Fre', 'Lör'];
export const MON = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
const MONTHS = ['Januari', 'Februari', 'Mars', 'April', 'Maj', 'Juni', 'Juli', 'Augusti', 'September', 'Oktober', 'November', 'December'];

export const today0 = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const sameDay = (a, b) => a.toDateString() === b.toDateString();
export const dayLabel = (d) => sameDay(d, today0()) ? 'Idag' : sameDay(d, addDays(today0(), 1)) ? 'Imorgon' : WD[d.getDay()];
export const timeSpan = (e) => e.end ? `${e.start.replace(':00', '')}–${e.end.replace(':00', '')}` : e.start;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const weekStart = (d) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x; };
export const isoWeek = (d) => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y) / 864e5 + 1) / 7);
};

export class Calendar {
  constructor(el) {
    this.el = el; this.people = []; this.events = [];
    this.view = 'week'; this.anchor = today0(); this.hidden = new Set();
    el.addEventListener('click', (e) => e.stopPropagation());
  }
  setPeople(people) { this.people = people; this.byId = Object.fromEntries(people.map((p) => [p.id, p])); }
  setEvents(events) { this.events = events.slice().sort((a, b) => a.date - b.date || a.start.localeCompare(b.start)); if (this.isOpen()) this.draw(); }
  upcoming(pid, days = 7) { const s = today0(), e = addDays(s, days); return this.events.filter((v) => v.person === pid && v.date >= s && v.date < e); }
  isOpen() { return this.el.classList.contains('open'); }
  open(onlyPid) {
    this.hidden = new Set(onlyPid ? this.people.filter((p) => p.id !== onlyPid).map((p) => p.id) : []);
    this.anchor = today0(); this.draw(); this.el.classList.add('open');
  }
  close() { this.el.classList.remove('open'); }

  #color(pid) { return (this.byId[pid] || { color: '#f0b43c' }).color; }
  #name(pid) { return (this.byId[pid] || { name: '' }).name; }

  draw() {
    const vis = (e) => !this.hidden.has(e.person); let range, body;
    if (this.view === 'week') {
      const ws = weekStart(this.anchor), we = addDays(ws, 6);
      range = `Vecka ${isoWeek(ws)} · ${ws.getDate()} ${MON[ws.getMonth()]} – ${we.getDate()} ${MON[we.getMonth()]}`;
      body = `<div class="week">${[0, 1, 2, 3, 4, 5, 6].map((i) => {
        const d = addDays(ws, i), ev = this.events.filter((e) => sameDay(e.date, d) && vis(e));
        return `<div class="wday${sameDay(d, today0()) ? ' today' : ''}"><h5>${WD[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}</h5>${ev.map((e) =>
          `<div class="cev" style="--pc:${this.#color(e.person)}"><span class="who">${esc(this.#name(e.person))}</span> ${esc(e.title)}<small>${timeSpan(e)}${e.note ? ' · ' + esc(e.note) : ''}</small></div>`).join('')}</div>`;
      }).join('')}</div>`;
    } else {
      const first = new Date(this.anchor.getFullYear(), this.anchor.getMonth(), 1), gs = weekStart(first);
      range = `${MONTHS[first.getMonth()]} ${first.getFullYear()}`;
      body = `<div class="month"><div class="mhead">V</div>${['MÅN', 'TIS', 'ONS', 'TOR', 'FRE', 'LÖR', 'SÖN'].map((h) => `<div class="mhead">${h}</div>`).join('')}${Array.from({ length: 42 }, (_, i) => {
        const d = addDays(gs, i), ev = this.events.filter((e) => sameDay(e.date, d) && vis(e));
        return (i % 7 === 0 ? `<div class="wnum" data-day="${d.toISOString()}">${isoWeek(d)}</div>` : '') +
          `<div class="mcell${d.getMonth() !== first.getMonth() ? ' other' : ''}${sameDay(d, today0()) ? ' today' : ''}" data-day="${d.toISOString()}"><b>${d.getDate()}</b>${ev.slice(0, 4).map((e) =>
            `<div class="mev" style="--pc:${this.#color(e.person)}"><i></i>${e.start} ${esc(e.title)}</div>`).join('')}${ev.length > 4 ? `<div class="mmore">+${ev.length - 4}</div>` : ''}</div>`;
      }).join('')}</div>`;
    }
    this.el.innerHTML = `<div class="calbar"><h3>URD · KALENDER</h3><div class="nav"><button class="cbtn" data-nav="-1">◀</button><span class="range">${range}</span><button class="cbtn" data-nav="1">▶</button><button class="cbtn" data-nav="0">Idag</button></div>
      <button class="cbtn${this.view === 'week' ? ' on' : ''}" data-view="week">Vecka</button><button class="cbtn${this.view === 'month' ? ' on' : ''}" data-view="month">Månad</button>
      <div class="filters"><span class="fchip all${this.hidden.size ? '' : ' on'}" data-all>Alla</span>${this.people.map((p) => `<span class="fchip${this.hidden.has(p.id) ? ' off' : ''}" data-f="${p.id}" style="--pc:${p.color}">${esc(p.name)}</span>`).join('')}</div>
      <button class="cbtn" data-x>✕</button></div><div class="calbody">${body}</div>`;
    const q = (s) => this.el.querySelectorAll(s);
    q('[data-nav]').forEach((b) => b.onclick = () => {
      const n = +b.dataset.nav;
      if (!n) this.anchor = today0();
      else if (this.view === 'week') this.anchor = addDays(this.anchor, 7 * n);
      else this.anchor = new Date(this.anchor.getFullYear(), this.anchor.getMonth() + n, 1);
      this.draw();
    });
    q('[data-view]').forEach((b) => b.onclick = () => { this.view = b.dataset.view; this.draw(); });
    this.el.querySelector('[data-all]').onclick = () => { this.hidden.clear(); this.draw(); };
    q('[data-f]').forEach((b) => b.onclick = () => { const id = b.dataset.f; this.hidden.has(id) ? this.hidden.delete(id) : this.hidden.add(id); this.draw(); });
    q('[data-day]').forEach((b) => b.onclick = () => { this.anchor = new Date(b.dataset.day); this.view = 'week'; this.draw(); });
    this.el.querySelector('[data-x]').onclick = () => this.close();
  }
}
