"""End-to-end test of jbl_authentics.py against fake_speaker.py on localhost.

    python3 test_fake_speaker.py
"""
import contextlib
import io
import os
import socket
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbl_authentics as ja           # noqa: E402
from fake_speaker import FakeSpeaker, XML, status  # noqa: E402


def _txt(*items):
    return b"".join(bytes([len(i)]) + i.encode() for i in items)


def _response(records):
    pkt = struct.pack("!HHHHHH", 0, 0x8400, 0, len(records), 0, 0)
    for name, rtype, rdata in records:
        pkt += ja._dns_name(name) + struct.pack("!HHIH", rtype, 0x8001, 120, len(rdata)) + rdata
    return pkt


def test_mdns_parsing():
    inst, host = "AABB@JBL L16._raop._tcp.local", "JBL-L16.local"
    pkt = _response([
        ("_raop._tcp.local", 12, ja._dns_name(inst)),
        (inst, 33, struct.pack("!HHH", 0, 0, 5000) + ja._dns_name(host)),
        (inst, 16, _txt("txtvers=1", "am=Authentics L16")),
        (host, 1, socket.inet_aton("10.0.0.99")),
    ])
    recs = ja._parse_mdns(pkt)
    assert ("_raop._tcp.local", "PTR", inst) in recs
    assert (inst, "SRV", (host, 5000)) in recs
    assert (inst, "TXT", ["txtvers=1", "am=Authentics L16"]) in recs
    assert (host, "A", "10.0.0.99") in recs
    # name compression: answer name and PTR target both point back into the question
    q = ja._dns_name("_raop._tcp.local")
    pkt = struct.pack("!HHHHHH", 0, 0x8400, 1, 1, 0, 0) + q + struct.pack("!HH", 12, 1)
    rdata = b"\x0aAA@JBL L16" + b"\xc0\x0c"
    pkt += b"\xc0\x0c" + struct.pack("!HHIH", 12, 1, 120, len(rdata)) + rdata
    assert ja._parse_mdns(pkt) == [("_raop._tcp.local", "PTR", "AA@JBL L16._raop._tcp.local")]
    assert ja._parse_mdns(b"garbage") == []
    print("mDNS parsing OK")


class FakeMdns(threading.Thread):
    """Answers PTR lazily (no extra records) so discover_mdns must ask SRV and A itself."""

    def __init__(self, spotify_port=0):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.inst, self.host = "AABB@JBL L16._raop._tcp.local", "JBL-L16.local"
        self.sp_inst, self.sp_host, self.sp_port = "SpotifyConnect._spotify-connect._tcp.local", "spotify-box.local", spotify_port
        self.questions = []

    def run(self):
        while True:
            data, peer = self.sock.recvfrom(4096)
            _id, _f, qd, _an, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
            off, answers = 12, []
            for _ in range(qd):
                name, off = ja._read_name(data, off)
                qtype = struct.unpack("!H", data[off:off + 2])[0]
                off += 4
                self.questions.append((name, qtype))
                if qtype == 12 and name == "_raop._tcp.local":
                    answers.append((name, 12, ja._dns_name(self.inst)))
                elif qtype == 33 and name == self.inst:
                    answers.append((name, 33, struct.pack("!HHH", 0, 0, 5000) + ja._dns_name(self.host)))
                    answers.append((name, 16, _txt("am=Authentics L16")))
                elif qtype == 1 and name == self.host:
                    answers.append((name, 1, socket.inet_aton("10.0.0.99")))
                elif qtype == 12 and name == "_spotify-connect._tcp.local" and self.sp_port:
                    answers.append((name, 12, ja._dns_name(self.sp_inst)))
                    answers.append((self.sp_inst, 33, struct.pack("!HHH", 0, 0, self.sp_port) + ja._dns_name(self.sp_host)))
                    answers.append((self.sp_inst, 16, _txt("CPath=/zc", "VERSION=1.0")))
                    answers.append((self.sp_host, 1, socket.inet_aton("127.0.0.1")))
            if answers:
                self.sock.sendto(_response(answers), peer)


class _GetInfo(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b'{"remoteName":"Living Room L16","brandDisplayName":"JBL","modelDisplayName":"Authentics L16","deviceType":"SPEAKER","libraryVersion":"2.0.1"}'
        self.send_response(200 if "action=getInfo" in self.path and self.path.startswith("/zc") else 404)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


def test_mdns_discovery():
    httpd = HTTPServer(("127.0.0.1", 0), _GetInfo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    responder = FakeMdns(spotify_port=httpd.server_address[1]); responder.start()
    saved = ja.MDNS_GROUP
    ja.MDNS_GROUP = ("127.0.0.1", responder.port)
    try:
        found = ja.discover_mdns(2.5)
    finally:
        ja.MDNS_GROUP = saved
    raop = [d for d in found if d["service"] == "raop"]
    assert raop, found
    d = raop[0]
    assert d["ip"] == "10.0.0.99" and d["friendlyName"] == "JBL L16" and d["host"] == "JBL-L16.local"
    assert d["port"] == 5000 and d["modelName"] == "Authentics L16" and d["authentics"], d
    assert ("AABB@JBL L16._raop._tcp.local", 33) in responder.questions and ("JBL-L16.local", 1) in responder.questions
    sp = [d for d in found if d["service"] == "spotify-connect"]
    assert sp and sp[0]["ip"] == "127.0.0.1" and sp[0]["friendlyName"] == "Living Room L16" and sp[0]["modelName"] == "JBL Authentics L16" and sp[0]["authentics"], sp
    assert ja.spotify_info("127.0.0.1", 1) == {}
    # merge with an SSDP hit for the same address
    saved_ssdp, saved_mdns = ja.discover_ssdp, ja.discover_mdns
    ja.discover_ssdp = lambda *a, **k: [{"ip": "10.0.0.99", "location": "http://10.0.0.99:8080/description.xml", "authentics": False}]
    ja.discover_mdns = lambda *a, **k: [d]
    try:
        merged = ja.discover(1.0)
    finally:
        ja.discover_ssdp, ja.discover_mdns = saved_ssdp, saved_mdns
    assert len(merged) == 1 and merged[0]["location"].endswith("description.xml") and merged[0]["friendlyName"] == "JBL L16" and merged[0]["authentics"]
    print("mDNS discovery OK")


class _FakeBootloader(BaseHTTPRequestHandler):
    """Replies copied from a real L16 bootloader page, plus the second progress handler."""
    known = {"aformNetFwHandler", "aformFwUpdateProgessHandler", "aformHandlerSetNetFwUpdate", "aformHandlerRestartNotify"}
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, out, code=200):
        data = out.encode()
        self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        name = self.path.rsplit("/", 1)[-1]
        _FakeBootloader.seen.append(("GET", name, ""))
        if self.path.startswith("/goform/") and name in self.known:
            return self._send("qwhgpstgrizEndRes\r\n")
        self._send("<html><head><title>Document Error: Data follows</title></head>\n\t\t<body><h2>Access Error: Data follows</h2>"
                   f"\n\t\t<p>Form {name} is not defined</p></body></html>\r\n\r\n", 404 if name else 200)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        name = self.path.rsplit("/", 1)[-1]
        _FakeBootloader.seen.append(("POST", name, body))
        if name == "aformNetFwHandler" and body == "pollStatus=1":
            out = "1qwhgpstgriz1qwhgpstgriz1qwhgpstgriz8zirgtspghwq0qwhgpstgrizEndRes\n"
        elif name == "aformNetFwHandler" and body == "pollStatus=2":
            out = "2qwhgpstgriz1qwhgpstgriz2qwhgpstgriz1000zirgtspghwq1.29zirgtspghwqqwhgpstgrizEndRes\n"
        elif name == "aformNetFwHandler" and body == "pollStatus=0":
            out = "7qwhgpstgriz1qwhgpstgriz0qwhgpstgriz0qwhgpstgrizEndRes\n"
        elif name == "aformFwUpdateProgessHandler" and body == "pollStatus=1":
            out = "1qwhgpstgriz1qwhgpstgriz1qwhgpstgriz2zirgtspghwq37qwhgpstgrizEndRes\n"
        elif name == "aformFwUpdateProgessHandler" and body == "pollStatus=2":
            out = "2qwhgpstgriz1qwhgpstgriz2qwhgpstgriz1zirgtspghwq50qwhgpstgrizEndRes\n"
        elif name == "aformHandlerSetNetFwUpdate" and body == "readyStatus=0":
            out = "8qwhgpstgriz1qwhgpstgriz8qwhgpstgriz0qwhgpstgrizEndRes\n"
        elif name not in self.known:
            return self.do_GET()
        else:
            out = "qwhgpstgrizEndRes"
        self._send(out)


def _serve(handler):
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"127.0.0.1:{httpd.server_address[1]}"


def _run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ja.main(list(args))
    return rc, out.getvalue()


def _build_bcod(segments, padding=140):
    """A minimal JukeBlox module image: header, segment table with CRC-32s, 'DMP 3.x' marker, data, 0xFF pad."""
    import zlib
    hdr = bytearray(0xB8)
    hdr[0:4] = b"bCoD"; hdr[4:8] = struct.pack("<I", 1); hdr[8:24] = b"20131106051708  "
    hdr[0xB0:0xB8] = b"DMP 3.x\0"
    body, off = b"", 0xB8
    for i, (load, flags, data) in enumerate(segments):
        struct.pack_into("<IIIII", hdr, 0x30 + i * 0x20, off, load, len(data), zlib.crc32(data) & 0xFFFFFFFF, flags)
        body += data; off += len(data)
    return bytes(hdr) + body + b"\xff" * padding


def _build_hui(secs, versions=None, product=b"JBL_L16"):
    """A HUI container with correct section and file checksums."""
    versions = versions or [(9, 2, 1, 0)] * len(secs)
    table_off, n = 0x30, len(secs)
    body_off = table_off + n * 32
    table, blobs, off = b"", b"", body_off
    for i, blob in enumerate(secs):
        table += struct.pack("<I4BIII", i, *versions[i], off, len(blob), ja.hui_checksum(blob)) + b"\x00" * 12
        blobs += blob; off += len(blob)
    total = body_off + len(blobs)
    hdr = b"HUI " + bytes([9, 2, 1, 0]) + struct.pack("<IIII", n, table_off, total, 0) + b"\x00" * 8 + product.ljust(16, b"\x00")
    assert len(hdr) == table_off
    whole = hdr + table + blobs
    return whole[:0x14] + struct.pack("<I", ja.hui_checksum(whole)) + whole[0x18:]


class _FakeBootloaderFlash(BaseHTTPRequestHandler):
    state = {"uploaded": None, "flash": 0, "restarted": False}

    def log_message(self, *a):
        pass

    def _reply(self, text):
        data = text.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        st = _FakeBootloaderFlash.state
        if self.path == "/goform/aformNetFwUpdateHandler":
            boundary = self.headers.get("Content-Type", "").split("boundary=")[1].encode()
            first = body.index(b"\r\n\r\n") + 4
            end = body.index(b"\r\n--" + boundary, first)
            st["uploaded"] = body[first:end]
            return self._reply("ok")
        if self.path == "/goform/aformHandlerRestartNotify":
            return self._reply("7qwhgpstgriz1qwhgpstgriz0qwhgpstgrizEndRes" if st["restarted"] else "8qwhgpstgriz1qwhgpstgriz0qwhgpstgrizEndRes")
        p = body.decode()
        if p == "pollStatus=1":
            return self._reply("8qwhgpstgriz1qwhgpstgriz1qwhgpstgriz3zirgtspghwq100qwhgpstgrizEndRes" if st["uploaded"]
                               else "8qwhgpstgriz1qwhgpstgriz1qwhgpstgrizFirmware Update not startedzirgtspghwq0qwhgpstgrizEndRes")
        if p == "pollStatus=2":
            if not st["uploaded"]:
                return self._reply("8qwhgpstgriz1qwhgpstgriz2qwhgpstgriz999zirgtspghwqzirgtspghwqqwhgpstgrizEndRes")
            ok = st["uploaded"][:4] == b"bCoD"
            return self._reply(f"8qwhgpstgriz1qwhgpstgriz2qwhgpstgriz{0 if ok else 2}zirgtspghwqs.237.149zirgtspghwqs9.7.5.9qwhgpstgrizEndRes")
        if p == "pollStatus=3":
            st["flash"] = 1
            return self._reply("8qwhgpstgriz1qwhgpstgriz3qwhgpstgriz1qwhgpstgrizEndRes")
        if p == "pollStatus=4":
            st["flash"] = min(3, st["flash"] + 1)
            if st["flash"] == 3:
                st["restarted"] = True
            return self._reply(f"8qwhgpstgriz1qwhgpstgriz4qwhgpstgriz{st['flash']}zirgtspghwq{st['flash'] * 33}qwhgpstgrizEndRes")
        return self._reply("qwhgpstgrizEndRes")


def test_fwflash(tmpdir="/tmp"):
    import struct, tempfile
    # build a small fake container: 3 sections, section 2 is a module image
    secs = [b"MCU" * 100, b"CSR-dfu2" + b"\x00" * 50, _build_bcod([(0x401c0000, 0x540000, b"app" * 1000)])]
    container = _build_hui(secs)
    path = tempfile.mktemp(suffix=".HUI", dir=tmpdir)
    open(path, "wb").write(container)
    _data, parsed = ja.hui_sections(path)
    assert [x["id"] for x in parsed] == [0, 1, 2] and parsed[2]["data"][:4] == b"bCoD" and parsed[0]["version"] == "0.1.2.9"

    httpd = HTTPServer(("127.0.0.1", 0), _FakeBootloaderFlash)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    addr = f"127.0.0.1:{httpd.server_address[1]}"
    for mode in ("lean", "safari", "urllib"):
        _FakeBootloaderFlash.state.update(uploaded=None, flash=0, restarted=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ja.main(["--timeout", "2", "fwflash", addr, path, "--yes", "--upload", mode])
        text = out.getvalue()
        assert rc == 0 and "validation passed" in text and "new firmware: s9.7.5.9" in text and "flash: finished" in text and "has restarted" in text, (mode, text)
        assert _FakeBootloaderFlash.state["uploaded"] == secs[2], mode
    # wrong section is rejected by validation, never flashed
    _FakeBootloaderFlash.state.update(uploaded=None, flash=0, restarted=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ja.main(["--timeout", "2", "fwflash", addr, path, "--section", "0", "--yes"])
    assert rc == 1 and "invalid for this player" in out.getvalue(), out.getvalue()
    print("fwflash OK")


def test_fwstatus():
    addr = _serve(_FakeBootloader)
    rc, text = _run("--timeout", "2", "fwstatus", addr)
    assert rc == 0, text
    for want in ("aformNetFwHandler pollStatus=1", "transfer state: update failed, 0%", "validation: not ready yet; current firmware 1.29",
                 "aformFwUpdateProgessHandler pollStatus=1", "transfer state: downloading, 37%", "flash state: erasing flash, 50%"):
        assert want in text, (want, text)
    rc, text = _run("fwstatus", addr, "--handler", "aformNetFwHandler", "--poll", "1")
    assert rc == 0 and text.count("pollStatus=") == 1 and "update failed" in text, text
    rc, text = _run("fwstatus", addr, "--watch", "0.2", "--for", "0.7")
    lines = [l for l in text.splitlines() if l.strip()]
    assert rc == 0 and len(lines) == 4 and all(":" in l[:8] and "pollStatus=" in l for l in lines), text
    rc, text = _run("--timeout", "1", "fwstatus", "127.0.0.1:1")
    assert rc == 1 and "ConnectionRefusedError" in text or "URLError" in text, text
    print("fwstatus OK")


def test_fwhandlers():
    addr = _serve(_FakeBootloader)
    rc, text = _run("fwhandlers", addr)
    assert rc == 0, text
    assert "aformNetFwHandler: present" in text and "aformFwUpdateProgessHandler: present" in text, text
    assert "aformHandlerObtainConnStatus: not present" in text and "aformHandlerRefreshPage: not present" in text, text
    assert "aformHandlerRestartNotify" not in text, "the destructive handlers must not be probed by default"
    rc, text = _run("fwhandlers", addr, "aformHandlerRestartNotify", "nothing")
    assert rc == 0 and "aformHandlerRestartNotify: present" in text and "nothing: not present" in text, text
    print("fwhandlers OK")


def test_fwprepare():
    _FakeBootloader.seen.clear()
    addr = _serve(_FakeBootloader)
    rc, text = _run("fwprepare", addr, "--yes")
    assert rc == 0 and "the module reports that it restarted" in text and "state now: transfer state: update failed, 0%" in text, text
    assert ("POST", "aformHandlerSetNetFwUpdate", "readyStatus=0") in _FakeBootloader.seen
    print("fwprepare OK")


def test_fwinfo(tmpdir="/tmp"):
    import tempfile
    image = _build_bcod([(0x401c0000, 0x540000, b"app" * 500), (0, 0x10000, b"cfg" * 20), (0x40700000, 0xe0000, b"res" * 100)])
    container = _build_hui([b"MCU" * 100, b"CSR-dfu2" + b"\x00" * 51, image, b"dsp" * 33],
                           versions=[(9, 2, 1, 0), (3, 2, 1, 0), (9, 7, 5, 9), (9, 1, 0, 0)])
    good = tempfile.mktemp(suffix=".HUI", dir=tmpdir); open(good, "wb").write(container)
    rc, text = _run("fwinfo", good)
    assert rc == 0 and "all checksums OK" in text and "MISMATCH" not in text, text
    assert "version 0.1.2.9" in text and "section 2: version bytes 9.5.7.9" in text and "3 segment(s), 140 bytes of padding" in text, text
    assert text.count("crc32 ") == 3 and "load address 0x40700000" in text and "Bluetooth firmware" in text, text
    bad = bytearray(container); bad[-5] ^= 0x01
    badp = tempfile.mktemp(suffix=".HUI", dir=tmpdir); open(badp, "wb").write(bad)
    rc, text = _run("fwinfo", badp)
    assert rc == 1 and "section 3" in text and "checksum 0x" in text and "CHECKSUM MISMATCH" in text, text
    assert "file checksum" in text and text.count("MISMATCH") == 3, text   # file field, section 3, verdict
    bare = tempfile.mktemp(suffix=".bin", dir=tmpdir); open(bare, "wb").write(image)
    rc, text = _run("fwinfo", bare)
    assert rc == 0 and "bare Wi-Fi module image" in text and "all segment CRCs OK" in text, text
    bad = bytearray(image); bad[0xC0] ^= 0x01
    open(bare, "wb").write(bad)
    rc, text = _run("fwinfo", bare)
    assert rc == 1 and "segment 0" in text and "crc32 0x" in text and "CRC MISMATCH" in text, text
    other = tempfile.mktemp(suffix=".txt", dir=tmpdir); open(other, "wb").write(b"hello world")
    rc, text = _run("fwinfo", other)
    assert rc == 1 and "neither" in text, text
    assert ja.hui_checksum(b"\x01\x00\x00\x00\x02\x00\x00\x00") == (-3) & 0xFFFFFFFF
    assert ja.hui_checksum(b"\x01\x00\x00\x00\x02") == (-3) & 0xFFFFFFFF, "tail bytes are zero-padded"
    print("fwinfo OK")


def test_scan(port):
    assert ja.scan_subnet(hosts=["127.0.0.1"], port=port) == [("127.0.0.1", "JBL L16")]
    assert ja.probe("127.0.0.1", port=1) is None
    saved = ja.discover_ssdp, ja.discover_mdns, ja.scan_subnet
    ja.discover_ssdp = lambda *a, **k: [{"ip": "10.0.0.1", "location": "http://10.0.0.1/desc.xml", "authentics": False, "friendlyName": "router"}]
    ja.discover_mdns = lambda *a, **k: []
    ja.scan_subnet = lambda *a, **k: [("10.0.0.77", "JBL L16")]
    try:
        found = ja.discover(1.0)
    finally:
        ja.discover_ssdp, ja.discover_mdns, ja.scan_subnet = saved
    spk = [d for d in found if d["ip"] == "10.0.0.77"]
    assert len(found) == 2 and spk and spk[0]["authentics"] and spk[0]["friendlyName"] == "JBL L16" and spk[0]["service"] == "port 10025", found
    print("subnet scan OK")


def main():
    test_mdns_parsing()
    test_mdns_discovery()
    fake = FakeSpeaker()
    port = fake.start()
    test_scan(port)
    test_fwstatus()
    test_fwhandlers()
    test_fwprepare()
    test_fwinfo()
    test_fwflash()

    # --- unit checks ---------------------------------------------------------
    body = (b'<?xml version="1.0" encoding="UTF-8"?> <harman> <mm> <common> <control> '
            b'<name>query-status</name> <zone>Main Zone</zone> <para>volume</para> '
            b'</control> </common> </mm> </harman>')
    expected = (b"POST MM HTTP/1.1\r\nHost: :10025\r\nUser-Agent: Harman Remote Controller/1.0\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    assert ja.build_request("query-status", "volume") == expected
    assert ja.parse_bass_level("on||x@5:0") == {"manual_eq": "on", "bass": 5, "mid": 10, "high": 0, "raw": "on||x@5:0"}
    msgs, rest = ja.parse_messages(b"junk\r\n" + status("volume", "3") + status("power", "on")[:-20])
    assert [m["name"] for m in msgs] == ["volume"] and XML in rest and b"</harman>" not in rest
    assert ja.parse_spectrum(bytes([1, 0, 0, 255, 0x12, 0x34])) == [256, 255, 0x1234]
    print("unit checks OK")

    # --- CLI runs against the fake speaker ----------------------------------
    def run(*args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ja.main(["--host", "127.0.0.1", "--port", str(port), "--timeout", "1.5", *args])
        print(f"$ {' '.join(args)}  (rc={rc})\n{out.getvalue().rstrip()}\n")
        return out.getvalue()

    o = run("status"); assert "'20'" in o and "'optical1'" in o and "'mid': 5" in o and "'00:11:22:33:44:55'" in o
    o = run("source", "aux"); assert "'aux'" in o
    o = run("volume", "30"); assert "'30'" in o
    o = run("volume", "up"); assert "'31'" in o
    o = run("tone", "6", "10", "7"); assert "'bass': 6, 'mid': 10, 'high': 7" in o
    o = run("tone", "off"); assert "'manual_eq': 'off'" in o and "'bass': 5" in o
    o = run("clarifi", "on", "8"); assert "'on||8'" in o
    o = run("clarifi", "off"); assert "'off'" in o
    o = run("name", "JBL L16 Kitchen"); assert "'JBL L16 Kitchen'" in o
    o = run("spectrum"); assert "[256, 255, 4660, 128]" in o
    o = run("raw", "query-status", "MAC_address", "--wait", "0.5"); assert "00:11:22:33:44:55" in o
    o = run("power", "on"); assert "(no reply)" in o
    o = run("power", "on", "--alt"); assert "'on'" in o
    run("mute", "toggle")
    assert ("status", "power", "on") in fake.log and ("control", "power-on", "") in fake.log
    print(f"requests seen by fake speaker: {len(fake.log)}")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
