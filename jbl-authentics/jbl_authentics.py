#!/usr/bin/env python3
"""
jbl_authentics.py - reference control client for the JBL Authentics L8 / L16.

Speaks Harman's "MM" XML-over-TCP protocol on port 10025, as used by the
JBL Music 3.0 Android app (package com.harman.jblmusicflow) and the community
Node-RED flow for the L8. Standard library only, Python 3.8+.

STATUS: derived from the app's decompiled code. Not yet verified against real
hardware by the author of this file. Items the Node-RED author confirmed on an
L8: volume-up/down, source-selection OPTICAL1/Dlna, query-status volume/power/
source, and power via the <status> element (see `power --alt`).

Examples:
  python3 jbl_authentics.py discover
  python3 jbl_authentics.py --host 192.168.1.50 status
  python3 jbl_authentics.py --host 192.168.1.50 source optical
  python3 jbl_authentics.py --host 192.168.1.50 volume 20
  python3 jbl_authentics.py --host 192.168.1.50 volume up
  python3 jbl_authentics.py --host 192.168.1.50 tone 6 5 7
  python3 jbl_authentics.py --host 192.168.1.50 tone off
  python3 jbl_authentics.py --host 192.168.1.50 clarifi on 5
  python3 jbl_authentics.py --host 192.168.1.50 power on --alt
  python3 jbl_authentics.py --host 192.168.1.50 raw query-status MAC_address
  python3 jbl_authentics.py --host 192.168.1.50 monitor
"""
import argparse
import json
import re
import socket
import struct
import sys
import threading
import time
import urllib.request

PORT = 10025
SSDP_GROUP = ("239.255.255.250", 1900)
MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "MX: 3\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "ST: upnp:rootdevice\r\n"
    "\r\n"
)
MDNS_GROUP = ("224.0.0.251", 5353)
# Services the speaker advertises with mDNS: AirPlay audio (RAOP), AirPlay, Spotify Connect.
MDNS_SERVICES = ("_raop._tcp.local", "_airplay._tcp.local", "_spotify-connect._tcp.local")
XML_PROLOG = '<?xml version="1.0" encoding="UTF-8"?>'

# Friendly name -> exact <para> the app sends with source-selection.
SOURCES = {
    "airplay": "Airplay",
    "bluetooth": "Bluetooth",
    "bt": "Bluetooth",
    "dlna": "Dlna",
    "spotify": "Dlna",   # the app's "SPOTIFY/DLNA" button sends Dlna
    "optical": "OPTICAL1",
    "aux": "AUX",
    "phono": "Phono",    # L16 only
}

STATUS_QUERIES = [
    "power", "volume", "source", "bass_level", "signal_doctor",
    "device_name", "sys_version", "MAC_address",
]


# --------------------------------------------------------------------------
# Wire format
# --------------------------------------------------------------------------
def build_request(name, para="", zone="Main Zone", element="control"):
    """Return the exact bytes the app writes to the socket for one command."""
    body = (
        f"{XML_PROLOG} <harman> <mm> <common> <{element}> "
        f"<name>{name}</name> <zone>{zone}</zone> <para>{para}</para> "
        f"</{element}> </common> </mm> </harman>"
    ).encode("utf-8")
    head = (
        f"POST MM HTTP/1.1\r\n"
        f"Host: :{PORT}\r\n"
        f"User-Agent: Harman Remote Controller/1.0\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
    ).encode("ascii")
    return head + body


_MSG_RE = re.compile(rb"<harman>.*?</harman>", re.S)


def _field(blob, tag):
    m = re.search(rb"<" + tag + rb">(.*?)</" + tag + rb">", blob, re.S)
    return m.group(1) if m else b""


def _text(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_messages(buf):
    """Split a receive buffer into status dicts. Returns (messages, leftover)."""
    msgs, end = [], 0
    for m in _MSG_RE.finditer(buf):
        blob = m.group(0)
        para = _field(blob, b"para")
        msgs.append({
            "name": _text(_field(blob, b"name")),
            "zone": _text(_field(blob, b"zone")),
            "para": _text(para),
            "para_bytes": para,
        })
        end = m.end()
    rest = buf[end:]
    if len(rest) > 65536:          # never let junk accumulate forever
        rest = rest[-4096:]
    return msgs, rest


def parse_bass_level(para):
    """'on||<x>@<b><m><h>' -> dict. Digits 0-9, ':' means 10."""
    state, _, rest = para.partition("||")
    levels = rest.partition("@")[2]

    def lv(c):
        if c == ":":
            return 10
        return int(c) if c.isdigit() else None

    vals = [lv(c) for c in levels[:3]] + [None, None, None]
    return {"manual_eq": state.strip().lower(), "bass": vals[0],
            "mid": vals[1], "high": vals[2], "raw": para}


def parse_spectrum(para_bytes):
    """Raw para bytes taken in pairs, big-endian, one value per band."""
    return [(para_bytes[i] << 8) | para_bytes[i + 1]
            for i in range(0, len(para_bytes) - 1, 2)]


# --------------------------------------------------------------------------
# Discovery (SSDP)
# --------------------------------------------------------------------------
def fetch_description(url):
    """Pull the UPnP device description and return the interesting tags."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=3) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as exc:          # noqa: BLE001 - report, don't crash
        return {"description_error": str(exc)}
    out = {}
    for tag in ("friendlyName", "manufacturer", "modelName",
                "modelDescription", "modelNumber", "UDN"):
        m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), xml, re.S)
        if m:
            out[tag] = m.group(1).strip()
    return out


def discover_ssdp(timeout=6.0, fetch_descriptions=True):
    """UPnP search, the way the JBL Music app found the speaker."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    sock.settimeout(0.5)
    sock.bind(("", 0))
    payloads = [MSEARCH.encode("ascii"),
                MSEARCH.replace("upnp:rootdevice", "ssdp:all").encode("ascii")]
    seen = {}
    deadline = time.monotonic() + timeout
    next_send = 0.0
    while time.monotonic() < deadline:
        if time.monotonic() >= next_send:          # repeat the search like the app did
            try:
                for payload in payloads:
                    sock.sendto(payload, SSDP_GROUP)
            except OSError as exc:
                sock.close()
                raise SystemExit(f"SSDP send failed ({exc}); check that you are on the speaker's Wi-Fi") from exc
            next_send = time.monotonic() + 2.0
        try:
            data, (ip, _port) = sock.recvfrom(8192)
        except socket.timeout:
            continue
        text = data.decode("utf-8", "replace")
        headers = {}
        for line in text.split("\r\n")[1:]:
            k, _, v = line.partition(":")
            if k:
                headers[k.strip().lower()] = v.strip()
        location = headers.get("location", "")
        key = (ip, location)
        if key in seen:
            continue
        entry = {
            "ip": ip,
            "location": location,
            "usn": headers.get("usn", ""),
            "server": headers.get("server", ""),
            "authentics": "jbl_authentics" in text.lower(),
        }
        if fetch_descriptions and location:
            entry.update(fetch_description(location))
            ident = (entry.get("modelName", "") + entry.get("friendlyName", "")).lower()
            if "jbl_authentics" in ident:
                entry["authentics"] = True
        seen[key] = entry
    sock.close()
    return list(seen.values())


# -- minimal mDNS (Bonjour) browser, standard library only ------------------
def _dns_name(name):
    out = b""
    for label in name.strip(".").split("."):
        raw = label.encode("utf-8")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _mdns_query(names, qtype):
    pkt = struct.pack("!HHHHHH", 0, 0, len(names), 0, 0, 0)
    for n in names:
        pkt += _dns_name(n) + struct.pack("!HH", qtype, 1 | 0x8000)   # QU bit: please answer us directly
    return pkt


def _read_name(pkt, off):
    labels, jumped, end, hops = [], False, None, 0
    while True:
        hops += 1
        if hops > 128:
            raise ValueError("bad name")
        length = pkt[off]
        if length == 0:
            off += 1
            break
        if length & 0xC0 == 0xC0:
            pointer = struct.unpack("!H", pkt[off:off + 2])[0] & 0x3FFF
            if not jumped:
                end = off + 2
            jumped, off = True, pointer
            continue
        off += 1
        labels.append(pkt[off:off + length].decode("utf-8", "replace"))
        off += length
    return ".".join(labels), (end if jumped else off)


def _parse_mdns(pkt):
    """Return (owner name, type, value) for the PTR/SRV/TXT/A records in a DNS message."""
    recs = []
    try:
        _id, _flags, qd, an, ns, ar = struct.unpack("!HHHHHH", pkt[:12])
        off = 12
        for _ in range(qd):
            _, off = _read_name(pkt, off)
            off += 4
        for _ in range(an + ns + ar):
            name, off = _read_name(pkt, off)
            rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", pkt[off:off + 10])
            off += 10
            rdata, rdstart = pkt[off:off + rdlen], off
            off += rdlen
            if rtype == 12:
                recs.append((name, "PTR", _read_name(pkt, rdstart)[0]))
            elif rtype == 33:
                _prio, _weight, port = struct.unpack("!HHH", rdata[:6])
                recs.append((name, "SRV", (_read_name(pkt, rdstart + 6)[0], port)))
            elif rtype == 1 and rdlen == 4:
                recs.append((name, "A", socket.inet_ntoa(rdata)))
            elif rtype == 16:
                items, i = [], 0
                while i < len(rdata):
                    n = rdata[i]
                    items.append(rdata[i + 1:i + 1 + n].decode("utf-8", "replace"))
                    i += 1 + n
                recs.append((name, "TXT", items))
    except (struct.error, IndexError, ValueError):
        pass
    return recs


def discover_mdns(timeout=5.0):
    """Find AirPlay / Spotify Connect responders. The L16 advertises both when it is on Wi-Fi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:                                   # listen on the mDNS port too, for multicast replies
        sock.bind(("", MDNS_GROUP[1]))
        mreq = struct.pack("4s4s", socket.inet_aton(MDNS_GROUP[0]), socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError:                        # fall back to unicast replies only
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.bind(("", 0))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    sock.settimeout(0.3)

    ptr, srv, txt, addr, sender = {}, {}, {}, {}, {}
    asked = set()

    def ask(names, qtype):
        try:
            sock.sendto(_mdns_query(names, qtype), MDNS_GROUP)
        except OSError:
            pass

    deadline = time.monotonic() + timeout
    next_send = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_send:
            ask(list(MDNS_SERVICES), 12)
            next_send = now + 1.5
        try:
            data, (ip, _port) = sock.recvfrom(9000)
        except socket.timeout:
            data = None
        except OSError:
            break
        if data:
            for name, rtype, value in _parse_mdns(data):
                key = name.lower()
                if rtype == "PTR":
                    ptr.setdefault(key, set()).add(value)
                    sender.setdefault(value.lower(), ip)
                elif rtype == "SRV":
                    srv[key] = value
                elif rtype == "TXT":
                    txt[key] = value
                elif rtype == "A":
                    addr[key] = value
        # follow-up questions for instances we only half know
        for service in MDNS_SERVICES:
            for inst in ptr.get(service, ()):
                k = inst.lower()
                if k not in srv and ("SRV", k) not in asked:
                    asked.add(("SRV", k)); ask([inst], 33)
                elif k in srv and srv[k][0].lower() not in addr and ("A", srv[k][0].lower()) not in asked:
                    asked.add(("A", srv[k][0].lower())); ask([srv[k][0]], 1)
    sock.close()

    results = []
    for service in MDNS_SERVICES:
        for inst in sorted(ptr.get(service, ())):
            k = inst.lower()
            host, port = srv.get(k, ("", 0))
            ip = addr.get(host.lower(), "") or sender.get(k, "")
            items = txt.get(k, [])
            label = inst[:-len(service) - 1] if k.endswith("." + service) else inst
            if service.startswith("_raop") and "@" in label:
                label = label.split("@", 1)[1]
            model = next((t.split("=", 1)[1] for t in items if t.startswith(("am=", "model=", "modelDisplayName="))), "")
            blob = (label + " " + model + " " + " ".join(items)).lower()
            results.append({
                "ip": ip, "friendlyName": label, "modelName": model, "host": host, "port": port,
                "service": service.split(".")[0].lstrip("_"), "txt": items, "location": "",
                "authentics": any(w in blob for w in ("l16", "l8", "authentics", "jbl")),
            })
    return results


def discover(timeout=6.0, fetch_descriptions=True):
    """UPnP search and mDNS browse at the same time, merged by IP address."""
    found = {"ssdp": [], "mdns": [], "error": None}

    def run_ssdp():
        try:
            found["ssdp"] = discover_ssdp(timeout, fetch_descriptions)
        except SystemExit as exc:
            found["error"] = exc

    t = threading.Thread(target=run_ssdp, daemon=True)
    t.start()
    found["mdns"] = discover_mdns(min(timeout, 5.0))
    t.join()
    if found["error"] is not None and not found["mdns"]:
        raise found["error"]
    by_ip, out = {}, []
    for d in found["ssdp"] + found["mdns"]:
        ip = d.get("ip", "")
        if ip and ip in by_ip:
            existing = by_ip[ip]
            for key, val in d.items():
                if val and not existing.get(key):
                    existing[key] = val
            existing["authentics"] = existing.get("authentics") or d.get("authentics", False)
            continue
        if ip:
            by_ip[ip] = d
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Control connection
# --------------------------------------------------------------------------
class Authentics:
    def __init__(self, host, port=PORT, timeout=5.0, verbose=False):
        self.sock = socket.create_connection((host, port), timeout=15)
        self.sock.settimeout(timeout)
        self.timeout = timeout
        self.verbose = verbose
        self.buf = b""
        self.pending = []
        self.last_beat = time.monotonic()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    # -- sending ------------------------------------------------------------
    def send(self, name, para="", zone="Main Zone", element="control"):
        data = build_request(name, para, zone, element)
        if self.verbose:
            print(">> " + data.decode("utf-8", "replace").replace("\r\n", "\\r\\n"),
                  file=sys.stderr)
        self.sock.sendall(data)

    def heartbeat(self):
        # The app sends heart-alive with an empty zone and para every 10 s.
        self.send("heart-alive", zone="")
        self.last_beat = time.monotonic()

    def maybe_heartbeat(self):
        if time.monotonic() - self.last_beat >= 10:
            self.heartbeat()

    # -- receiving ----------------------------------------------------------
    def recv(self, timeout=None):
        """Return the next status message, or None if nothing arrives in time."""
        if self.pending:
            return self.pending.pop(0)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("speaker closed the connection")
            self.buf += chunk
            msgs, self.buf = parse_messages(self.buf)
            if msgs:
                if self.verbose:
                    for m in msgs:
                        print("<< %s zone=%r para=%r" % (m["name"], m["zone"], m["para"]),
                              file=sys.stderr)
                self.pending.extend(msgs[1:])
                return msgs[0]

    def wait_for(self, name, timeout=3.0):
        """Wait for a status with this name; other messages are kept for later."""
        deadline = time.monotonic() + timeout
        skipped = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                m = self.recv(remaining)
                if m is None:
                    return None
                if m["name"] == name:
                    return m
                if m["name"] != "heart-alive":
                    skipped.append(m)
        finally:
            self.pending = skipped + self.pending

    def query(self, what, timeout=3.0):
        self.send("query-status", what)
        return self.wait_for(what, timeout)

    def drain(self, seconds):
        """Collect everything that arrives within `seconds`."""
        out = []
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return out
            m = self.recv(remaining)
            if m is None:
                return out
            out.append(m)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def show(m, label=None):
    if m is None:
        print(f"{label or '?':14} (no reply)")
        return
    label = label or m["name"]
    if m["name"] == "bass_level":
        print(f"{label:14} {parse_bass_level(m['para'])}")
    elif m["name"] == "spectrum_data":
        print(f"{label:14} {parse_spectrum(m['para_bytes'])}")
    else:
        print(f"{label:14} {m['para']!r}")


def cmd_discover(args, _spk=None):
    devices = discover(args.dtimeout)
    if not devices:
        print("Nothing answered the UPnP or AirPlay search. Is the speaker on this Wi-Fi network?")
        return 1
    for d in devices:
        flag = "AUTHENTICS" if d.get("authentics") else "          "
        via = f"  via {d['service']}" if d.get("service") else ""
        print(f"{flag} {d.get('ip') or '?':15} {d.get('friendlyName', '?')}  "
              f"model={d.get('modelName') or '?'}  desc={d.get('modelDescription') or '?'}{via}")
        if d.get("location"):
            print(f"           location={d['location']}")
        if d.get("host"):
            print(f"           host={d['host']} port={d['port']}")
        if d.get("description_error"):
            print(f"           description: {d['description_error']}")
    return 0


def cmd_status(args, spk):
    for what in STATUS_QUERIES:
        show(spk.query(what, timeout=2.0), what)
        time.sleep(0.15)
    return 0


def cmd_power(args, spk):
    if args.alt:
        # What the Node-RED author found to work on the L8: a <status> element.
        spk.send("power", args.state, element="status")
    else:
        spk.send("power-on" if args.state == "on" else "power-off")
    show(spk.wait_for("power", 2.0), "power")
    return 0


def cmd_source(args, spk):
    spk.send("source-selection", SOURCES[args.name])
    time.sleep(0.3)
    show(spk.query("source", 2.0), "source")
    return 0


def cmd_volume(args, spk):
    if args.value == "up":
        spk.send("volume-up")
    elif args.value == "down":
        spk.send("volume-down")
    else:
        v = int(args.value)
        if not 0 <= v <= 39:
            print("volume must be 0-39, up or down", file=sys.stderr)
            return 2
        spk.send("set_system_volume", str(v))
    time.sleep(0.3)
    show(spk.query("volume", 2.0), "volume")
    return 0


def cmd_mute(args, spk):
    spk.send({"on": "mute-on", "off": "mute-off", "toggle": "mute-toggle"}[args.state])
    for m in spk.drain(2.0):
        show(m)
    return 0


def cmd_tone(args, spk):
    if args.bass == "off":
        spk.send("set_manual_mode", "off")
    else:
        levels = [int(args.bass), int(args.mid), int(args.high)]
        if any(not 0 <= x <= 10 for x in levels):
            print("levels must be 0-10 (5 = flat)", file=sys.stderr)
            return 2
        for name, val in zip(("set_bass_level", "set_mid_level", "set_high_level"), levels):
            spk.send(name, str(val))
            time.sleep(0.15)
    time.sleep(0.3)
    show(spk.query("bass_level", 2.0), "bass_level")
    return 0


def cmd_clarifi(args, spk):
    if args.state == "off":
        spk.send("signal_doctor_control", "off")
    else:
        level = 5 if args.level is None else int(args.level)
        if not 0 <= level <= 9:
            print("level must be 0-9", file=sys.stderr)
            return 2
        spk.send("signal_doctor_control", f"on||{level}")
    time.sleep(0.3)
    show(spk.query("signal_doctor", 2.0), "signal_doctor")
    return 0


def cmd_name(args, spk):
    spk.send("set_device_name", args.new_name.strip())
    time.sleep(0.5)
    show(spk.query("device_name", 2.0), "device_name")
    return 0


def cmd_spectrum(args, spk):
    for _ in range(args.count):
        show(spk.query("spectrum_data", 2.0), "spectrum_data")
        time.sleep(0.3)
    return 0


def cmd_raw(args, spk):
    spk.send(args.name, args.para, zone=args.zone, element=args.element)
    replies = spk.drain(args.wait)
    if not replies:
        print("(no reply)")
    for m in replies:
        print(json.dumps({"name": m["name"], "zone": m["zone"], "para": m["para"]}))
    return 0


def cmd_monitor(args, spk):
    print("Sending heart-alive every 10 s and printing everything the speaker sends. Ctrl-C to stop.")
    spk.heartbeat()
    try:
        while True:
            m = spk.recv(1.0)
            if m is not None:
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp} {m['name']:16} zone={m['zone']!r} para={m['para']!r}")
            spk.maybe_heartbeat()
    except KeyboardInterrupt:
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="speaker IP or hostname (not needed for discover)")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--timeout", type=float, default=3.0, help="reply / discovery timeout in seconds")
    p.add_argument("-v", "--verbose", action="store_true", help="print raw traffic on stderr")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("discover", help="find speakers with SSDP")
    s.add_argument("--timeout", type=float, default=6.0, dest="dtimeout", help="seconds to listen (default 6)")
    s.set_defaults(fn=cmd_discover, needs_host=False)
    sub.add_parser("status", help="query power, volume, source, tone, Clari-Fi, name, version").set_defaults(fn=cmd_status)
    s = sub.add_parser("power"); s.add_argument("state", choices=["on", "off"])
    s.add_argument("--alt", action="store_true", help="use the <status> element form instead of power-on/power-off")
    s.set_defaults(fn=cmd_power)
    s = sub.add_parser("source"); s.add_argument("name", choices=sorted(SOURCES)); s.set_defaults(fn=cmd_source)
    s = sub.add_parser("volume"); s.add_argument("value", help="0-39, up, or down"); s.set_defaults(fn=cmd_volume)
    s = sub.add_parser("mute", help="unverified: the app never sends these"); s.add_argument("state", choices=["on", "off", "toggle"]); s.set_defaults(fn=cmd_mute)
    s = sub.add_parser("tone", help="bass mid high (0-10 each, 5 = flat), or 'off'")
    s.add_argument("bass"); s.add_argument("mid", nargs="?"); s.add_argument("high", nargs="?"); s.set_defaults(fn=cmd_tone)
    s = sub.add_parser("clarifi", help="Clari-Fi on <level 0-9> | off"); s.add_argument("state", choices=["on", "off"]); s.add_argument("level", nargs="?"); s.set_defaults(fn=cmd_clarifi)
    s = sub.add_parser("name"); s.add_argument("new_name"); s.set_defaults(fn=cmd_name)
    s = sub.add_parser("spectrum", help="read Clari-Fi spectrum data"); s.add_argument("--count", type=int, default=1); s.set_defaults(fn=cmd_spectrum)
    s = sub.add_parser("raw", help="send any <name>/<para> and print replies")
    s.add_argument("name"); s.add_argument("para", nargs="?", default="")
    s.add_argument("--zone", default="Main Zone"); s.add_argument("--element", default="control", choices=["control", "status"])
    s.add_argument("--wait", type=float, default=2.0); s.set_defaults(fn=cmd_raw)
    sub.add_parser("monitor", help="keep the connection open and print every message").set_defaults(fn=cmd_monitor)

    args = p.parse_args(argv)
    if getattr(args, "needs_host", True) and not args.host:
        p.error("--host is required for this command (run 'discover' first)")
    if args.cmd == "tone" and args.bass != "off" and (args.mid is None or args.high is None):
        p.error("tone needs three levels: bass mid high, or 'off'")

    if not getattr(args, "needs_host", True):
        return args.fn(args)
    spk = Authentics(args.host, args.port, args.timeout, args.verbose)
    try:
        return args.fn(args, spk)
    finally:
        spk.close()


if __name__ == "__main__":
    sys.exit(main())
