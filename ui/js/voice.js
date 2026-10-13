// Voice controls: the microphone button in the chat field, the assistant's listening /
// speaking state, and the voice settings in the sound menu. The microphone and
// speakers are handled by the core (SpeechService) - this module only controls it.

import { api } from './api.js';
import { esc } from './calendar.js';

const $ = (id) => document.getElementById(id);
const MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6"/></svg>';
const VOICES = [['lisa', 'Lisa'], ['alma', 'Alma'], ['nst', 'NST (mansröst)']];
const MODES = [['always', 'Alla svar'], ['voice', 'Bara när jag pratar'], ['important', 'Bara viktiga saker']];
const STATE_TEXT = { listening: 'Lyssnar…', thinking: 'Tänker…', speaking: 'Pratar – klicka för att tysta' };

export class VoiceControl {
  constructor({ getSettings, saveSettings, setStatus, sys }) {
    Object.assign(this, { getSettings, saveSettings, setStatus, sys });
    this.state = 'off'; this.enabled = false;
    const form = $('ask');
    form.classList.add('with-mic');
    this.btn = Object.assign(document.createElement('button'), { type: 'button', id: 'micBtn', innerHTML: MIC, hidden: true });
    form.appendChild(this.btn);
    this.btn.onclick = (e) => { e.preventDefault(); this.toggle(); };
  }

  async init() {
    try {
      const s = await api('/voice/status');
      this.enabled = !!s.enabled; this.btn.hidden = !this.enabled; this.mic = s.microphone || '';
      this.setState(s.state || 'idle'); this.renderSettings();
      if (s.error) this.sys(`🎙 ${s.error}`);
    } catch { this.btn.hidden = true; }
  }

  async toggle() {
    try {
      if (this.state === 'listening' || this.state === 'speaking') await api('/voice/stop', { method: 'POST' });
      else await api('/voice/listen', { method: 'POST' });
    } catch (err) { this.sys(`🎙 ${err.message}`); }
  }

  setState(state) {
    this.state = state;
    this.btn.className = state;
    const hotkey = 'Ctrl+Alt+Space', name = this.name();
    this.btn.title = state === 'listening' ? 'Lyssnar… (klicka för att avbryta)' : state === 'speaking' ? `Tysta ${name}` : `Prata med ${name} (${hotkey}${this.getSettings()?.voice?.wake_word ? ` eller säg "Hej ${name}"` : ''})`;
    this.setStatus(STATE_TEXT[state] ? `🎙 ${STATE_TEXT[state]}` : null, state);
  }

  name() { return this.getSettings()?.orchestrator_name || 'Nexus'; }

  onEvent(ev) {
    const d = ev.data || {};
    if (ev.type === 'voice.state') this.setState(d.state || ev.message);
    else if (ev.type === 'voice.error') this.sys(`🎙 ${ev.message}`);
  }

  /** Voice section in the sound menu. */
  renderSettings() {
    const pop = $('soundPop'); if (!pop || !this.enabled) return;
    let box = $('voiceSettings');
    if (!box) { box = Object.assign(document.createElement('div'), { id: 'voiceSettings' }); pop.appendChild(box); }
    const v = this.getSettings()?.voice || {};
    box.innerHTML = `<h4>RÖST</h4>
      <label class="master"><span>Lyssna efter "Hej ${esc(this.name())}"<small>Mikrofonen är på – inget sparas eller lämnar datorn</small></span><input type="checkbox" id="wakeWord" ${v.wake_word ? 'checked' : ''}><i></i></label>
      <div class="vrow"><span>Röst</span><select id="voiceName">${VOICES.map(([k, n]) => `<option value="${k}" ${v.voice === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select><button class="cbtn" id="voiceTest">Testa</button></div>
      <div class="vrow"><span>Läs upp</span><select id="voiceMode">${MODES.map(([k, n]) => `<option value="${k}" ${v.speak === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
      <div class="vrow"><span>Tempo</span><input type="range" id="voiceRate" min="0.7" max="1.4" step="0.05" value="${v.rate ?? 1}"><span class="v">${Math.round((v.rate ?? 1) * 100)}%</span></div>
      <div class="vrow"><span>Tyst tid</span><input type="time" id="quietFrom" value="${esc(v.quiet_from || '22:00')}"><input type="time" id="quietTo" value="${esc(v.quiet_to || '07:00')}"></div>
      <small class="vnote">Under tyst tid läses svar bara upp när du själv har pratat.</small>
      ${this.mic ? `<small class="vnote">Mikrofon: ${esc(this.mic)}</small>` : ''}`;
    const save = (patch) => this.saveSettings({ voice: { ...(this.getSettings()?.voice || {}), ...patch } });
    $('wakeWord').onchange = (e) => save({ wake_word: e.target.checked });
    $('voiceName').onchange = (e) => save({ voice: e.target.value });
    $('voiceMode').onchange = (e) => save({ speak: e.target.value });
    $('voiceRate').oninput = (e) => { e.target.nextElementSibling.textContent = `${Math.round(e.target.value * 100)}%`; };
    $('voiceRate').onchange = (e) => save({ rate: +e.target.value });
    $('quietFrom').onchange = (e) => save({ quiet_from: e.target.value });
    $('quietTo').onchange = (e) => save({ quiet_to: e.target.value });
    $('voiceTest').onclick = async (e) => { e.stopPropagation(); try { await api('/voice/test', { method: 'POST' }); } catch (err) { this.sys(`🎙 ${err.message}`); } };
  }
}
