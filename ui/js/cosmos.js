// Background atmosphere: a twinkling star field with the odd meteor, a slowly
// turning star-chart ring around Nexus (hour marks like right ascension, a
// scanner sweep that speeds up while the system works) and constellations that
// fade in and out around it.

const PINK = '255,46,196', WHITE = '230,228,235', HOT = '255,255,255';
const TAU = Math.PI * 2;

// [name, stars (0..1), lines between star indexes]
const CONSTELLATIONS = [
  ['Karlavagnen', [[0, .35], [.18, .3], [.33, .36], [.47, .45], [.52, .68], [.8, .72], [.84, .47]], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 3]]],
  ['Kassiopeja', [[0, .3], [.25, .72], [.5, .45], [.75, .78], [1, .25]], [[0, 1], [1, 2], [2, 3], [3, 4]]],
  ['Orion', [[.2, .12], [.76, .2], [.38, .5], [.5, .47], [.62, .44], [.3, .92], [.8, .86], [.48, 0]], [[0, 2], [1, 4], [2, 3], [3, 4], [2, 5], [4, 6], [0, 1], [0, 7], [1, 7]]],
  ['Lyran', [[.2, .04], [.4, .36], [.56, .3], [.64, .86], [.46, .92]], [[0, 1], [0, 2], [1, 2], [1, 4], [2, 3], [3, 4]]],
  ['Svanen', [[.5, 0], [.5, .4], [.5, 1], [.08, .28], [.92, .52]], [[0, 1], [1, 2], [3, 1], [1, 4]]],
];

export class StarChart {
  constructor(canvas) {
    this.canvas = canvas; this.geo = null; this.sweep = 0; this.last = 0;
    this.slots = Array.from({ length: 4 }, (_, i) => ({ start: i * 5000, dur: 0, place: null }));
  }

  resize(w, h, geo) {
    const d = window.devicePixelRatio || 1;
    this.canvas.width = w * d; this.canvas.height = h * d; this.canvas.style.width = w + 'px'; this.canvas.style.height = h + 'px';
    this.ctx = this.canvas.getContext('2d'); this.ctx.scale(d, d); this.w = w; this.h = h; this.geo = geo;
    for (const s of this.slots) s.place = null;
  }

  #place(t) {
    const g = this.geo, R = g.s * 0.55;
    for (let tries = 0; tries < 20; tries++) {
      const size = 90 + Math.random() * 60;
      const x = g.midL + 30 + Math.random() * Math.max(1, g.midR - g.midL - 60 - size), y = 70 + Math.random() * Math.max(1, this.h - 200 - size);
      const far = Math.hypot(x + size / 2 - g.cx, y + size / 2 - g.cy) > R + size * 0.6;
      const free = this.slots.every((s) => !s.place || Math.hypot(s.place.x - x, s.place.y - y) > 170);
      if (far && free) return { x, y, size, c: CONSTELLATIONS[Math.random() * CONSTELLATIONS.length | 0], rot: (Math.random() - 0.5) * 0.6 };
    }
    return null;
  }

  #constellation(x, p, alpha) {
    const [name, stars, lines] = p.c, cos = Math.cos(p.rot), sin = Math.sin(p.rot);
    const pt = ([u, v]) => { const a = (u - 0.5) * p.size, b = (v - 0.5) * p.size; return [p.x + p.size / 2 + a * cos - b * sin, p.y + p.size / 2 + a * sin + b * cos]; };
    x.strokeStyle = `rgba(${WHITE},${alpha * 0.4})`; x.lineWidth = 0.8; x.beginPath();
    for (const [i, j] of lines) { const [a, b] = pt(stars[i]), [c, d] = pt(stars[j]); x.moveTo(a, b); x.lineTo(c, d); }
    x.stroke();
    for (const s of stars) {
      const [a, b] = pt(s);
      x.fillStyle = `rgba(${HOT},${alpha})`; x.beginPath(); x.arc(a, b, 1.6, 0, TAU); x.fill();
      x.fillStyle = `rgba(${PINK},${alpha * 0.25})`; x.beginPath(); x.arc(a, b, 4.5, 0, TAU); x.fill();
    }
    x.fillStyle = `rgba(${WHITE},${alpha * 0.6})`; x.font = '600 9px "Nexus Montserrat", "Segoe UI", sans-serif';
    x.fillText(name.toUpperCase().split('').join(' '), p.x, p.y + p.size + 14);
  }

  draw(t, level) {
    const x = this.ctx, g = this.geo; if (!x || !g) return;
    const dt = Math.min(50, t - (this.last || t)); this.last = t;
    x.clearRect(0, 0, this.w, this.h);
    const R = g.s * 0.55, K = 0.92, rot = t / 140000;
    const at = (a, r) => [g.cx + Math.cos(a) * r, g.cy + Math.sin(a) * r * K];

    // rings
    x.lineWidth = 1;
    for (const [r, al] of [[R + 16, 0.06], [R - 16, 0.05]]) { x.strokeStyle = `rgba(${WHITE},${al * 0.8})`; x.beginPath(); x.ellipse(g.cx, g.cy, r, r * K, 0, 0, TAU); x.stroke(); }
    // tick marks every 5 degrees, longer every 30
    x.beginPath();
    for (let k = 0; k < 72; k++) {
      const a = k / 72 * TAU + rot, big = k % 6 === 0, [x1, y1] = at(a, R - (big ? 9 : 4)), [x2, y2] = at(a, R + (big ? 9 : 4));
      x.moveTo(x1, y1); x.lineTo(x2, y2);
    }
    x.strokeStyle = `rgba(${WHITE},${0.08 + level * 0.06})`; x.stroke();
    // hour labels (right ascension 0h-23h)
    x.font = '500 9px "Nexus Montserrat", Consolas, monospace'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillStyle = `rgba(${WHITE},${0.14 + level * 0.05})`;
    for (let h = 0; h < 24; h += 2) { const [lx, ly] = at(h / 24 * TAU + rot, R + 30); x.fillText(`${h}h`, lx, ly); }
    x.textAlign = 'start'; x.textBaseline = 'alphabetic';
    // counter-rotating arc segments
    x.lineWidth = 2; x.strokeStyle = `rgba(${WHITE},${0.05 + level * 0.08})`;
    for (let k = 0; k < 3; k++) {
      const a0 = k / 3 * TAU - t / 60000; x.beginPath(); x.ellipse(g.cx, g.cy, R - 30, (R - 30) * K, 0, a0, a0 + 0.85); x.stroke();
    }
    // scanner sweep
    this.sweep += dt * (TAU / 14000 + level * TAU / 3500);
    for (let k = 0; k < 10; k++) {
      x.strokeStyle = `rgba(${PINK},${(0.22 + level * 0.25) * (1 - k / 10)})`; x.lineWidth = 2;
      const a1 = this.sweep - k * 0.045; x.beginPath(); x.ellipse(g.cx, g.cy, R, R * K, 0, a1 - 0.045, a1); x.stroke();
    }

    // constellations fading in and out around the ring
    for (const s of this.slots) {
      if (!s.place) { if (t < s.start) continue; s.place = this.#place(t); s.start = t; s.dur = 14000 + Math.random() * 9000; if (!s.place) { s.start = t + 3000; continue; } }
      const q = (t - s.start) / s.dur;
      if (q >= 1) { s.place = null; s.start = t + 2000 + Math.random() * 6000; continue; }
      this.#constellation(x, s.place, 0.22 * Math.sin(Math.PI * q));
    }
  }
}

export class Starfield {
  constructor(canvas) { this.canvas = canvas; this.meteor = null; this.resize(); addEventListener('resize', () => this.resize()); }

  resize() {
    this.canvas.width = innerWidth; this.canvas.height = innerHeight; this.ctx = this.canvas.getContext('2d');
    const n = Math.round(innerWidth * innerHeight / 8500);
    this.list = Array.from({ length: n }, () => {
      const c = Math.random();
      return { x: Math.random() * innerWidth, y: Math.random() * innerHeight, r: 0.3 + Math.pow(Math.random(), 3) * 1.3,
        a: 0.15 + Math.random() * 0.5, tw: 0.0006 + Math.random() * 0.002, ph: Math.random() * TAU,
        rgb: c < 0.94 ? '235,235,240' : c < 0.98 ? '255,150,225' : '255,220,200' };
    });
  }

  draw(t = performance.now()) {
    const x = this.ctx, W = this.canvas.width, H = this.canvas.height;
    x.clearRect(0, 0, W, H);
    for (const s of this.list) {
      s.x -= 0.006 * s.r; if (s.x < -2) s.x = W + 2;
      const al = s.a * (0.6 + 0.4 * Math.sin(t * s.tw + s.ph));
      x.fillStyle = `rgba(${s.rgb},${al})`; x.beginPath(); x.arc(s.x, s.y, s.r, 0, TAU); x.fill();
      if (s.r > 1.1) { x.fillStyle = `rgba(${s.rgb},${al * 0.15})`; x.beginPath(); x.arc(s.x, s.y, s.r * 3.5, 0, TAU); x.fill(); }
    }
    // a meteor now and then (about every 15 seconds)
    if (!this.meteor && Math.random() < 1 / 900) {
      const left = Math.random() < 0.5, a = (left ? 0.55 : Math.PI - 0.55) + (Math.random() - 0.5) * 0.3;
      this.meteor = { x: Math.random() * W, y: Math.random() * H * 0.45, dx: Math.cos(a) * 11, dy: Math.sin(a) * 11, life: 0, max: 38 + Math.random() * 20 };
    }
    const m = this.meteor;
    if (m) {
      m.life++; m.x += m.dx; m.y += m.dy;
      const fade = Math.sin(Math.PI * m.life / m.max), tx = m.x - m.dx * 11, ty = m.y - m.dy * 11;
      const g = x.createLinearGradient(m.x, m.y, tx, ty);
      g.addColorStop(0, `rgba(${HOT},${0.7 * fade})`); g.addColorStop(1, `rgba(${PINK},0)`);
      x.strokeStyle = g; x.lineWidth = 1.3; x.lineCap = 'round'; x.beginPath(); x.moveTo(m.x, m.y); x.lineTo(tx, ty); x.stroke();
      if (m.life >= m.max) this.meteor = null;
    }
  }
}
