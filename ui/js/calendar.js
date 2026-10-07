// Urd - the family calendar: day view (one column per family member), week and
// month views, person filters and a detail card for every booking.
// All-day bookings (trips, cups, "Julian hos oss") are drawn as banners across
// the days they cover; recurring bookings arrive as one event per occurrence.
// Event shape: {id, key, source: 'calendar'|'reminder', person, date: Date (midnight),
//   endDate: Date (exclusive midnight), allDay, start: 'HH:MM', end, title, short, icon,
//   kind: 'event'|'work'|'match'|'reminder', location, details, note, occurrence, recurrenceLabel}

export const WD = ['Sön', 'Mån', 'Tis', 'Ons', 'Tor', 'Fre', 'Lör'];
const WD_LONG = ['söndag', 'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag'];
export const MON = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
const MON_LONG = ['januari', 'februari', 'mars', 'april', 'maj', 'juni', 'juli', 'augusti', 'september', 'oktober', 'november', 'december'];
const MONTHS = ['Januari', 'Februari', 'Mars', 'April', 'Maj', 'Juni', 'Juli', 'Augusti', 'September', 'Oktober', 'November', 'December'];

export const today0 = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const sameDay = (a, b) => a.toDateString() === b.toDateString();
export const dayLabel = (d) => sameDay(d, today0()) ? 'Idag' : sameDay(d, addDays(today0(), 1)) ? 'Imorgon' : WD[d.getDay()];
export const timeSpan = (e) => e.allDay ? 'Heldag' : e.end && e.kind !== 'match' ? `${e.start.replace(':00', '')}–${e.end.replace(':00', '')}` : e.start;
export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const longDay = (d) => `${WD_LONG[d.getDay()]} ${d.getDate()} ${MON_LONG[d.getMonth()]}`;
const shortDay = (d) => `${WD[d.getDay()].toLowerCase()} ${d.getDate()} ${MON[d.getMonth()]}`;
const weekStart = (d) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x; };
const daysBetween = (a, b) => Math.round((b - a) / 864e5);
export const lastDay = (e) => addDays(e.endDate, -1);
export const covers = (e, d) => e.date <= d && d < e.endDate;
export const isoWeek = (d) => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y) / 864e5 + 1) / 7);
};

/** 'tor 15 okt – sön 18 okt' for all-day bookings. */
export function rangeShort(e) {
  const last = lastDay(e);
  return sameDay(e.date, last) ? shortDay(e.date) : `${shortDay(e.date)} – ${shortDay(last)}`;
}
/** Compact 'when' for lists: 'Fre 19:15', 'Tor–Sön', 'Nu–Sön'. */
export function whenLabel(e) {
  if (!e.allDay) return `${dayLabel(e.date)} ${timeSpan(e)}`;
  const last = lastDay(e), first = e.date < today0() ? 'Nu' : dayLabel(e.date);
  return sameDay(e.date, last) ? `${first} heldag` : `${first}–${WD[last.getDay()]}`;
}
/** Title with the person's name in front, unless the title already says who it is. */
const labeled = (title, name) => (name && !String(title).toLowerCase().includes(name.toLowerCase()) ? `${name}: ${title}` : title);

/** Full text card for a booking (used in the detail popup). */
export function detailHTML(e, personName) {
  const repeat = e.recurrenceLabel ? `<div class="evd-line evd-muted">Återkommer ${esc(e.recurrenceLabel)}</div>` : '';
  if (e.kind === 'match') {
    const d = e.details || {};
    const role = (d.role || '').replace(/\d+$/, '');
    const head = `${e.icon || ''} ${[d.division, role, `${d.home} - ${d.away}`].filter(Boolean).join(' ')}`;
    const when = `${longDay(e.date)}${d.gather ? ` · samling ${d.gather}` : ''} · start ${e.start}`;
    return `<div class="evd-title">${esc(head)}</div>${e.location ? `<div class="evd-line">${esc(e.location)}</div>` : ''}
      <div class="evd-line evd-muted">${esc(when)}</div>${repeat}
      <div class="evd-crew">${(d.officials || []).map((o) => `<div><b>${esc(o.role)}:</b> ${esc(o.name)}</div>`).join('')}</div>`;
  }
  const when = e.allDay
    ? (sameDay(e.date, lastDay(e)) ? `${longDay(e.date)} · heldag` : `${longDay(e.date)} – ${longDay(lastDay(e))}`)
    : `${longDay(e.date)} · ${timeSpan(e)}`;
  return `<div class="evd-title">${esc(e.title)}</div><div class="evd-line evd-muted">${esc(personName)} · ${esc(when)}</div>${repeat}
    ${e.location ? `<div class="evd-line">${esc(e.location)}</div>` : ''}${e.note ? `<div class="evd-line evd-muted">${esc(e.note)}</div>` : ''}
    ${e.kind === 'reminder' ? '<div class="evd-line evd-muted">Påminnelse</div>' : ''}`;
}

/** Greedy lane assignment so overlapping banners stack instead of covering each other. */
function lanes(spans) {
  const ends = [], out = new Map();
  spans.slice().sort((a, b) => a.date - b.date || b.endDate - a.endDate).forEach((e) => {
    let lane = ends.findIndex((end) => end <= e.date);
    if (lane < 0) { lane = ends.length; ends.push(0); }
    ends[lane] = e.endDate; out.set(e, lane);
  });
  return out;
}

export class Calendar {
  constructor(el, { onDelete } = {}) {
    this.el = el; this.people = []; this.events = []; this.byId = {};
    this.view = 'week'; this.anchor = today0(); this.hidden = new Set(); this.onDelete = onDelete;
    el.addEventListener('click', (e) => e.stopPropagation());
  }
  setPeople(people) { this.people = people; this.byId = Object.fromEntries(people.map((p) => [p.id, p])); }
  setEvents(events) {
    this.events = events.slice().sort((a, b) => a.date - b.date || (b.allDay - a.allDay) || a.start.localeCompare(b.start));
    if (this.isOpen()) this.draw();
  }
  /** Bookings for one person that touch the next `days` days (ongoing banners included). */
  upcoming(pid, days = 7) { const s = today0(), e = addDays(s, days); return this.events.filter((v) => v.person === pid && v.date < e && v.endDate > s); }
  isOpen() { return this.el.classList.contains('open'); }
  open(onlyPid, view) {
    this.hidden = new Set(onlyPid ? this.people.filter((p) => p.id !== onlyPid).map((p) => p.id) : []);
    this.anchor = today0(); if (view) this.view = view; this.draw(); this.el.classList.add('open');
  }
  close() { this.el.classList.remove('open'); }
  color(pid) { return (this.byId[pid] || { color: '#f0b43c' }).color; }
  name(pid) { return (this.byId[pid] || { name: '' }).name; }

  showDetail(ev) {
    let box = this.el.querySelector('.evd');
    if (!box) { box = document.createElement('div'); box.className = 'evd'; this.el.appendChild(box); }
    box.style.setProperty('--pc', this.color(ev.person));
    const buttons = ev.occurrence
      ? '<button class="cbtn" data-evdel="one">Ta bort bara denna gång</button><button class="cbtn" data-evdel="all">Ta bort hela serien</button>'
      : `<button class="cbtn" data-evdel="all">${ev.source === 'reminder' ? 'Ta bort påminnelsen' : 'Ta bort bokningen'}</button>`;
    box.innerHTML = `<button class="cbtn evd-x" data-evx>✕</button>${detailHTML(ev, this.name(ev.person))}<div class="evd-actions">${buttons}</div>`;
    box.classList.add('open');
    box.querySelector('[data-evx]').onclick = () => box.classList.remove('open');
    box.querySelectorAll('[data-evdel]').forEach((del) => del.onclick = () => {
      if (del.dataset.sure) { box.classList.remove('open'); this.onDelete?.(ev, { whole: del.dataset.evdel === 'all' }); }
      else { del.dataset.sure = '1'; del.textContent = 'Klicka igen för att bekräfta'; }
    });
  }

  #card(e, withWho = true) {
    return `<div class="cev" data-ev="${this.events.indexOf(e)}" style="--pc:${this.color(e.person)}">${withWho ? `<span class="who">${esc(this.name(e.person))}</span> ` : ''}${esc(e.short || e.title)}<small>${esc(timeSpan(e))}${e.location ? ' · ' + esc(e.location) : ''}</small></div>`;
  }

  #weekBands(ws, vis) {
    const we = addDays(ws, 7), spans = this.events.filter((e) => e.allDay && vis(e) && e.date < we && e.endDate > ws);
    if (!spans.length) return '';
    const lane = lanes(spans), rows = Math.max(...lane.values()) + 1;
    return `<div class="wbands" style="grid-template-rows:repeat(${rows},24px)">${spans.map((e) => {
      const s = Math.max(0, daysBetween(ws, e.date)), end = Math.min(6, daysBetween(ws, lastDay(e)));
      const cls = `${e.date < ws ? ' cl' : ''}${e.endDate > we ? ' cr' : ''}`;
      return `<div class="band${cls}" data-ev="${this.events.indexOf(e)}" style="grid-column:${s + 1}/${end + 2};grid-row:${lane.get(e) + 1};--pc:${this.color(e.person)}" title="${esc(rangeShort(e))}">${esc(labeled(e.title, this.name(e.person)))}${e.location ? `<small> · ${esc(e.location)}</small>` : ''}</div>`;
    }).join('')}</div>`;
  }

  draw() {
    const vis = (e) => !this.hidden.has(e.person); let range, body;
    if (this.view === 'day') {
      const d = this.anchor, cols = this.people.filter((p) => !this.hidden.has(p.id));
      range = `${sameDay(d, today0()) ? 'Idag · ' : ''}${longDay(d)}`;
      body = `<div class="dayview" style="grid-template-columns:repeat(${Math.max(1, cols.length)},1fr)">${cols.map((p) => {
        const mine = this.events.filter((e) => e.person === p.id && covers(e, d));
        const bands = mine.filter((e) => e.allDay).map((e) => `<div class="dband" data-ev="${this.events.indexOf(e)}">${esc(e.title)}<small>${esc(rangeShort(e))}</small></div>`).join('');
        const cards = mine.filter((e) => !e.allDay).map((e) => this.#card(e, false)).join('');
        return `<div class="dcol" style="--pc:${p.color}"><h5>${esc(p.name)}</h5>${bands}${cards || (bands ? '' : '<div class="dnone">Inget planerat</div>')}</div>`;
      }).join('')}</div>`;
    } else if (this.view === 'week') {
      const ws = weekStart(this.anchor), we = addDays(ws, 6);
      range = `Vecka ${isoWeek(ws)} · ${ws.getDate()} ${MON[ws.getMonth()]} – ${we.getDate()} ${MON[we.getMonth()]}`;
      const days = [0, 1, 2, 3, 4, 5, 6].map((i) => addDays(ws, i));
      body = `<div class="weekwrap"><div class="whead">${days.map((d) => `<h5 class="${sameDay(d, today0()) ? 'today' : ''}" data-day="${d.toISOString()}" data-go="day">${WD[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}</h5>`).join('')}</div>
        ${this.#weekBands(ws, vis)}
        <div class="week">${days.map((d) => {
          const ev = this.events.filter((e) => !e.allDay && sameDay(e.date, d) && vis(e));
          return `<div class="wday${sameDay(d, today0()) ? ' today' : ''}">${ev.map((e) => this.#card(e)).join('')}</div>`;
        }).join('')}</div></div>`;
    } else {
      const first = new Date(this.anchor.getFullYear(), this.anchor.getMonth(), 1), gs = weekStart(first), ge = addDays(gs, 42);
      range = `${MONTHS[first.getMonth()]} ${first.getFullYear()}`;
      const spans = this.events.filter((e) => e.allDay && vis(e) && e.date < ge && e.endDate > gs), lane = lanes(spans);
      body = `<div class="month"><div class="mhead">V</div>${['MÅN', 'TIS', 'ONS', 'TOR', 'FRE', 'LÖR', 'SÖN'].map((h) => `<div class="mhead">${h}</div>`).join('')}${Array.from({ length: 42 }, (_, i) => {
        const d = addDays(gs, i), ev = this.events.filter((e) => !e.allDay && sameDay(e.date, d) && vis(e));
        const here = spans.filter((e) => covers(e, d)), top = here.length ? Math.min(2, Math.max(...here.map((e) => lane.get(e)))) : -1;
        const bars = Array.from({ length: top + 1 }, (_, l) => {
          const e = here.find((x) => lane.get(x) === l);
          if (!e) return '<div class="mbar empty"></div>';
          const start = sameDay(e.date, d), end = sameDay(lastDay(e), d), label = start || i % 7 === 0;
          return `<div class="mbar${start ? ' s' : ''}${end ? ' e' : ''}" data-ev="${this.events.indexOf(e)}" style="--pc:${this.color(e.person)}">${label ? esc(labeled(e.title, this.name(e.person))) : '&nbsp;'}</div>`;
        }).join('');
        return (i % 7 === 0 ? `<div class="wnum" data-day="${d.toISOString()}" data-go="week">${isoWeek(d)}</div>` : '') +
          `<div class="mcell${d.getMonth() !== first.getMonth() ? ' other' : ''}${sameDay(d, today0()) ? ' today' : ''}" data-day="${d.toISOString()}" data-go="day"><b>${d.getDate()}</b>${bars}${ev.slice(0, 3).map((e) =>
            `<div class="mev" style="--pc:${this.color(e.person)}"><i></i>${esc(e.start)} ${esc(e.short || e.title)}</div>`).join('')}${ev.length > 3 ? `<div class="mmore">+${ev.length - 3}</div>` : ''}</div>`;
      }).join('')}</div>`;
    }
    this.el.innerHTML = `<div class="calbar"><h3>URD · KALENDER</h3><div class="nav"><button class="cbtn" data-nav="-1">◀</button><span class="range">${range}</span><button class="cbtn" data-nav="1">▶</button><button class="cbtn" data-today>Idag</button></div>
      <button class="cbtn${this.view === 'day' ? ' on' : ''}" data-view="day">Dag</button><button class="cbtn${this.view === 'week' ? ' on' : ''}" data-view="week">Vecka</button><button class="cbtn${this.view === 'month' ? ' on' : ''}" data-view="month">Månad</button>
      <div class="filters"><span class="fchip all${this.hidden.size ? '' : ' on'}" data-all>Alla</span>${this.people.map((p) => `<span class="fchip${this.hidden.has(p.id) ? ' off' : ''}" data-f="${p.id}" style="--pc:${p.color}">${esc(p.name)}</span>`).join('')}</div>
      <button class="cbtn" data-x>✕</button></div><div class="calbody">${body}</div>`;
    const q = (s) => this.el.querySelectorAll(s);
    q('[data-nav]').forEach((b) => b.onclick = () => {
      const n = +b.dataset.nav;
      if (this.view === 'day') this.anchor = addDays(this.anchor, n);
      else if (this.view === 'week') this.anchor = addDays(this.anchor, 7 * n);
      else this.anchor = new Date(this.anchor.getFullYear(), this.anchor.getMonth() + n, 1);
      this.draw();
    });
    this.el.querySelector('[data-today]').onclick = () => { this.anchor = today0(); this.view = 'day'; this.draw(); };
    q('[data-view]').forEach((b) => b.onclick = () => { this.view = b.dataset.view; this.draw(); });
    this.el.querySelector('[data-all]').onclick = () => { this.hidden.clear(); this.draw(); };
    q('[data-f]').forEach((b) => b.onclick = () => { const id = b.dataset.f; this.hidden.has(id) ? this.hidden.delete(id) : this.hidden.add(id); this.draw(); });
    q('[data-day]').forEach((b) => b.onclick = () => { this.anchor = new Date(b.dataset.day); this.view = b.dataset.go || 'week'; this.draw(); });
    q('[data-ev]').forEach((b) => b.onclick = (e) => { e.stopPropagation(); this.showDetail(this.events[+b.dataset.ev]); });
    this.el.querySelector('[data-x]').onclick = () => this.close();
  }
}
