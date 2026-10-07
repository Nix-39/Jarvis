// Talks to Yggdrasil Core on 127.0.0.1. The bearer token is handed over by the
// desktop app (pywebview bridge) - a page opened in an ordinary browser never
// gets it and cannot use the API.

let token = null;

export async function getToken() {
  if (token) return token;
  const bridge = await waitForBridge(8000);
  if (!bridge) return null;
  token = await window.pywebview.api.get_token();
  return token;
}

function waitForBridge(ms) {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve(true);
    const timer = setTimeout(() => resolve(false), ms);
    window.addEventListener('pywebviewready', () => { clearTimeout(timer); resolve(true); }, { once: true });
  });
}

export async function api(path, { method = 'GET', body, raw, headers = {} } = {}) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, ...headers } };
  if (raw !== undefined) {
    opts.body = raw;
    opts.headers['Content-Type'] = 'application/octet-stream';
  } else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    const err = new Error(detail); err.status = res.status; throw err;
  }
  const type = res.headers.get('content-type') || '';
  if (type.includes('application/json')) return res.json();
  return res.blob();
}

export async function health() {
  try { const r = await fetch('/health', { cache: 'no-store' }); return r.ok ? r.json() : null; }
  catch { return null; }
}

// Live event feed (Server-Sent Events over fetch, so the token can be sent as a header).
export function followEvents(onEvent, onState) {
  let lastId = 0, stopped = false;
  (async function loop() {
    while (!stopped) {
      try {
        // Start from "now" on first connect, and after a core restart (ids begin at 1 again).
        const recent = await api('/events/recent?limit=1');
        const latest = recent.length ? recent[recent.length - 1].id : 0;
        if (lastId === 0 || latest < lastId) lastId = latest;
        const res = await fetch(`/events/stream?after_id=${lastId}`, { headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        onState?.(true);
        const reader = res.body.getReader(), dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
            const line = chunk.split('\n').find((l) => l.startsWith('data: '));
            if (!line) continue;
            try { const ev = JSON.parse(line.slice(6)); lastId = Math.max(lastId, ev.id); onEvent(ev); } catch { /* ignore */ }
          }
        }
      } catch { /* reconnect below */ }
      onState?.(false);
      await new Promise((r) => setTimeout(r, 3000));
    }
  })();
  return () => { stopped = true; };
}

export async function openExternal(url) {
  try { await window.pywebview.api.open_url(url); } catch { /* not in desktop app */ }
}
