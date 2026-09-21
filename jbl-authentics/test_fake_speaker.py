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
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if self.path == "/goform/aformNetFwHandler" and body == "pollStatus=1":
            out = "1qwhgpstgriz1qwhgpstgriz1qwhgpstgriz8zirgtspghwq0qwhgpstgrizEndRes\n"
        elif self.path == "/goform/aformNetFwHandler" and body == "pollStatus=2":
            out = "2qwhgpstgriz1qwhgpstgriz2qwhgpstgriz1000zirgtspghwq1.29zirgtspghwqqwhgpstgrizEndRes\n"
        else:
            out = "qwhgpstgrizEndRes"
        data = out.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


def test_fwstatus():
    httpd = HTTPServer(("127.0.0.1", 0), _FakeBootloader)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ja.main(["--timeout", "2", "fwstatus", f"127.0.0.1:{httpd.server_address[1]}"])
    text = out.getvalue()
    assert rc == 0 and "transfer state: update failed, 0%" in text and "validation: not ready yet" in text and "current firmware: 1.29" in text, text
    print("fwstatus OK")


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
