// Shooting stars: bright heads with tapering tails that arc along a slightly
// curved path, shedding sparkles, and flare like a star where they land.

const NS = 'http://www.w3.org/2000/svg';
const TAIL = 12;                       // tail segments

const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

export class Bolts {
  constructor(guidesGroup, boltsGroup) {
    this.guides = guidesGroup; this.bolts = boltsGroup;
    this.anchors = {}; this.guideEls = {};
    this.onImpact = () => {};
  }

  setAnchors(anchors, guideTargets) {
    this.anchors = anchors; this.guides.innerHTML = ''; this.guideEls = {};
    for (const id of guideTargets) {
      const A = anchors.crown, B = anchors[id]; if (!A || !B) continue;
      const l = el('line', { x1: A.x, y1: A.y, x2: B.x, y2: B.y, class: 'guide' });
      this.guides.appendChild(l); this.guideEls[id] = l;
    }
  }

  fire(fromKey, toKey, count = 3) {
    const from = this.anchors[fromKey], to = this.anchors[toKey]; if (!from || !to) return;
    const dx = to.x - from.x, dy = to.y - from.y, dist = Math.hypot(dx, dy); if (!dist) return;
    const nx = -dy / dist, ny = dx / dist, dur = Math.max(320, dist * 1.05), tail = Math.min(0.55, 120 / dist);
    const g = this.guideEls[toKey] || this.guideEls[fromKey];
    if (g) { g.classList.add('hot'); setTimeout(() => g.classList.remove('hot'), dur + 500); }
    for (let k = 0; k < count; k++) {
      // each star takes its own gentle arc
      const bend = ((k - (count - 1) / 2) * 0.09 + (Math.random() - 0.5) * 0.05) * dist;
      const cx = (from.x + to.x) / 2 + nx * bend, cy = (from.y + to.y) / 2 + ny * bend;
      const at = (q) => { q = Math.max(0, Math.min(1, q)); const u = 1 - q; return [u * u * from.x + 2 * u * q * cx + q * q * to.x, u * u * from.y + 2 * u * q * cy + q * q * to.y]; };
      const grp = el('g', {}), haze = el('polyline', { class: 'star-haze', filter: 'url(#blur)' });
      const segs = Array.from({ length: TAIL }, (_, i) => el('line', { class: 'star-tail', 'stroke-width': (2.8 * (1 - i / TAIL) + 0.3).toFixed(2), opacity: (1 - i / TAIL).toFixed(2) }));
      const halo = el('circle', { r: 7, class: 'star-halo', filter: 'url(#blur)' }), head = el('circle', { r: 2.4, class: 'star-head' });
      grp.append(haze, ...segs, halo, head); grp.style.opacity = 0; this.bolts.appendChild(grp);
      const start = performance.now() + k * 130;
      const step = (t) => {
        const q = (t - start) / dur;
        if (q < 0) return requestAnimationFrame(step);
        grp.style.opacity = 1;
        const pts = Array.from({ length: TAIL + 1 }, (_, i) => at(q - tail * i / TAIL));
        segs.forEach((s, i) => { s.setAttribute('x1', pts[i][0]); s.setAttribute('y1', pts[i][1]); s.setAttribute('x2', pts[i + 1][0]); s.setAttribute('y2', pts[i + 1][1]); });
        haze.setAttribute('points', pts.slice(0, TAIL / 2).map((p) => p.join(',')).join(' '));
        const [hx, hy] = pts[0], show = q <= 1 ? 1 : 0;
        for (const c of [halo, head]) { c.setAttribute('cx', hx); c.setAttribute('cy', hy); c.style.opacity = show; }
        if (q <= 1 && Math.random() < 0.45) this.#sparkle(hx, hy);
        if (q < 1 + tail) requestAnimationFrame(step);
        else { grp.remove(); this.#flare(to.x, to.y, k === count - 1 ? 1 : 0.6); if (k === count - 1) this.onImpact(toKey); }
      };
      requestAnimationFrame(step);
    }
  }

  #sparkle(x, y) {
    const s = el('circle', { cx: x + (Math.random() - 0.5) * 4, cy: y + (Math.random() - 0.5) * 4, r: (0.6 + Math.random() * 0.9).toFixed(2), class: 'star-spark' });
    s.style.setProperty('--sx', `${(Math.random() - 0.5) * 14}px`); s.style.setProperty('--sy', `${(Math.random() - 0.5) * 14}px`);
    s.addEventListener('animationend', () => s.remove()); this.bolts.appendChild(s);
  }

  #flare(x, y, size) {
    const r = 11 * size, w = 1.8 * size;
    const f = el('path', { class: 'star-flare', d: `M${x} ${y - r}L${x + w} ${y - w}L${x + r} ${y}L${x + w} ${y + w}L${x} ${y + r}L${x - w} ${y + w}L${x - r} ${y}L${x - w} ${y - w}Z` });
    f.style.transformOrigin = `${x}px ${y}px`;
    f.addEventListener('animationend', () => f.remove()); this.bolts.appendChild(f);
  }
}
