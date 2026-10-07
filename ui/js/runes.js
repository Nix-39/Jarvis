// Background atmosphere: a slow ring of Elder Futhark runes around the tree,
// occasional runes fading in and out, and drifting golden sparks.
// Runes are drawn as strokes, so no special font is needed.

const GOLD = '240,180,60';
const RUNES = [
  [[.3,0,.3,1],[.3,.35,.75,.1],[.3,.6,.75,.35]], [[.25,1,.25,0],[.25,0,.75,.3],[.75,.3,.75,1]], [[.3,0,.3,1],[.3,.3,.7,.5],[.7,.5,.3,.7]],
  [[.3,0,.3,1],[.3,0,.7,.25],[.3,.3,.7,.55]], [[.3,0,.3,1],[.3,0,.7,.25],[.7,.25,.3,.5],[.3,.5,.75,1]], [[.7,.1,.3,.4],[.3,.4,.7,.7]],
  [[.2,0,.8,1],[.8,0,.2,1]], [[.3,0,.3,1],[.3,0,.7,.2],[.7,.2,.3,.45]], [[.25,0,.25,1],[.75,0,.75,1],[.25,.35,.75,.6]],
  [[.5,0,.5,1],[.3,.35,.7,.6]], [[.5,0,.5,1]], [[.45,.1,.2,.35],[.2,.35,.45,.6],[.55,.4,.8,.65],[.8,.65,.55,.9]],
  [[.5,0,.5,1],[.5,0,.75,.2],[.5,1,.25,.8]], [[.3,0,.3,1],[.3,0,.7,.2],[.3,1,.7,.8],[.7,.8,.7,.7],[.7,.2,.7,.3]], [[.5,0,.5,1],[.5,.4,.2,.05],[.5,.4,.8,.05]],
  [[.7,0,.3,.35],[.3,.35,.7,.65],[.7,.65,.3,1]], [[.5,0,.5,1],[.5,0,.2,.3],[.5,0,.8,.3]],
  [[.3,0,.3,1],[.3,0,.7,.25],[.7,.25,.3,.5],[.3,.5,.7,.75],[.7,.75,.3,1]], [[.25,0,.25,1],[.75,0,.75,1],[.25,0,.5,.35],[.5,.35,.75,0]],
  [[.25,0,.25,1],[.75,0,.75,1],[.25,0,.75,.45],[.75,0,.25,.45]], [[.35,0,.35,1],[.35,0,.7,.3]], [[.5,.2,.8,.5],[.8,.5,.5,.8],[.5,.8,.2,.5],[.2,.5,.5,.2]],
  [[.2,0,.2,1],[.8,0,.8,1],[.2,0,.8,1],[.8,0,.2,1]], [[.5,0,.8,.3],[.8,.3,.5,.6],[.5,.6,.2,.3],[.2,.3,.5,0],[.35,.45,.15,1],[.65,.45,.85,1]],
];

function rune(x, i, px, py, size, rot, alpha) {
  x.save(); x.translate(px, py); x.rotate(rot);
  x.strokeStyle = `rgba(${GOLD},${alpha})`; x.lineWidth = 1.3; x.lineCap = 'round'; x.beginPath();
  for (const [a, b, c, d] of RUNES[i % RUNES.length]) { x.moveTo((a - 0.5) * size * 0.6, (b - 0.5) * size); x.lineTo((c - 0.5) * size * 0.6, (d - 0.5) * size); }
  x.stroke(); x.restore();
}

export class Myth {
  constructor(canvas) {
    this.canvas = canvas; this.geo = null;
    this.drift = Array.from({ length: 14 }, (_, i) => ({ i: (i * 7) % 24, u: Math.random(), v: Math.random(), ph: Math.random() * 6.28, sz: 14 + Math.random() * 16 }));
  }
  resize(w, h, geo) {
    const d = window.devicePixelRatio || 1;
    this.canvas.width = w * d; this.canvas.height = h * d; this.canvas.style.width = w + 'px'; this.canvas.style.height = h + 'px';
    this.ctx = this.canvas.getContext('2d'); this.ctx.scale(d, d); this.w = w; this.h = h; this.geo = geo;
  }
  draw(t, level) {
    const x = this.ctx, g = this.geo; if (!x || !g) return;
    x.clearRect(0, 0, this.w, this.h);
    const R = g.s * 0.58, n = 24, rot = t / 90000;
    for (let k = 0; k < n; k++) {
      const a = k / n * Math.PI * 2 + rot, pulse = 0.06 + 0.05 * Math.max(0, Math.sin(t / 1400 - k * 0.55));
      rune(x, k, g.cx + Math.cos(a) * R, g.cy + Math.sin(a) * R * 0.92, 22, a + Math.PI / 2, pulse + level * 0.04);
    }
    x.strokeStyle = `rgba(${GOLD},.05)`; x.lineWidth = 1;
    for (const r of [R + 18, R - 18]) { x.beginPath(); x.ellipse(g.cx, g.cy, r, r * 0.92, 0, 0, 7); x.stroke(); }
    for (const d of this.drift) {
      const al = 0.035 * Math.max(0, Math.sin(t / 3000 + d.ph)); if (al < 0.004) continue;
      rune(x, d.i, g.midL + d.u * (g.midR - g.midL), 60 + d.v * (this.h - 120), d.sz, 0, al);
    }
  }
}

export class Sparks {
  constructor(canvas) { this.canvas = canvas; this.resize(); addEventListener('resize', () => this.resize()); }
  resize() {
    this.canvas.width = innerWidth; this.canvas.height = innerHeight; this.ctx = this.canvas.getContext('2d');
    this.list = Array.from({ length: 60 }, () => ({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, r: Math.random() * 1.4 + 0.3, v: Math.random() * 0.22 + 0.05, a: Math.random() * 6 }));
  }
  draw() {
    const x = this.ctx; x.clearRect(0, 0, this.canvas.width, this.canvas.height); x.fillStyle = '#f0b43c';
    for (const s of this.list) {
      s.y -= s.v; s.a += 0.012; if (s.y < -5) { s.y = this.canvas.height + 5; s.x = Math.random() * this.canvas.width; }
      x.globalAlpha = 0.18 + 0.3 * Math.abs(Math.sin(s.a)); x.beginPath(); x.arc(s.x, s.y, s.r, 0, 7); x.fill();
    }
    x.globalAlpha = 1;
  }
}
