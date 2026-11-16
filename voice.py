"""Voice incantations: listen for spell names using Windows' built-in offline speech recognition.

Recognition runs entirely on this PC through the .NET `System.Speech` engine, driven from a PowerShell child
process (no extra Python packages, no audio files, nothing leaves the machine). The engine is given a closed
grammar of spell names, so it only ever answers with one of them or nothing.
"""
import base64
import json
import os
import re
import subprocess
import threading
from typing import Callable, Dict, Iterable, Optional

from spells_data import SPELLS, pretty

# Other ways people say (or the recogniser may need to be told how to say) common spells. Each alternative maps
# to the same spell. These are best guesses, so they are kept short and easy to extend.
ALTERNATES: Dict[str, list] = {
    "lumos": ["Loo mos"],
    "nox": ["Knocks"],
    "expelliarmus": ["Expelly armus", "Ex pell ee are mus"],
    "alohomora": ["Ah low ha mora"],
    "wingardium_leviosa": ["Win gar dee um Levi oh sa"],
    "protego": ["Pro tay go"],
    "expecto_patronum": ["Expecto Patron um"],
    "accio": ["Ack see oh"],
    "stupefy": ["Stew pe fie"],
    "riddikulus": ["Ridiculous"],
    "reparo": ["Reh par oh"],
    "incendio": ["In sen dee oh"],
    "aguamenti": ["Agua menti"],
    "petrificus_totalus": ["Pet rif icus Toe tall us"],
}

_SAFE = re.compile(r"[^A-Za-z ]+")


def clean_phrase(p: str) -> str:
    """Only letters and spaces are ever sent to the recogniser (also keeps the script free of injection)."""
    return re.sub(r"\s+", " ", _SAFE.sub(" ", p)).strip()


def phrase_map(keys: Iterable[str], alternates: Optional[Dict[str, list]] = None) -> Dict[str, str]:
    """{spoken phrase: spell key} for the given spells, including alternative pronunciations."""
    alternates = ALTERNATES if alternates is None else alternates
    out: Dict[str, str] = {}
    for k in keys:
        for p in [pretty(k)] + list(alternates.get(k, [])):
            c = clean_phrase(p)
            if c and c.lower() not in {x.lower() for x in out}:
                out[c] = k
    return out


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Speech
  $phrases = @'
__PHRASES__
'@ | ConvertFrom-Json
  $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
  $choices = New-Object System.Speech.Recognition.Choices
  foreach ($p in $phrases) { [void]$choices.Add([string]$p) }
  $gb = New-Object System.Speech.Recognition.GrammarBuilder
  $gb.Append($choices)
  $rec.LoadGrammar((New-Object System.Speech.Recognition.Grammar $gb))
  if ($env:MCC_VOICE_WAV) { $rec.SetInputToWaveFile($env:MCC_VOICE_WAV) } else { $rec.SetInputToDefaultAudioDevice() }
  Register-ObjectEvent -InputObject $rec -EventName SpeechRecognized -SourceIdentifier mccheard | Out-Null
  [Console]::Out.WriteLine('READY'); [Console]::Out.Flush()
  $rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
  $parent = [int]$env:MCC_PARENT_PID
  while ($true) {
    $e = Wait-Event -SourceIdentifier mccheard -Timeout 1
    if ($e) {
      $r = $e.SourceEventArgs.Result
      [Console]::Out.WriteLine('HEARD' + [char]9 + $r.Text + [char]9 + [math]::Round($r.Confidence, 3))
      [Console]::Out.Flush()
      Remove-Event -EventIdentifier $e.EventIdentifier
    }
    if ($parent -gt 0 -and -not (Get-Process -Id $parent -ErrorAction SilentlyContinue)) { break }
  }
  $rec.RecognizeAsyncCancel(); $rec.Dispose()
} catch {
  [Console]::Out.WriteLine('ERROR' + [char]9 + $_.Exception.Message); [Console]::Out.Flush(); exit 1
}
"""


def build_script(phrases: Iterable[str]) -> str:
    clean = [c for c in (clean_phrase(p) for p in phrases) if c]
    return SCRIPT.replace("__PHRASES__", json.dumps(clean))


def encode_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def parse_line(line: str):
    """-> ('ready',) | ('heard', phrase, confidence) | ('error', message) | None"""
    parts = line.rstrip("\r\n").split("\t")
    tag = parts[0].strip()
    if tag == "READY":
        return ("ready",)
    if tag == "HEARD" and len(parts) >= 3:
        try:
            return ("heard", parts[1].strip(), float(parts[2]))
        except ValueError:
            return None
    if tag == "ERROR":
        return ("error", " ".join(parts[1:]).strip() or "unknown error")
    return None


def friendly_error(msg: str) -> str:
    low = msg.lower()
    if "access" in low and ("denied" in low or "audio" in low) or "microphone" in low:
        return ("Windows is not letting this app use the microphone. Open Settings > Privacy & security > "
                "Microphone and allow desktop apps.")
    if "no audio" in low or "default audio" in low or "input device" in low:
        return "No microphone was found. Plug one in or choose a default recording device in Windows."
    if "recognizer" in low or "culture" in low or "speech" in low and "install" in low:
        return "Windows speech recognition (English) is not installed on this PC."
    return msg


def available() -> bool:
    """True if this PC has an English desktop speech recogniser installed."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             "([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers().Count)"],
            capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip().isdigit() and int(r.stdout.strip()) > 0
    except (OSError, subprocess.SubprocessError):
        return False


class VoiceListener:
    """Runs the recogniser and reports what it hears.

    on_heard(spell_key, phrase, confidence) and on_state(state, detail) are called from a background thread;
    states are 'starting', 'listening', 'error' and 'stopped'.
    """

    def __init__(self, phrases: Dict[str, str], on_heard: Callable, on_state: Callable, wav: Optional[str] = None):
        self.phrases = dict(phrases)
        self.on_heard, self.on_state, self.wav = on_heard, on_state, wav
        self.proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running:
            return
        self._stopping = False
        env = dict(os.environ, MCC_PARENT_PID=str(os.getpid()))
        if self.wav:
            env["MCC_VOICE_WAV"] = self.wav
        else:
            env.pop("MCC_VOICE_WAV", None)
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
               encode_command(build_script(self.phrases))]
        self.on_state("starting", "")
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                         env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.on_state("error", f"Could not start speech recognition: {e}")
            return
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        proc = self.proc
        by_lower = {p.lower(): k for p, k in self.phrases.items()}
        got_error = False
        for raw in iter(proc.stdout.readline, b""):
            ev = parse_line(raw.decode("utf-8", "replace"))
            if not ev:
                continue
            if ev[0] == "ready":
                self.on_state("listening", "")
            elif ev[0] == "heard":
                key = by_lower.get(ev[1].lower())
                if key:
                    self.on_heard(key, ev[1], ev[2])
            elif ev[0] == "error":
                got_error = True
                self.on_state("error", friendly_error(ev[1]))
        if not got_error and not self._stopping:
            self.on_state("stopped", "")

    def stop(self):
        self._stopping = True
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
        self.on_state("stopped", "")
