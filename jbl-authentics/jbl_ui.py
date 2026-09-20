#!/usr/bin/env python3
"""
jbl_ui.py - a small local web UI for the JBL Authentics L8 / L16.

    python3 jbl_ui.py                      # serves http://127.0.0.1:8765 and opens it
    python3 jbl_ui.py --host 192.168.1.50  # connect to the speaker straight away
    python3 jbl_ui.py --port 9000 --no-browser

Standard library only; needs jbl_authentics.py in the same folder.
The page talks to this script over localhost, and this script talks to the
speaker over TCP 10025 with one persistent connection and a heartbeat.
Everything sent and received is shown in the page's log, so this doubles as
the tool for verifying the protocol on real hardware.
"""
import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbl_authentics as ja  # noqa: E402

STATUS_FIELDS = ("power", "volume", "source", "bass_level", "signal_doctor",
                 "device_name", "sys_version")


class NotConnected(Exception):
    pass


class Session:
    """One speaker connection shared by all HTTP requests, guarded by a lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.spk = None
        self.target = ""
        self.log = []
        self.log_id = 0
        self.last_error = ""
        threading.Thread(target=self._housekeeping, daemon=True).start()

    # -- log ------------------------------------------------------------------
    def _log(self, direction, text):
        self.log_id += 1
        self.log.append({"id": self.log_id, "t": time.strftime("%H:%M:%S"),
                         "d": direction, "m": text})
        if len(self.log) > 400:
            del self.log[:len(self.log) - 400]

    def _absorb(self, msgs):
        for m in msgs:
            if m["name"] == "heart-alive":
                continue
            self._log("<", f"{m['name']}  zone={m['zone']!r}  para={m['para']!r}")

    def _flush_pending(self):
        if self.spk is not None and self.spk.pending:
            self._absorb(self.spk.pending)
            self.spk.pending.clear()

    # -- connection -----------------------------------------------------------
    def connect(self, target):
        host, _, port = target.strip().partition(":")
        if not host:
            raise ValueError("no speaker address given")
        port = int(port) if port else ja.PORT
        with self.lock:
            self.disconnect()
            self.spk = ja.Authentics(host, port, timeout=3.0)
            self.target = target.strip()
            self.last_error = ""
            self._log("*", f"connected to {host}:{port}")
            self.spk.heartbeat()

    def disconnect(self):
        with self.lock:
            if self.spk is not None:
                self.spk.close()
                self.spk = None
                self._log("*", "disconnected")

    def _drop(self, exc):
        self.last_error = str(exc)
        self._log("!", f"connection lost: {exc}")
        if self.spk is not None:
            self.spk.close()
            self.spk = None

    def _housekeeping(self):
        """Heartbeat every 10 s and pick up unsolicited messages for the log."""
        while True:
            time.sleep(1.0)
            with self.lock:
                if self.spk is None:
                    continue
                try:
                    self.spk.maybe_heartbeat()
                    self._absorb(self.spk.drain(0.05))
                    self._flush_pending()
                except (OSError, ConnectionError) as exc:
                    self._drop(exc)

    # -- commands -------------------------------------------------------------
    def send(self, name, para="", element="control", zone="Main Zone",
             wait=None, timeout=2.5, settle=0.4):
        """Send one command. With `wait`, return the status of that name (or None);
        without it, return whatever arrived within `settle` seconds."""
        with self.lock:
            if self.spk is None:
                raise NotConnected("not connected to a speaker")
            try:
                self.spk.send(name, para, zone, element)
                suffix = "" if element == "control" else f"  [{element}]"
                self._log(">", f"{name}  para={para!r}{suffix}")
                if wait is None:
                    msgs = self.spk.drain(settle)
                    self._absorb(msgs)
                    self._flush_pending()
                    return msgs
                m = self.spk.wait_for(wait, timeout)
                if m is not None:
                    self._absorb([m])
                self._flush_pending()
                return m
            except (OSError, ConnectionError) as exc:
                self._drop(exc)
                raise

    def query(self, what, timeout=2.5):
        return self.send("query-status", what, wait=what, timeout=timeout)

    def status(self):
        out = {}
        for what in STATUS_FIELDS:
            m = self.query(what, 2.0)
            out[what] = None if m is None else m["para"]
            time.sleep(0.15)
        out["tone"] = ja.parse_bass_level(out["bass_level"]) if out.get("bass_level") else None
        return out

    def state(self):
        return {"connected": self.spk is not None, "target": self.target,
                "error": self.last_error, "log": self.log[-150:]}


SESSION = Session()


def _para(m):
    return None if m is None else m["para"]


def run_action(body):
    a = body.get("action")
    if a == "power":
        state = "on" if body.get("state") == "on" else "off"
        if body.get("alt"):
            m = SESSION.send("power", state, element="status", wait="power")
        else:
            m = SESSION.send("power-on" if state == "on" else "power-off", wait="power")
        return {"power": _para(m)}
    if a == "source":
        SESSION.send("source-selection", ja.SOURCES[body["name"]])
        return {"source": _para(SESSION.query("source"))}
    if a == "volume":
        if "step" in body:
            SESSION.send("volume-up" if body["step"] == "up" else "volume-down")
        else:
            SESSION.send("set_system_volume", str(max(0, min(39, int(body["value"])))))
        return {"volume": _para(SESSION.query("volume"))}
    if a == "tone":
        if body.get("off"):
            SESSION.send("set_manual_mode", "off")
        else:
            for name, key in (("set_bass_level", "bass"), ("set_mid_level", "mid"),
                              ("set_high_level", "high")):
                SESSION.send(name, str(max(0, min(10, int(body[key])))), settle=0.15)
        m = SESSION.query("bass_level")
        return {"tone": ja.parse_bass_level(m["para"]) if m else None}
    if a == "clarifi":
        if body.get("on"):
            level = max(0, min(9, int(body.get("level", 5))))
            SESSION.send("signal_doctor_control", f"on||{level}")
        else:
            SESSION.send("signal_doctor_control", "off")
        return {"signal_doctor": _para(SESSION.query("signal_doctor"))}
    if a == "name":
        SESSION.send("set_device_name", body["name"].strip(), settle=0.5)
        return {"device_name": _para(SESSION.query("device_name"))}
    if a == "spectrum":
        m = SESSION.query("spectrum_data", 1.5)
        return {"spectrum": ja.parse_spectrum(m["para_bytes"]) if m else None}
    if a == "raw":
        msgs = SESSION.send(body.get("name", "").strip(), body.get("para", ""),
                            element=body.get("element", "control"),
                            zone=body.get("zone", "Main Zone"), settle=1.0)
        return {"replies": [{"name": m["name"], "zone": m["zone"], "para": m["para"]} for m in msgs]}
    raise ValueError(f"unknown action {a!r}")


class Handler(BaseHTTPRequestHandler):
    server_version = "jbl-ui/0.1"

    def log_message(self, fmt, *args):   # keep the terminal quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(200, {"ok": True, "result": SESSION.state()})
            elif path == "/api/status":
                self._send(200, {"ok": True, "result": SESSION.status()})
            elif path == "/api/discover":
                self._send(200, {"ok": True, "result": ja.discover(3.0)})
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except NotConnected as exc:
            self._send(409, {"ok": False, "error": str(exc)})
        except (OSError, ConnectionError) as exc:
            self._send(502, {"ok": False, "error": f"speaker connection failed: {exc}"})
        except SystemExit as exc:            # discover() raises this if multicast fails
            self._send(500, {"ok": False, "error": str(exc)})
        except Exception as exc:             # noqa: BLE001 - report to the page
            self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/connect":
                SESSION.connect(body.get("target", ""))
                self._send(200, {"ok": True, "result": SESSION.state()})
            elif path == "/api/disconnect":
                SESSION.disconnect()
                self._send(200, {"ok": True, "result": SESSION.state()})
            elif path == "/api/command":
                self._send(200, {"ok": True, "result": run_action(body)})
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except NotConnected as exc:
            self._send(409, {"ok": False, "error": str(exc)})
        except (OSError, ConnectionError) as exc:
            self._send(502, {"ok": False, "error": f"speaker connection failed: {exc}"})
        except (KeyError, ValueError) as exc:
            self._send(400, {"ok": False, "error": f"bad request: {exc}"})
        except Exception as exc:             # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JBL Authentics</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='14' fill='%23f28c22'/%3E%3Ccircle cx='16' cy='16' r='5' fill='%23111'/%3E%3C/svg%3E">
<style>
  :root { --bg:#14161a; --card:#1e2127; --line:#2c3038; --fg:#e8e8e8; --muted:#9aa0a8; --accent:#f28c22; --ok:#4cc38a; --bad:#e5484d; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font: 15px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
  header { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:14px 18px; border-bottom:1px solid var(--line); }
  header h1 { font-size:17px; margin:0 12px 0 0; font-weight:600; }
  main { display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap:14px; padding:16px 18px; max-width:1200px; margin:0 auto; }
  section { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  section h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 10px; }
  button { background:#2a2e36; color:var(--fg); border:1px solid var(--line); border-radius:8px; padding:7px 12px; font:inherit; cursor:pointer; }
  button:hover { border-color:#4a505a; }
  button.on { background:var(--accent); border-color:var(--accent); color:#111; font-weight:600; }
  button:disabled { opacity:.45; cursor:default; }
  input[type=text], select { background:#111318; color:var(--fg); border:1px solid var(--line); border-radius:8px; padding:7px 10px; font:inherit; min-width:0; }
  input[type=range] { width:100%; accent-color: var(--accent); }
  .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0; }
  .grow { flex:1; }
  .dot { width:10px; height:10px; border-radius:50%; background:var(--bad); display:inline-block; }
  .dot.ok { background:var(--ok); }
  .val { min-width:2.5em; text-align:right; font-variant-numeric: tabular-nums; color:var(--muted); }
  .muted { color:var(--muted); font-size:13px; }
  label.slider { display:grid; grid-template-columns: 4em 1fr 2.5em; gap:10px; align-items:center; margin:8px 0; }
  #log { height:220px; overflow:auto; background:#0f1115; border:1px solid var(--line); border-radius:8px; padding:8px 10px; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; white-space:pre-wrap; }
  #log .out { color:#8ab4f8; } #log .in { color:#b6e3a8; } #log .sys { color:var(--muted); } #log .err { color:var(--bad); }
  canvas { width:100%; height:90px; background:#0f1115; border-radius:8px; border:1px solid var(--line); }
  .wide { grid-column: 1 / -1; }
</style>
</head>
<body>
<header>
  <h1>JBL Authentics</h1>
  <span id="dot" class="dot"></span>
  <span id="conn" class="muted">not connected</span>
  <span class="grow"></span>
  <button id="discover">Discover</button>
  <select id="found" hidden></select>
  <input id="target" type="text" placeholder="speaker IP (or ip:port)" size="20">
  <button id="connect" class="on">Connect</button>
  <button id="disconnect" hidden>Disconnect</button>
  <button id="refresh" title="query everything again">Refresh</button>
</header>
<main>
  <section>
    <h2>Power</h2>
    <div class="row"><button data-power="on">On</button><button data-power="off">Off</button><span id="power" class="val">–</span></div>
    <label class="muted"><input id="altpower" type="checkbox"> use the status-element form (the one reported to work on the L8)</label>
  </section>
  <section>
    <h2>Source</h2>
    <div class="row" id="sources">
      <button data-source="airplay">AirPlay</button><button data-source="bluetooth">Bluetooth</button>
      <button data-source="dlna">DLNA / Spotify</button><button data-source="optical">Optical</button>
      <button data-source="aux">Aux</button><button data-source="phono">Phono</button>
    </div>
  </section>
  <section>
    <h2>Volume</h2>
    <div class="row"><button id="voldown">−</button><input id="volume" type="range" min="0" max="39" value="0" class="grow"><button id="volup">+</button><span id="volval" class="val">–</span></div>
  </section>
  <section>
    <h2>Tone</h2>
    <label class="slider">Bass <input id="bass" type="range" min="0" max="10" value="5"><span class="val" id="bassv">5</span></label>
    <label class="slider">Mid <input id="mid" type="range" min="0" max="10" value="5"><span class="val" id="midv">5</span></label>
    <label class="slider">High <input id="high" type="range" min="0" max="10" value="5"><span class="val" id="highv">5</span></label>
    <div class="row"><button id="tonereset">Reset to flat</button><span id="tonestate" class="muted"></span></div>
  </section>
  <section>
    <h2>Clari-Fi</h2>
    <div class="row"><button id="clarion">On</button><button id="clarioff">Off</button><span id="claristate" class="muted"></span></div>
    <label class="slider">Level <input id="clarilevel" type="range" min="0" max="9" value="5"><span class="val" id="clarilevelv">5</span></label>
    <div class="row"><button id="spectrum">Start spectrum</button><span class="muted">live analyzer data from the speaker</span></div>
    <canvas id="canvas" width="600" height="90"></canvas>
  </section>
  <section>
    <h2>Speaker</h2>
    <div class="row"><input id="name" type="text" placeholder="device name" class="grow"><button id="rename">Rename</button></div>
    <div class="muted">Firmware version: <span id="version">–</span></div>
  </section>
  <section class="wide">
    <h2>Raw command</h2>
    <div class="row">
      <input id="rawname" type="text" placeholder="name, e.g. query-status" size="24">
      <input id="rawpara" type="text" placeholder="para, e.g. MAC_address" size="24">
      <select id="rawelem"><option value="control">control</option><option value="status">status</option></select>
      <button id="rawsend">Send</button>
      <span class="grow"></span>
      <button id="clearlog">Clear log</button>
    </div>
    <div class="muted">Everything sent (blue) and received (green) appears here. This is how you verify the protocol on your unit.</div>
    <div id="log"></div>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let connected = false, lastLogId = 0, lastErr = '', statusTimer = null, spectrumTimer = null, spectrumBusy = false;

async function api(path, body) {
  const opts = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ok: false, error: 'bad response'}));
  if (!r.ok || j.ok === false) throw new Error(j.error || ('HTTP ' + r.status));
  return j.result;
}
function line(text, cls) {
  const d = document.createElement('div'); d.className = cls || 'sys'; d.textContent = text;
  const log = $('log'); log.appendChild(d); log.scrollTop = log.scrollHeight;
}
async function command(body) {
  try { return await api('/api/command', body); }
  catch (e) { line('error: ' + e.message, 'err'); return null; }
}
function setConnected(on, target) {
  connected = on;
  $('dot').className = 'dot' + (on ? ' ok' : '');
  $('conn').textContent = on ? ('connected to ' + target) : 'not connected';
  $('connect').hidden = on; $('disconnect').hidden = !on;
  document.querySelectorAll('main button, main input').forEach(el => el.disabled = !on);
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
  if (on) { refresh(); statusTimer = setInterval(refresh, 8000); }
}
function srcMatch(btn, reply) { reply = String(reply).toLowerCase(); return btn === reply || (btn === 'optical' && reply === 'optical1'); }
function applyStatus(s) {
  if (!s) return;
  if (s.power != null) $('power').textContent = s.power;
  if (s.volume != null) { $('volume').value = s.volume; $('volval').textContent = s.volume; }
  if (s.source != null) document.querySelectorAll('[data-source]').forEach(b => b.classList.toggle('on', srcMatch(b.dataset.source, s.source)));
  if (s.tone) {
    for (const k of ['bass', 'mid', 'high']) if (s.tone[k] != null) { $(k).value = s.tone[k]; $(k + 'v').textContent = s.tone[k]; }
    $('tonestate').textContent = 'manual EQ: ' + (s.tone.manual_eq || '?');
  }
  if (s.signal_doctor != null) {
    const on = String(s.signal_doctor).toLowerCase().startsWith('on');
    $('claristate').textContent = s.signal_doctor;
    $('clarion').classList.toggle('on', on); $('clarioff').classList.toggle('on', !on);
    const m = /\|\|(\d+)/.exec(s.signal_doctor); if (m) { $('clarilevel').value = m[1]; $('clarilevelv').textContent = m[1]; }
  }
  if (s.device_name != null) $('name').value = s.device_name;
  if (s.sys_version != null) $('version').textContent = s.sys_version;
}
async function refresh() {
  if (!connected) return;
  try { applyStatus(await api('/api/status')); } catch (e) { line('status: ' + e.message, 'err'); }
}
async function pollState() {
  try {
    const st = await api('/api/state');
    if (st.connected !== connected) setConnected(st.connected, st.target);
    if (!st.connected && st.error && st.error !== lastErr) { lastErr = st.error; }
    for (const e of st.log) if (e.id > lastLogId) {
      lastLogId = e.id;
      line(e.t + '  ' + e.d + ' ' + e.m, e.d === '>' ? 'out' : e.d === '<' ? 'in' : e.d === '!' ? 'err' : 'sys');
    }
  } catch (e) { /* server not reachable; try again next tick */ }
}
$('discover').onclick = async () => {
  $('discover').disabled = true; $('discover').textContent = 'Searching…';
  try {
    const devs = await api('/api/discover');
    const sel = $('found'); sel.innerHTML = '';
    if (!devs.length) line('discover: nothing answered the SSDP search');
    for (const d of devs) {
      const o = document.createElement('option'); o.value = d.ip;
      o.textContent = (d.authentics ? '★ ' : '') + d.ip + '  ' + (d.friendlyName || d.modelName || d.server || '');
      sel.appendChild(o);
      line('found ' + d.ip + '  ' + (d.friendlyName || '') + '  ' + (d.modelDescription || d.modelName || '') + (d.authentics ? '  [Authentics]' : ''));
    }
    sel.hidden = !devs.length;
    if (devs.length) { const best = devs.find(d => d.authentics) || devs[0]; sel.value = best.ip; $('target').value = best.ip; }
    sel.onchange = () => { $('target').value = sel.value; };
  } catch (e) { line('discover: ' + e.message, 'err'); }
  $('discover').disabled = false; $('discover').textContent = 'Discover';
};
$('connect').onclick = async () => {
  try {
    const st = await api('/api/connect', {target: $('target').value});
    localStorage.setItem('jbl_target', $('target').value);
    setConnected(st.connected, st.target);
  } catch (e) { line('connect: ' + e.message, 'err'); }
};
$('disconnect').onclick = async () => { try { await api('/api/disconnect', {}); } catch (e) {} setConnected(false); };
$('refresh').onclick = refresh;
document.querySelectorAll('[data-power]').forEach(b => b.onclick = async () => applyStatus(await command({action: 'power', state: b.dataset.power, alt: $('altpower').checked})));
document.querySelectorAll('[data-source]').forEach(b => b.onclick = async () => applyStatus(await command({action: 'source', name: b.dataset.source})));
$('volume').oninput = () => { $('volval').textContent = $('volume').value; };
$('volume').onchange = async () => applyStatus(await command({action: 'volume', value: +$('volume').value}));
$('volup').onclick = async () => applyStatus(await command({action: 'volume', step: 'up'}));
$('voldown').onclick = async () => applyStatus(await command({action: 'volume', step: 'down'}));
async function sendTone() { applyStatus(await command({action: 'tone', bass: +$('bass').value, mid: +$('mid').value, high: +$('high').value})); }
for (const k of ['bass', 'mid', 'high']) { $(k).oninput = () => { $(k + 'v').textContent = $(k).value; }; $(k).onchange = sendTone; }
$('tonereset').onclick = async () => applyStatus(await command({action: 'tone', off: true}));
$('clarilevel').oninput = () => { $('clarilevelv').textContent = $('clarilevel').value; };
$('clarilevel').onchange = async () => applyStatus(await command({action: 'clarifi', on: true, level: +$('clarilevel').value}));
$('clarion').onclick = async () => applyStatus(await command({action: 'clarifi', on: true, level: +$('clarilevel').value}));
$('clarioff').onclick = async () => applyStatus(await command({action: 'clarifi', on: false}));
$('rename').onclick = async () => applyStatus(await command({action: 'name', name: $('name').value}));
function drawSpectrum(v) {
  const c = $('canvas'), g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  if (!v || !v.length) return;
  const max = Math.max(1, ...v), w = c.width / v.length;
  g.fillStyle = '#f28c22';
  v.forEach((x, i) => { const h = x / max * (c.height - 6); g.fillRect(i * w + 1, c.height - h, Math.max(1, w - 2), h); });
}
$('spectrum').onclick = () => {
  if (spectrumTimer) { clearInterval(spectrumTimer); spectrumTimer = null; $('spectrum').textContent = 'Start spectrum'; return; }
  $('spectrum').textContent = 'Stop spectrum';
  spectrumTimer = setInterval(async () => {
    if (spectrumBusy) return; spectrumBusy = true;
    try { const r = await command({action: 'spectrum'}); if (r && r.spectrum) drawSpectrum(r.spectrum); } finally { spectrumBusy = false; }
  }, 400);
};
$('rawsend').onclick = async () => {
  const r = await command({action: 'raw', name: $('rawname').value, para: $('rawpara').value, element: $('rawelem').value});
  if (r && !r.replies.length) line('(no reply within 1 s)');
};
$('clearlog').onclick = () => { $('log').innerHTML = ''; };
$('target').value = localStorage.getItem('jbl_target') || '';
setConnected(false);
pollState(); setInterval(pollState, 1500);
</script>
</body>
</html>
"""


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="speaker IP (or ip:port) to connect to at startup")
    p.add_argument("--port", type=int, default=8765, help="local port for the web UI (default 8765)")
    p.add_argument("--bind", default="127.0.0.1", help="address to serve on (default: this Mac only)")
    p.add_argument("--no-browser", action="store_true", help="do not open the page automatically")
    args = p.parse_args(argv)

    if args.host:
        try:
            SESSION.connect(args.host)
        except (OSError, ValueError) as exc:
            print(f"could not connect to {args.host}: {exc}", file=sys.stderr)

    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    url = f"http://{args.bind}:{args.port}/"
    print(f"JBL Authentics UI: {url}   (Ctrl-C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SESSION.disconnect()
        httpd.server_close()


if __name__ == "__main__":
    main()
