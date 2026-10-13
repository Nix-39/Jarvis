"""
SpeechService - talk to Nexus and hear her answer. Everything runs locally.

Listening (speech-to-text):
    - faster-whisper with KBLab's Swedish Whisper models (KB-Whisper, about half
      the error rate of OpenAI's Whisper on Swedish). The large model runs on the
      GPU when CUDA works (checked in a separate process first, so a broken CUDA
      setup can never crash the core) and falls back to a smaller model on the CPU.
    - Ways to start talking:
        * "Hej Nexus ..." (or just "Nexus, ...") - the wake phrase follows the
          orchestrator name in the settings. The microphone listens all the time (when switched on),
          a simple energy detector cuts out speech, and a small model on the CPU
          checks only the first seconds of each piece for the wake phrase. Audio
          is kept in memory only and thrown away after the check.
        * the microphone button in Yggdrasil or the voice hotkey (push to talk).
        * after Nexus has answered, she listens a few seconds for a follow-up
          ("ja", "nej", "flytta till 16") without the wake phrase.
    - Telegram voice messages are transcribed the same way.

Speaking (text-to-speech):
    - Piper (offline neural TTS) with a Swedish voice: Lisa (default), Alma or NST
      (male). Slightly calmer settings than Piper's defaults, short pauses between
      sentences and soft edges give cleaner speech.
    - Plays through the computer's speakers from the core, so Nexus can speak even
      when the window is hidden. Volume, mute and quiet hours come from the
      interface's sound settings; long answers are cut after a few sentences.

Models are downloaded once into models/ (not part of git or the backup).
"""

from __future__ import annotations

import functools
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from core.config import BASE_DIR, Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

SAMPLE_RATE = 16000
FRAME = 480                                   # 30 ms
MODELS_DIR = BASE_DIR / "models"
VOICE_DIR = MODELS_DIR / "piper"
WHISPER_DIR = MODELS_DIR / "whisper"
VOICES = {"alma": "sv_SE-alma-medium", "lisa": "sv_SE-lisa-medium", "nst": "sv_SE-nst-medium"}
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/sv/sv_SE/{name}/medium/{file}"
WAKE_SECONDS = 2.6                            # how much of each speech piece the wake check looks at
FOLLOW_UP_SECONDS = 6.0                       # listen for a follow-up after an answer
ARM_SECONDS = 8.0                             # push to talk: wait this long for speech to start
MAX_SPOKEN_CHARS = 420
SENTENCE_PAUSE = 0.14                         # seconds of silence between sentences
NOISE_SCALE, NOISE_W = 0.6, 0.7               # a little calmer than Piper's defaults (0.667 / 0.8)
GREETING = r"(?:hej|hey|hallå|halla|hejsan|tjena|okej|ok)"
# How Whisper tends to write the names. "loose" only counts after a greeting ("Hej Lexus" = Hej Nexus),
# "strict" also works on its own at the start ("Nexus, vad är klockan?"). The name itself is always strict.
NAME_VARIANTS = {
    "nexus": {"strict": ("nexus", "nexxus", "neksus", "nexsus"), "loose": ("nexis", "nexes", "nexos", "nexius", "lexus", "next us", "nex us")},
    "oden": {"strict": (), "loose": ("odin", "åden", "öden", "uden", "odden")},
}
HALLUCINATIONS = ("tack för att du tittade", "textning", "undertexter", "prenumerera", "www.", "svensktextning")


class SpeechError(Exception):
    pass


# ----------------------------------------------------------------------
# Text cleaning for speech
# ----------------------------------------------------------------------

def speakable(text: str, limit: int = MAX_SPOKEN_CHARS) -> tuple[str, bool]:
    """Turn a chat answer into something pleasant to listen to. Returns (text, was_cut)."""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    t = re.sub(r"https?://\S+", "länken", t)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\b0(\d):(\d{2})\b", r"\1:\2", t)                    # 09:00 -> 9:00
    t = re.sub(r"\b(\d{1,2}):00\b", r"\1", t)                      # 15:00 -> 15
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", r"\1 \2", t)              # 13:15 -> 13 15
    t = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 till \2", t)
    for a, b in (("°", " grader"), ("m/s", " meter per sekund"), (" mm", " millimeter"), ("kl.", "klockan"),
                 ("t.ex.", "till exempel"), ("bl.a.", "bland annat"), ("ca ", "cirka "), ("&", " och "), (" · ", ", ")):
        t = t.replace(a, b)
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk", "Cs"))   # emoji and symbols
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .") + "."
    t = re.sub(r"\.{2,}", ".", t)
    if len(t) <= limit:
        return t, False
    cut = max(t.rfind(". ", 0, limit), t.rfind("? ", 0, limit), t.rfind("! ", 0, limit))
    return (t[: cut + 1] if cut > limit // 3 else t[:limit].rsplit(" ", 1)[0] + ".") + " Resten står i chatten.", True


@functools.lru_cache(maxsize=8)
def wake_re(name: str = "Nexus") -> re.Pattern:
    """The wake phrase for an orchestrator name: "Hej Nexus", and for names of 5+ letters also just "Nexus,"."""
    key = (name or "Nexus").strip().lower()
    variants = NAME_VARIANTS.get(key, {})
    alt = lambda words: "|".join(re.escape(w).replace("\\ ", " ").replace(" ", r"\s*") for w in sorted(set(words), key=len, reverse=True))
    strict, loose = alt((key, *variants.get("strict", ()))), alt((key, *variants.get("strict", ()), *variants.get("loose", ())))
    alone = f"|(?:{strict})" if len(key) >= 5 else ""
    return re.compile(rf"^\W*(?:{GREETING}\W+(?:{loose}){alone})\b\W*", re.IGNORECASE)


def strip_wake(text: str, name: str = "Nexus") -> str:
    return wake_re(name).sub("", text or "", count=1).strip()


def _clean_transcript(text: str) -> str:
    t = " ".join((text or "").split())
    return "" if not t or any(h in t.lower() for h in HALLUCINATIONS) else t


# ----------------------------------------------------------------------
# Speech detection (energy based, adaptive noise floor)
# ----------------------------------------------------------------------

class Segmenter:
    """Cuts a stream of 30 ms frames into pieces of speech."""

    def __init__(self) -> None:
        self.floor = 0.004
        self.reset()

    def reset(self) -> None:
        self.last = 0.0                           # level of the latest frame (for diagnostics)
        self.pre: deque = deque(maxlen=12)        # 360 ms before speech starts
        self.buf: list = []
        self.in_speech = False
        self.loud = 0
        self.quiet = 0
        self.voiced = 0

    def push(self, frame):
        import numpy as np

        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        self.last = rms
        level = Config.VOICE_MIC_LEVEL
        start_at, stop_at = max(self.floor * 3.0, level), max(self.floor * 2.0, level * 0.7)
        if not self.in_speech:
            self.pre.append(frame)
            if rms > start_at:
                self.loud += 1
            else:
                self.loud = 0
                self.floor = min(0.05, max(0.0008, 0.97 * self.floor + 0.03 * rms))
            if self.loud >= 3:
                self.in_speech, self.buf, self.quiet = True, list(self.pre), 0
            return None
        self.buf.append(frame)
        self.quiet = self.quiet + 1 if rms < stop_at else 0
        self.voiced += rms >= stop_at
        if self.quiet >= 36 or len(self.buf) >= 500:            # 1.1 s of silence (room for a short pause), or 15 s
            audio, voiced = np.concatenate(self.buf), self.voiced
            self.reset()
            return audio if voiced >= 10 else None              # ignore clicks and knocks (< 0.3 s of sound)
        return None


def chime(volume: float):
    """A short, soft two-tone 'I'm listening' sound."""
    import numpy as np

    t = np.linspace(0, 0.12, int(SAMPLE_RATE * 0.12), endpoint=False)
    tone = np.concatenate([np.sin(2 * np.pi * 660 * t), np.sin(2 * np.pi * 880 * t)])
    envelope = np.minimum(1, np.minimum(np.arange(tone.size), tone.size - np.arange(tone.size)) / 400)
    return (tone * envelope * 0.25 * volume).astype("float32")


# ----------------------------------------------------------------------
# CUDA helpers (Windows: cuBLAS/cuDNN come from the nvidia-* pip packages)
# ----------------------------------------------------------------------

def add_cuda_dll_dirs() -> None:
    if os.name != "nt":
        return
    import site

    for base in [Path(p) for p in site.getsitepackages()] + [Path(sys.prefix) / "Lib" / "site-packages"]:
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_runtime/bin"):
            folder = base / sub
            if folder.is_dir():
                try:
                    os.add_dll_directory(str(folder))
                except OSError:
                    pass
                if str(folder) not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")


def cuda_works() -> bool:
    """Try the GPU model in a separate process - a broken CUDA setup must not crash the core."""
    marker = WHISPER_DIR / "cuda_check.json"
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
        if cached.get("model") == Config.VOICE_STT_MODEL:
            return bool(cached.get("ok"))
    except (OSError, ValueError):
        pass
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    try:
        result = subprocess.run([sys.executable, "-m", "services.speech_service", "--probe-cuda"], cwd=str(BASE_DIR),
                                capture_output=True, timeout=1800, creationflags=flags)
        ok = result.returncode == 0
        if not ok:
            logger.warning("CUDA speech check failed - using the CPU model. %s", result.stderr.decode(errors="replace")[-300:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("CUDA speech check could not run: %s", exc)
        ok = False
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"model": Config.VOICE_STT_MODEL, "ok": ok}), encoding="utf-8")
    return ok


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

class SpeechService:
    def __init__(
        self,
        settings_provider: Callable[[], dict[str, Any]],
        on_command: Callable[[str], Any],
    ) -> None:
        """
        :param settings_provider: returns the UI settings as a dict (uses "voice" and "sound").
        :param on_command: called (in a worker thread) with what the user said to the assistant.
        """
        self.settings_provider = settings_provider
        self.on_command = on_command
        self.state = "off"
        self.error: Optional[str] = None
        self.device = ""
        self.device_name = "standardmikrofonen"
        self.audio_ok = True
        self._stt = None
        self._wake = None
        self._voice = None
        self._voice_name = ""
        self._model_lock = threading.Lock()
        self._armed_until = 0.0
        self._deaf_until = 0.0
        self._push_to_talk = False                 # armed by the mic button/hotkey (not a follow-up)
        self._peak = 0.0                           # loudest frame while armed
        self._segments: queue.Queue = queue.Queue(maxsize=3)
        self._speech: queue.Queue = queue.Queue(maxsize=8)
        self._stop_playback = threading.Event()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _voice_settings(self) -> dict[str, Any]:
        return (self.settings_provider() or {}).get("voice") or {}

    def _name(self) -> str:
        return str((self.settings_provider() or {}).get("orchestrator_name") or "Nexus")

    def _prompt(self) -> str:
        """Words Whisper should expect: the assistant's and the family's names and common commands.
        Without them it hears names it does not know as ordinary words ("Neo" -> "nio")."""
        settings = self.settings_provider() or {}
        names = [str(p.get("name", "")) for p in settings.get("people") or [] if p.get("name")]
        family = f" {', '.join(names[:-1])} och {names[-1]}." if len(names) > 1 else (f" {names[0]}." if names else "")
        return (f"Hej {self._name()}.{family} Lägg in i kalendern, påminn mig, lär dig, "
                f"BVC, match, träning, favoritlag, resultaten.")

    def _volume(self) -> float:
        sound = (self.settings_provider() or {}).get("sound") or {}
        if sound.get("master_mute") or (sound.get("muted") or {}).get("voice"):
            return 0.0
        return max(0, min(100, int((sound.get("levels") or {}).get("voice", 80)))) / 100

    def _quiet_now(self) -> bool:
        v = self._voice_settings()
        start, end = v.get("quiet_from", "22:00"), v.get("quiet_to", "07:00")
        now = datetime.now().strftime("%H:%M")
        return (start <= now or now < end) if start > end else (start <= now < end)

    def wake_enabled(self) -> bool:
        return bool(self._voice_settings().get("wake_word", True))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def listen(self, seconds: float = ARM_SECONDS) -> None:
        """Push to talk: the next piece of speech is a command (no wake phrase needed)."""
        if not self.audio_ok:
            raise SpeechError(self.error or "Mikrofonen är inte tillgänglig.")
        self._stop_playback.set()                      # talking over the assistant stops her
        self._armed_until = time.monotonic() + seconds
        self._push_to_talk, self._peak = True, 0.0
        self._set_state("listening")
        try:
            self._play(chime(max(self._volume(), 0.3)), SAMPLE_RATE, interruptible=False)
        except Exception as exc:
            logger.debug("Chime failed: %s", exc)
        self._deaf_until = time.monotonic() + 0.3          # don't take the chime for speech

    def cancel(self) -> None:
        self._armed_until = 0.0
        self._stop_playback.set()
        with self._speech.mutex:
            self._speech.queue.clear()
        self._set_state("idle")

    def say(self, text: str, reason: str = "reply") -> None:
        """
        Queue text to be spoken. reason: "reply_voice" (answer to something said -
        always spoken unless muted), "reply" (answer to typed text) or "announce"
        (reminders etc.) - the last two respect the setting and quiet hours.
        """
        mode = self._voice_settings().get("speak", "always")
        if reason not in ("reply_voice", "test"):
            if self._quiet_now() or (mode == "voice") or (mode == "important" and reason != "announce"):
                return
        if self._volume() <= 0:
            return
        spoken, _ = speakable(text)
        if len(spoken) < 2:
            return
        try:
            self._speech.put_nowait((spoken, reason))
        except queue.Full:
            logger.warning("Speech queue full - dropping an answer.")

    def transcribe_bytes(self, data: bytes) -> str:
        """Transcribe an audio file (e.g. a Telegram voice message, OGG/Opus)."""
        model = self._load_stt()
        segments, _ = model.transcribe(io.BytesIO(data), language="sv", beam_size=5, vad_filter=True,
                                       condition_on_previous_text=False, initial_prompt=self._prompt())
        return _clean_transcript(" ".join(s.text for s in segments))

    def status(self) -> dict[str, Any]:
        return {"enabled": Config.VOICE_ENABLED, "state": self.state, "wake_word": self.wake_enabled(),
                "device": self.device, "microphone": self.device_name, "error": self.error, "voice": self._voice_settings().get("voice", "lisa"), "name": self._name()}

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def run_forever(self, stop: threading.Event) -> None:
        """Microphone loop + worker + speaker threads. Started by Jarvis Core."""
        if not Config.VOICE_ENABLED:
            return
        threading.Thread(target=self._speaker_loop, args=(stop,), name="jarvis-voice-out", daemon=True).start()
        threading.Thread(target=self._worker_loop, args=(stop,), name="jarvis-voice-work", daemon=True).start()
        threading.Thread(target=self._preload, args=(stop,), name="jarvis-voice-load", daemon=True).start()
        self._set_state("idle")
        try:
            import numpy as np
            import sounddevice as sd
        except (ImportError, OSError) as exc:   # OSError: no PortAudio / audio system
            self.audio_ok = False
            self._fail(f"Ljudsystemet kunde inte startas ({exc}). Kör pip install -r requirements.txt.")
            return
        segmenter = Segmenter()
        while not stop.is_set():
            if not (self.wake_enabled() or self._armed()):
                stop.wait(0.3)
                continue
            try:
                device = input_device()
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME,
                                    device=device) as stream:
                    self.error = None
                    self.device_name = microphone_name(device)
                    logger.info("Microphone open: %s (start level %.4f).", self.device_name, Config.VOICE_MIC_LEVEL)
                    while not stop.is_set() and (self.wake_enabled() or self._armed()):
                        block, _ = stream.read(FRAME)
                        if self.state == "listening" and not self._armed() and not segmenter.in_speech:
                            if self._push_to_talk:
                                self._nothing_heard()
                            self._set_state("idle")
                        if self.state in ("speaking", "thinking") or time.monotonic() < self._deaf_until:
                            segmenter.reset()
                            continue
                        audio = segmenter.push(np.asarray(block[:, 0], dtype="float32"))
                        if self._armed():
                            self._peak = max(self._peak, segmenter.last)
                        if audio is not None:
                            command = self._armed()
                            if command:
                                self._armed_until, self._push_to_talk = 0.0, False
                            try:
                                self._segments.put_nowait((audio, command))
                            except queue.Full:
                                pass
            except Exception as exc:
                self._fail(f"Mikrofonen gick inte att använda: {exc}")
                stop.wait(15)

    def _worker_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                audio, command = self._segments.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_segment(audio, command)
            except Exception as exc:
                logger.exception("Voice handling failed: %s", exc)
                self._fail("Något gick fel med taligenkänningen.")
                self._set_state("idle")

    def _handle_segment(self, audio, command: bool) -> None:
        if command:
            self._set_state("thinking")
            text = self._transcribe(audio, self._load_stt(), beam=5, prompt=self._prompt())
            if text:
                self._run_command(text)
            else:
                logger.info("Speech piece of %.1f s gave no words.", len(audio) / SAMPLE_RATE)
                event_bus.publish("voice.error", "voice", "Jag hörde ljud men uppfattade inga ord – prova igen, lite närmare mikrofonen.")
                self._set_state("idle")
            return
        # Wake mode: check only the beginning of the piece with the small CPU model.
        name = self._name()
        head = self._transcribe(audio[: int(WAKE_SECONDS * SAMPLE_RATE)], self._load_wake(), beam=1, prompt=f"Hej {name}.")
        if not wake_re(name).match(head):
            logger.debug("No wake phrase in a %.1f s speech piece (%d characters heard).", len(audio) / SAMPLE_RATE, len(head))
            return
        logger.info("Wake phrase heard.")
        event_bus.publish("voice.wake", "voice", f"Hej {name}")
        if len(audio) > (WAKE_SECONDS + 0.4) * SAMPLE_RATE:
            self._set_state("thinking")
            rest = strip_wake(self._transcribe(audio, self._load_stt(), beam=5, prompt=self._prompt()), name)
            if len(rest.split()) >= 2:
                self._run_command(rest)
                return
        self.listen()

    def _run_command(self, text: str) -> None:
        logger.info("Voice command received (%d characters).", len(text))
        event_bus.publish("voice.heard", "voice", text[:300])
        self._set_state("thinking")
        try:
            self.on_command(text)          # Jarvis Core answers and calls say(..., "reply_voice")
        finally:
            if self.state == "thinking":
                self._set_state("idle")

    def _speaker_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                text, reason = self._speech.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                audio, rate = self._synthesize(text)
                self._set_state("speaking")
                event_bus.publish("voice.speaking", "voice", text[:200])
                self._play(audio, rate)
            except Exception as exc:
                logger.warning("Speaking failed: %s", exc)
                self._fail(f"{self._name()} kunde inte prata just nu.")
            finally:
                self._deaf_until = time.monotonic() + 0.4      # don't hear our own echo
                if self._speech.empty():
                    if reason == "reply_voice":
                        self._armed_until = time.monotonic() + FOLLOW_UP_SECONDS   # follow-up without wake phrase
                        self._set_state("listening")
                    else:
                        self._set_state("idle")

    def _preload(self, stop: threading.Event) -> None:
        if stop.wait(45):
            return
        try:
            self._load_voice()
            if self.wake_enabled():
                self._load_wake()
            self._load_stt()
            logger.info("Voice models ready (%s).", self.device)
        except Exception as exc:
            logger.warning("Voice model preload failed: %s", exc)
            self._fail(f"Röstmodellerna kunde inte laddas: {exc}")

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    def _load_stt(self):
        add_cuda_dll_dirs()
        with self._model_lock:
            if self._stt is None:
                from faster_whisper import WhisperModel

                WHISPER_DIR.mkdir(parents=True, exist_ok=True)
                if Config.VOICE_DEVICE in ("auto", "cuda") and cuda_works():
                    self._stt = WhisperModel(Config.VOICE_STT_MODEL, device="cuda", compute_type="int8_float16",
                                             download_root=str(WHISPER_DIR))
                    self.device = "GPU"
                else:
                    self._stt = WhisperModel(Config.VOICE_STT_CPU_MODEL, device="cpu", compute_type="int8",
                                             cpu_threads=max(2, (os.cpu_count() or 4) // 2), download_root=str(WHISPER_DIR))
                    self.device = "CPU"
            return self._stt

    def _load_wake(self):
        with self._model_lock:
            if self._wake is None:
                from faster_whisper import WhisperModel

                self._wake = WhisperModel(Config.VOICE_WAKE_MODEL, device="cpu", compute_type="int8", cpu_threads=2,
                                          download_root=str(WHISPER_DIR))
            return self._wake

    def _load_voice(self):
        name = self._voice_settings().get("voice", "lisa")
        name = name if name in VOICES else "lisa"
        with self._model_lock:
            if self._voice is None or self._voice_name != name:
                from piper import PiperVoice

                model = VOICE_DIR / f"{VOICES[name]}.onnx"
                if not model.exists():
                    _download_voice(name)
                self._voice, self._voice_name = PiperVoice.load(str(model)), name
            return self._voice

    @staticmethod
    def _transcribe(audio, model, beam: int, prompt: str = "") -> str:
        segments, _ = model.transcribe(audio, language="sv", beam_size=beam, vad_filter=False, without_timestamps=True,
                                       condition_on_previous_text=False, initial_prompt=prompt or None)
        parts = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return _clean_transcript(" ".join(parts))

    def _synthesize(self, text: str):
        import numpy as np
        from piper import SynthesisConfig

        voice = self._load_voice()
        rate = float(self._voice_settings().get("rate", 1.0) or 1.0)
        length = 1.0 / max(0.6, min(1.6, rate))
        try:
            config = SynthesisConfig(length_scale=length, noise_scale=NOISE_SCALE, noise_w_scale=NOISE_W, volume=1.0)
        except TypeError:                                  # older piper-tts without these fields
            config = SynthesisConfig(length_scale=length, volume=1.0)
        chunks, sample_rate = [], 22050
        for chunk in voice.synthesize(text, syn_config=config):      # one chunk per sentence
            sample_rate = chunk.sample_rate
            part = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16).astype("float32") / 32768.0
            if chunks:
                chunks.append(np.zeros(int(sample_rate * SENTENCE_PAUSE), dtype="float32"))
            chunks.append(part)
        if not chunks:
            return np.zeros(1, dtype="float32"), sample_rate
        audio = np.concatenate(chunks)
        fade = min(len(audio) // 2, int(sample_rate * 0.008))       # soft edges, no clicks
        if fade:
            ramp = np.linspace(0.0, 1.0, fade, dtype="float32")
            audio[:fade] *= ramp
            audio[-fade:] *= ramp[::-1]
        return audio * self._volume(), sample_rate

    def _play(self, audio, rate: int, interruptible: bool = True) -> None:
        import sounddevice as sd

        if interruptible:
            self._stop_playback.clear()
        block = int(rate * 0.1)
        with sd.OutputStream(samplerate=rate, channels=1, dtype="float32") as out:
            for start in range(0, len(audio), block):
                if interruptible and self._stop_playback.is_set():
                    break
                out.write(audio[start:start + block].reshape(-1, 1))

    # ------------------------------------------------------------------

    def _armed(self) -> bool:
        return time.monotonic() < self._armed_until

    def _nothing_heard(self) -> None:
        """Push to talk ended without speech: tell the user why, with the level the microphone reached."""
        self._push_to_talk = False
        level = Config.VOICE_MIC_LEVEL
        logger.info("Push to talk: no speech (loudest %.4f, start level %.4f, microphone %s).", self._peak, level, self.device_name)
        if self._peak < level:
            hint = (f"Mikrofonen ({self.device_name}) var för tyst ({self._peak:.3f}, behöver {level:.3f}). "
                    "Höj mikrofonvolymen i Windows, välj en annan mikrofon med VOICE_INPUT_DEVICE eller sänk VOICE_MIC_LEVEL.")
        else:
            hint = "Jag hörde ljud men inget som lät som tal. Prova igen och börja prata direkt efter pipet."
        event_bus.publish("voice.error", "voice", f"Hörde inget. {hint}")

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            event_bus.publish("voice.state", "voice", state, state=state)

    def _fail(self, message: str) -> None:
        if message != self.error:
            self.error = message
            logger.warning(message)
            event_bus.publish("voice.error", "voice", message)


def input_device():
    """VOICE_INPUT_DEVICE as sounddevice wants it: a number, part of a name, or None (Windows default)."""
    value = Config.VOICE_INPUT_DEVICE
    return int(value) if value.isdigit() else (value or None)


def microphone_name(device) -> str:
    try:
        import sounddevice as sd

        info = sd.query_devices(device if device is not None else sd.default.device[0], "input")
        return str(info.get("name", "okänd mikrofon"))
    except Exception:
        return "okänd mikrofon"


def mic_test(seconds: float = 6.0) -> int:
    """Record a few seconds, show the levels and what was heard - for finding microphone problems."""
    import numpy as np
    import sounddevice as sd

    device = input_device()
    print(f"Mikrofon: {microphone_name(device)}   (VOICE_INPUT_DEVICE={Config.VOICE_INPUT_DEVICE or 'standard'})")
    print(f"Säg till exempel \"Hej Nexus, vad är klockan?\" - spelar in {seconds:.0f} sekunder ...")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device)
    sd.wait()
    audio = audio[:, 0]
    frames = audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)
    levels = np.sqrt(np.mean(frames * frames, axis=1))
    for i in range(0, len(levels), 17):                                  # about every half second
        part = levels[i:i + 17]
        print(f"  {i * FRAME / SAMPLE_RATE:4.1f} s  {'#' * int(min(60, part.max() * 600)):<60} {part.max():.4f}")
    quiet, loud = float(np.percentile(levels, 20)), float(levels.max())
    print(f"Tyst bakgrund ca {quiet:.4f}, högsta nivå {loud:.4f}, startnivå VOICE_MIC_LEVEL={Config.VOICE_MIC_LEVEL:.4f}")
    segmenter = Segmenter()
    pieces = [p for p in (segmenter.push(f) for f in frames) if p is not None]
    if loud < Config.VOICE_MIC_LEVEL:
        print(f"=> För tyst. Höj mikrofonvolymen i Windows eller sätt VOICE_MIC_LEVEL={max(0.002, loud * 0.5):.3f} i .env.")
    elif not pieces and not segmenter.in_speech:
        print("=> Ljud men inget tal upptäcktes (för kort?). Prata minst en sekund.")
    else:
        print(f"=> Tal upptäcktes ({len(pieces) or 1} bit/ar). Skriver ut vad som hördes ...")
    service = SpeechService(lambda: {}, on_command=print)
    text = service._transcribe(audio, service._load_stt(), beam=5, prompt="Hej Nexus.")
    print(f"Hörde: {text!r}")
    print(f"Väckningsord hittat: {'ja' if wake_re('Nexus').match(text) else 'nej'}")
    return 0


def _download_voice(name: str) -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    stem = VOICES[name]
    for file in (f"{stem}.onnx.json", f"{stem}.onnx"):
        url = VOICE_URL.format(name=name, file=file)
        target = VOICE_DIR / file
        tmp = target.with_suffix(target.suffix + ".part")
        logger.info("Downloading Piper voice %s ...", file)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)
        tmp.replace(target)


# ----------------------------------------------------------------------
# CLI:  python -m services.speech_service --mic-test | --devices | --say "text" | --probe-cuda
# ----------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if "--probe-cuda" in argv:
        import numpy as np

        add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        model = WhisperModel(Config.VOICE_STT_MODEL, device="cuda", compute_type="int8_float16", download_root=str(WHISPER_DIR))
        segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype="float32"), language="sv", beam_size=1)
        list(segments)
        return 0
    service = SpeechService(lambda: {"voice": {"voice": os.getenv("VOICE", "lisa")}, "sound": {}}, on_command=print)
    if "--say" in argv:
        text = argv[argv.index("--say") + 1] if len(argv) > argv.index("--say") + 1 else "Hej, jag är Nexus."
        audio, rate = service._synthesize(speakable(text)[0])
        service._play(audio, rate)
        return 0
    if "--devices" in argv:
        import sounddevice as sd

        print(sd.query_devices())
        print(f"Standardmikrofon: {microphone_name(None)}  - välj en annan med VOICE_INPUT_DEVICE=<nummer> i .env")
        return 0
    if "--mic-test" in argv:
        return mic_test()
    print("Användning: python -m services.speech_service --mic-test | --devices | --say \"text\" | --probe-cuda")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
