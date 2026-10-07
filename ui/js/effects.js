// Blaster bolts: three glowing bolts in a row along a straight neon line.

const NS = 'http://www.w3.org/2000/svg';

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
      const l = document.createElementNS(NS, 'line');
      for (const [k, v] of [['x1', A.x], ['y1', A.y], ['x2', B.x], ['y2', B.y], ['class', 'guide']]) l.setAttribute(k, v);
      this.guides.appendChild(l); this.guideEls[id] = l;
    }
  }

  fire(fromKey, toKey, count = 3) {
    const from = this.anchors[fromKey], to = this.anchors[toKey]; if (!from || !to) return;
    const dx = to.x - from.x, dy = to.y - from.y, dist = Math.hypot(dx, dy); if (!dist) return;
    const ux = dx / dist, uy = dy / dist, len = Math.min(34, dist * 0.25), dur = Math.max(260, dist * 0.9);
    const g = this.guideEls[toKey] || this.guideEls[fromKey];
    if (g) { g.classList.add('hot'); setTimeout(() => g.classList.remove('hot'), dur + 500); }
    for (let k = 0; k < count; k++) {
      const grp = document.createElementNS(NS, 'g'), glow = document.createElementNS(NS, 'line'), beam = document.createElementNS(NS, 'line');
      glow.setAttribute('stroke', 'var(--accent)'); glow.setAttribute('stroke-width', '8'); glow.setAttribute('stroke-linecap', 'round'); glow.setAttribute('filter', 'url(#blur)');
      beam.setAttribute('stroke', '#fff8dc'); beam.setAttribute('stroke-width', '2.6'); beam.setAttribute('stroke-linecap', 'round');
      grp.append(glow, beam); grp.style.opacity = 0; this.bolts.appendChild(grp);
      const start = performance.now() + k * 115;
      const step = (t) => {
        const q = (t - start) / dur;
        if (q < 0) return requestAnimationFrame(step);
        grp.style.opacity = 1;
        const head = Math.min(q, 1) * dist, tail = Math.max(0, head - len);
        for (const el of [glow, beam]) {
          el.setAttribute('x1', from.x + ux * tail); el.setAttribute('y1', from.y + uy * tail);
          el.setAttribute('x2', from.x + ux * head); el.setAttribute('y2', from.y + uy * head);
        }
        if (q < 1 + len / dist) requestAnimationFrame(step);
        else { grp.remove(); if (k === count - 1) this.onImpact(toKey); }
      };
      requestAnimationFrame(step);
    }
  }
}
