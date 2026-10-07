// Yggdrasil - the world tree that visualises the brain.
// Swappable module: it only draws, and reports where the crown, root and the
// three wells are so the rest of the UI can aim effects at them.

const GOLD = '240,180,60', HOT = '255,243,207';
export const S = 440;                 // internal drawing size (scaled to the canvas)
const C = S / 2;
export const WELLS = [                // left, middle, right root
  { id: 'mimer', name: 'Mimer', role: 'Minne' },
  { id: 'urd', name: 'Urd', role: 'Kalender' },
  { id: 'hvergelmer', name: 'Hvergelmer', role: 'Säkerhet' },
];

function rng(seed) { return () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; }

export function glow(x, px, py, r, a) {
  const g = x.createRadialGradient(px, py, 0, px, py, r);
  g.addColorStop(0, `rgba(${HOT},${a})`); g.addColorStop(1, `rgba(${GOLD},0)`);
  x.fillStyle = g; x.beginPath(); x.arc(px, py, r, 0, 7); x.fill();
}

export class Tree {
  constructor(canvas) {
    this.canvas = canvas;
    this.level = 0; this.busy = false;
    this.wellLevel = Object.fromEntries(WELLS.map((w) => [w.id, 0]));
    this.segs = []; this.starts = []; this.pulses = []; this.tips = []; this.wellPos = []; this.strands = [];
    this.cache = null;
    this.#grow();
  }

  #seg(x, y, x2, y2, w, parent, bend = 0) {
    const mx = (x + x2) / 2, my = (y + y2) / 2;
    const s = { x, y, x2, y2, cx: mx - (y2 - y) * bend, cy: my + (x2 - x) * bend, w, kids: [] };
    const i = this.segs.push(s) - 1; if (parent != null) this.segs[parent].kids.push(i); return i;
  }

  #branch(R, x, y, ang, len, w, depth, parent, o) {
    if (depth === 0 || len < 3) return;
    const a = ang + (R() - 0.5) * o.jitter, x2 = x + Math.cos(a) * len, y2 = y + Math.sin(a) * len;
    const i = this.#seg(x, y, x2, y2, w, parent, (R() - 0.5) * o.bend);
    const n = depth > o.forkDepth ? o.forks : 2;
    for (let k = 0; k < n; k++) {
      this.#branch(R, x2, y2, a + (k - (n - 1) / 2) * o.spread * (n === 2 ? 1 : 0.75),
        len * (o.lenF[0] + R() * (o.lenF[1] - o.lenF[0])), Math.max(0.5, w * o.wF), depth - 1, i, o);
    }
    if (!this.segs[i].kids.length) this.tips.push(i);
  }

  #grow() {
    const R = rng(29);
    for (let k = 0; k < 7; k++) this.strands.push(k * 2 * Math.PI / 7);
    const top = this.#seg(C, C + 60, C, C - 30, 4, null); this.segs[top].hidden = true; this.starts.push(top);
    for (const a of [-2.9, -2.5, -2.1, -1.75, -1.39, -1.05, -0.65, -0.25]) {
      this.#branch(R, C + Math.cos(a) * 8, C - 30, a, 45, 7, 7, top,
        { jitter: 0.3, bend: 0.3, forks: 3, forkDepth: 5, spread: 0.48, lenF: [0.66, 0.78], wF: 0.6 });
    }
    const bottom = this.#seg(C, C - 30, C, C + 62, 4, null); this.segs[bottom].hidden = true; this.starts.push(bottom);
    for (const [a, len] of [[2.45, 62], [1.57, 56], [0.7, 62]]) {
      let x = C, y = C + 62, ang = a, par = bottom, w = 12;
      for (let k = 0; k < 5; k++) {
        const x2 = x + Math.cos(ang) * len * 0.32, y2 = y + Math.sin(ang) * len * 0.32;
        par = this.#seg(x, y, x2, y2, w, par, (R() - 0.5) * 0.5);
        if (k > 0) this.#branch(R, x2, y2, ang + (R() < 0.5 ? -1 : 1) * 0.8, len * 0.28, w * 0.4, 3, par,
          { jitter: 0.4, bend: 0.4, forks: 2, forkDepth: 9, spread: 0.6, lenF: [0.6, 0.75], wF: 0.6 });
        x = x2; y = y2; w *= 0.78; ang += (1.57 - ang) * -0.08;
      }
      this.wellPos.push([x, y]);
    }
  }

  resize(px) {
    const d = window.devicePixelRatio || 1;
    this.canvas.width = S * d; this.canvas.height = S * d;
    this.canvas.style.width = this.canvas.style.height = px + 'px';
    this.ctx = this.canvas.getContext('2d'); this.ctx.scale(d, d);
    this.cache = null;
  }

  // Points in internal coordinates (0..S); the caller maps them to the page.
  anchors() {
    const a = { crown: [C, C - 40], root: [C, C + 60] };
    WELLS.forEach((w, i) => { a[w.id] = this.wellPos[i]; });
    return a;
  }

  pulseWell(id) { if (id in this.wellLevel) this.wellLevel[id] = 1; }
  burst() { this.level = Math.min(1, this.level + 0.4); }

  #buildCache() {
    const d = window.devicePixelRatio || 1, c = document.createElement('canvas');
    c.width = S * d; c.height = S * d; const x = c.getContext('2d'); x.scale(d, d);
    x.shadowColor = `rgba(${GOLD},.9)`; x.shadowBlur = 7; x.lineCap = 'round';
    for (const s of this.segs) {
      if (s.hidden) continue;
      x.strokeStyle = `rgba(${GOLD},${Math.min(1, 0.35 + s.w * 0.05)})`; x.lineWidth = s.w;
      x.beginPath(); x.moveTo(s.x, s.y); x.quadraticCurveTo(s.cx, s.cy, s.x2, s.y2); x.stroke();
    }
    this.cache = c;
  }

  draw(t) {
    const x = this.ctx; if (!x) return;
    x.clearRect(0, 0, S, S);
    this.level += ((this.busy ? 1 : 0) - this.level) * 0.05;
    const L = this.level;
    glow(x, C, C + 15, 150, 0.09 + L * 0.12);
    // twisted trunk strands (cheap glow: wide faint stroke + thin bright stroke)
    x.save(); x.lineCap = 'round';
    for (const [lw, al] of [[7, 0.18], [3.2, 0.85]]) for (const ph of this.strands) {
      x.strokeStyle = `rgba(${GOLD},${al})`; x.lineWidth = lw; x.beginPath();
      for (let yy = C + 64; yy >= C - 32; yy -= 3) {
        const k = (C + 64 - yy) / 96, amp = 12 - 6 * k, xx = C + Math.sin(yy * 0.07 + ph + t / 2500) * amp;
        yy === C + 64 ? x.moveTo(xx, yy) : x.lineTo(xx, yy);
      }
      x.stroke();
    }
    x.restore();
    if (!this.cache) this.#buildCache();
    x.drawImage(this.cache, 0, 0, S, S);
    // energy pulses travelling out to the tips
    if (Math.random() < 0.06 + L * 0.45) this.pulses.push({ i: this.starts[Math.random() * 2 | 0], t: 0 });
    for (let k = this.pulses.length - 1; k >= 0; k--) {
      const q = this.pulses[k], s = this.segs[q.i]; q.t += 0.045 + L * 0.05;
      if (q.t >= 1) {
        if (!s.kids.length) { this.pulses.splice(k, 1); glow(x, s.x2, s.y2, 10, 0.9); continue; }
        q.i = s.kids[Math.random() * s.kids.length | 0]; q.t = 0; continue;
      }
      const u = 1 - q.t;
      glow(x, u * u * s.x + 2 * u * q.t * s.cx + q.t * q.t * s.x2, u * u * s.y + 2 * u * q.t * s.cy + q.t * q.t * s.y2, 6, 0.95);
    }
    for (let k = 0; k < 3 + L * 8; k++) {
      const s = this.segs[this.tips[Math.random() * this.tips.length | 0]];
      if (s) glow(x, s.x2, s.y2, 4 + Math.random() * 4, 0.5 + Math.random() * 0.4);
    }
    // the three wells
    WELLS.forEach((w, i) => {
      const [wx, wy] = this.wellPos[i]; this.wellLevel[w.id] *= 0.97; const v = this.wellLevel[w.id];
      glow(x, wx, wy, 16 + Math.sin(t / 500 + i) * 3 + v * 16, 0.8 + v * 0.2);
      x.strokeStyle = `rgba(${GOLD},${0.55 + v * 0.4})`; x.lineWidth = 1 + v;
      x.beginPath(); x.ellipse(wx, wy, 15 + v * 4, 6 + v * 1.5, 0, 0, 7); x.stroke();
    });
    glow(x, C, C + 15, 26 + L * 10, 0.5 + L * 0.3);
  }
}
