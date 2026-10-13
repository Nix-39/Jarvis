// Nexus - the AI core at the centre of the interface: a star with a tilted
// spiral disc, two orbit rings and three planets (the wells Mimer, Urd and
// Hvergelmer). Swappable module: it only draws, and reports where the core and
// the planets are so the rest of the UI can aim effects at them.

export const S = 440;                 // internal drawing size (scaled to the canvas)
const C = S / 2;
export const CORE_Y = C - 34;         // the core sits a little above the middle
const TAU = Math.PI * 2, TILT = 0.3;  // the disc is seen from slightly above
const PINK = '255,46,196', SILVER = '215,212,222', HOT = '255,255,255', ROSE = '255,96,150';
export const WELLS = [                // left, middle, right planet
  { id: 'mimer', name: 'Mimer', role: 'Minne', pos: [C - 165, C + 112], tint: SILVER },
  { id: 'urd', name: 'Urd', role: 'Kalender', pos: [C, C + 150], tint: PINK },
  { id: 'hvergelmer', name: 'Hvergelmer', role: 'Säkerhet', pos: [C + 165, C + 112], tint: ROSE },
];

function rng(seed) { return () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; }
const mix = (a, b, q) => a.split(',').map((v, i) => Math.round(+v + (b.split(',')[i] - v) * q)).join(',');

export function glow(x, px, py, r, a, color = PINK) {
  const g = x.createRadialGradient(px, py, 0, px, py, r);
  g.addColorStop(0, `rgba(${HOT},${a})`); g.addColorStop(0.35, `rgba(${color},${a * 0.45})`); g.addColorStop(1, `rgba(${color},0)`);
  x.fillStyle = g; x.beginPath(); x.arc(px, py, r, 0, TAU); x.fill();
}

export class Nexus {
  constructor(canvas) {
    this.canvas = canvas;
    this.level = 0; this.busy = false; this.spin = 0; this.last = 0;
    this.wellLevel = Object.fromEntries(WELLS.map((w) => [w.id, 0]));
    this.pulses = [];
    const R = rng(41);
    // Two spiral arms of stars; the whole disc turns slowly (faster while working).
    this.dust = Array.from({ length: 280 }, (_, i) => {
      const r = 24 + Math.pow(R(), 0.75) * 122, q = (r - 24) / 122;
      const a = (i % 2) * Math.PI + 2.3 * Math.log(r / 24) + (R() + R() + R() - 1.5) * 0.45;
      return { r, a, s: 0.7 + R() * (1.5 - q * 0.6), b: 0.35 + R() * 0.65, wob: R() * TAU,
        rgb: q < 0.3 ? mix(HOT, PINK, q / 0.3) : mix(PINK, SILVER, (q - 0.3) / 0.7) };
    });
  }

  resize(px) {
    const d = window.devicePixelRatio || 1;
    this.canvas.width = S * d; this.canvas.height = S * d;
    this.canvas.style.width = this.canvas.style.height = px + 'px';
    this.ctx = this.canvas.getContext('2d'); this.ctx.scale(d, d);
  }

  // Points in internal coordinates (0..S); the caller maps them to the page.
  anchors() {
    const a = { crown: [C, CORE_Y - 20], root: [C, CORE_Y + 20] };
    for (const w of WELLS) a[w.id] = w.pos;
    return a;
  }

  pulseWell(id) {
    const i = WELLS.findIndex((w) => w.id === id); if (i < 0) return;
    this.wellLevel[id] = 1;
    for (let k = 0; k < 3; k++) this.pulses.push({ i, q: -k * 0.18 });
  }
  burst() { this.level = Math.min(1, this.level + 0.4); }

  #path(i) {                           // curve from the core down to planet i
    const [px, py] = WELLS[i].pos, x0 = C, y0 = CORE_Y + 16;
    return { x0, y0, cx: (x0 + px) / 2 + (px - x0) * -0.15, cy: (y0 + py) / 2 + 18, x1: px, y1: py - 18 };
  }

  #dust(x, front, L) {
    for (const p of this.dust) {
      const a = p.a + this.spin, sin = Math.sin(a);
      if ((sin >= 0) !== front) continue;
      const r = p.r + Math.sin(this.last / 1800 + p.wob) * 1.2;
      const al = Math.min(1, p.b * (front ? 1.1 : 0.75) * (0.75 + L * 0.35));
      x.fillStyle = `rgba(${p.rgb},${al})`;
      x.fillRect(C + Math.cos(a) * r - p.s / 2, CORE_Y + sin * r * TILT - p.s / 2, p.s, p.s);
    }
  }

  draw(t) {
    const x = this.ctx; if (!x) return;
    const dt = Math.min(50, t - (this.last || t)); this.last = t;
    x.clearRect(0, 0, S, S);
    this.level += ((this.busy ? 1 : 0) - this.level) * 0.05;
    const L = this.level;
    this.spin += dt * (0.000045 + L * 0.00028);

    // halo and the faint plane of the disc
    glow(x, C, CORE_Y, 130, 0.05 + L * 0.08);
    x.save(); x.translate(C, CORE_Y); x.scale(1, TILT);
    const disc = x.createRadialGradient(0, 0, 10, 0, 0, 150);
    disc.addColorStop(0, `rgba(${PINK},${0.16 + L * 0.1})`); disc.addColorStop(1, `rgba(${PINK},0)`);
    x.fillStyle = disc; x.beginPath(); x.arc(0, 0, 150, 0, TAU); x.fill(); x.restore();

    // orbit rings with a small moon each
    x.save(); x.lineWidth = 0.8;
    for (const [rx, ry, rot, sp, dash] of [[172, 42, -0.16, 9000, [2, 6]], [150, 58, 0.3, -6500, []]]) {
      const ang = rot + Math.sin(t / 11000) * 0.03;
      x.setLineDash(dash); x.strokeStyle = `rgba(${SILVER},${0.08 + L * 0.08})`;
      x.beginPath(); x.ellipse(C, CORE_Y, rx, ry, ang, 0, TAU); x.stroke();
      const m = t / sp, mx = Math.cos(m) * rx, my = Math.sin(m) * ry;
      glow(x, C + mx * Math.cos(ang) - my * Math.sin(ang), CORE_Y + mx * Math.sin(ang) + my * Math.cos(ang), 5, 0.75);
    }
    x.restore();

    // lines down to the planets, with data pulses travelling along them
    x.save(); x.setLineDash([1, 6]); x.lineWidth = 1;
    WELLS.forEach((w, i) => {
      const p = this.#path(i), v = this.wellLevel[w.id];
      x.strokeStyle = `rgba(${w.tint},${0.12 + v * 0.4})`;
      x.beginPath(); x.moveTo(p.x0, p.y0); x.quadraticCurveTo(p.cx, p.cy, p.x1, p.y1); x.stroke();
    });
    x.restore();
    if (Math.random() < 0.01 + L * 0.06) this.pulses.push({ i: Math.random() * WELLS.length | 0, q: 0 });
    for (let k = this.pulses.length - 1; k >= 0; k--) {
      const pu = this.pulses[k]; pu.q += 0.022 + L * 0.015;
      if (pu.q >= 1) { this.pulses.splice(k, 1); continue; }
      if (pu.q < 0) continue;
      const p = this.#path(pu.i), q = pu.q, u = 1 - q;
      glow(x, u * u * p.x0 + 2 * u * q * p.cx + q * q * p.x1, u * u * p.y0 + 2 * u * q * p.cy + q * q * p.y1, 5, 0.9, WELLS[pu.i].tint);
    }

    // the disc behind the core, the core, then the disc in front of it
    this.#dust(x, false, L);
    const cr = 12 + L * 3 + Math.sin(t / 600) * 0.8;
    x.save(); x.lineCap = 'round';
    for (let i = 0; i < 12; i++) {                     // corona
      const a = i / 12 * TAU + t / 24000, len = 24 + 9 * Math.sin(t / 700 + i * 1.7) + L * 14;
      const g = x.createLinearGradient(C, CORE_Y, C + Math.cos(a) * len, CORE_Y + Math.sin(a) * len);
      g.addColorStop(0, `rgba(${HOT},${0.35 + L * 0.2})`); g.addColorStop(1, `rgba(${PINK},0)`);
      x.strokeStyle = g; x.lineWidth = 1.4; x.beginPath(); x.moveTo(C, CORE_Y); x.lineTo(C + Math.cos(a) * len, CORE_Y + Math.sin(a) * len); x.stroke();
    }
    x.restore();
    for (const [w, h] of [[120 + L * 40, 1.3], [1.3, 72 + L * 24]]) {   // lens flare cross
      const g = w > h ? x.createLinearGradient(C - w, 0, C + w, 0) : x.createLinearGradient(0, CORE_Y - h, 0, CORE_Y + h);
      g.addColorStop(0, `rgba(${PINK},0)`); g.addColorStop(0.5, `rgba(${HOT},${0.55 + L * 0.3})`); g.addColorStop(1, `rgba(${PINK},0)`);
      x.fillStyle = g; x.fillRect(C - w, CORE_Y - h, w * 2, h * 2);
    }
    glow(x, C, CORE_Y, cr * 3.2, 0.55 + L * 0.3);
    const core = x.createRadialGradient(C, CORE_Y, 0, C, CORE_Y, cr);
    core.addColorStop(0, '#fff'); core.addColorStop(0.45, `rgba(${HOT},.95)`); core.addColorStop(1, `rgba(${PINK},0)`);
    x.fillStyle = core; x.beginPath(); x.arc(C, CORE_Y, cr, 0, TAU); x.fill();
    this.#dust(x, true, L);
    for (let k = 0; k < 2 + L * 9; k++) {             // stars in the disc flaring up
      const p = this.dust[Math.random() * this.dust.length | 0], a = p.a + this.spin;
      glow(x, C + Math.cos(a) * p.r, CORE_Y + Math.sin(a) * p.r * TILT, 3 + Math.random() * 4, 0.6);
    }

    // the planets
    WELLS.forEach((w, i) => {
      const [px, py] = w.pos; this.wellLevel[w.id] *= 0.97; const v = this.wellLevel[w.id];
      const r = 14 + v * 2, ux = (C - px) / Math.hypot(C - px, CORE_Y - py), uy = (CORE_Y - py) / Math.hypot(C - px, CORE_Y - py);
      glow(x, px, py, 30 + Math.sin(t / 500 + i) * 3 + v * 18, 0.28 + v * 0.5, w.tint);
      const ring = (front) => {
        x.strokeStyle = `rgba(${w.tint},${0.55 + v * 0.4})`; x.lineWidth = 1 + v;
        x.beginPath(); x.ellipse(px, py, 27 + v * 5, 7.5 + v * 1.5, -0.22, front ? 0 : Math.PI, front ? Math.PI : TAU); x.stroke();
      };
      const moon = () => { const a = t / 2600; return [px + Math.cos(a) * 30, py + Math.sin(a) * 10, Math.sin(a) > 0]; };
      if (w.id === 'mimer') ring(false);
      if (w.id === 'urd') { const [mx, my, front] = moon(); if (!front) glow(x, mx, my, 5.5, 0.7, w.tint); }
      const body = x.createRadialGradient(px + ux * r * 0.45, py + uy * r * 0.45, 0, px, py, r * 1.25);
      body.addColorStop(0, `rgba(${HOT},.95)`); body.addColorStop(0.35, `rgba(${w.tint},.9)`); body.addColorStop(1, 'rgba(10,3,14,.95)');
      x.fillStyle = body; x.beginPath(); x.arc(px, py, r, 0, TAU); x.fill();
      if (w.id === 'mimer') ring(true);
      if (w.id === 'urd') { const [mx, my, front] = moon(); if (front) glow(x, mx, my, 5.5, 0.85, w.tint); }
      if (w.id === 'hvergelmer') {                       // shield
        x.strokeStyle = `rgba(${w.tint},${0.35 + v * 0.5})`; x.lineWidth = 1 + v; x.beginPath();
        for (let k = 0; k <= 6; k++) { const a = k / 6 * TAU + t / 9000, rr = 25 + v * 5; k ? x.lineTo(px + Math.cos(a) * rr, py + Math.sin(a) * rr) : x.moveTo(px + Math.cos(a) * rr, py + Math.sin(a) * rr); }
        x.stroke();
      }
    });
  }
}
