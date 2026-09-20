"""Exercise the jbl_ui.py HTTP API against fake_speaker.py, all in one process.

    python3 test_ui.py
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbl_ui                                  # noqa: E402
from fake_speaker import FakeSpeaker           # noqa: E402


def main():
    fake = FakeSpeaker()
    spk_port = fake.start()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), jbl_ui.Handler)
    ui_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{ui_port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None, expect_ok=True):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with opener.open(req, timeout=20) as r:
                code, payload = r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            code, payload = e.code, json.loads(e.read())
        if expect_ok:
            assert code == 200 and payload.get("ok"), (path, code, payload)
        return code, payload

    # page
    with opener.open(base + "/", timeout=10) as r:
        html = r.read().decode()
    assert "<title>JBL Authentics</title>" in html and "/api/command" in html
    print("page OK")

    # not connected yet
    code, p = call("/api/status", expect_ok=False); assert code == 409, (code, p)
    code, p = call("/api/command", {"action": "volume", "value": 5}, expect_ok=False); assert code == 409
    # bad target
    code, p = call("/api/connect", {"target": "127.0.0.1:1"}, expect_ok=False); assert code == 502, (code, p)
    print("error paths OK")

    # connect and read status
    _, p = call("/api/connect", {"target": f"127.0.0.1:{spk_port}"})
    assert p["result"]["connected"] and p["result"]["target"] == f"127.0.0.1:{spk_port}"
    _, p = call("/api/status")
    s = p["result"]
    assert s["volume"] == "20" and s["source"] == "optical1" and s["tone"]["bass"] == 5 and s["sys_version"] == "200", s
    print("status OK:", {k: v for k, v in s.items() if k != "tone"})

    # commands
    _, p = call("/api/command", {"action": "source", "name": "phono"}); assert p["result"]["source"] == "phono"
    _, p = call("/api/command", {"action": "volume", "value": 25}); assert p["result"]["volume"] == "25"
    _, p = call("/api/command", {"action": "volume", "step": "down"}); assert p["result"]["volume"] == "24"
    _, p = call("/api/command", {"action": "tone", "bass": 8, "mid": 10, "high": 2}); assert p["result"]["tone"]["mid"] == 10 and p["result"]["tone"]["high"] == 2
    _, p = call("/api/command", {"action": "tone", "off": True}); assert p["result"]["tone"]["manual_eq"] == "off"
    _, p = call("/api/command", {"action": "clarifi", "on": True, "level": 7}); assert p["result"]["signal_doctor"] == "on||7"
    _, p = call("/api/command", {"action": "clarifi", "on": False}); assert p["result"]["signal_doctor"] == "off"
    _, p = call("/api/command", {"action": "name", "name": " Den "}); assert p["result"]["device_name"] == "Den"
    _, p = call("/api/command", {"action": "spectrum"}); assert p["result"]["spectrum"] == [256, 255, 0x1234, 128]
    _, p = call("/api/command", {"action": "power", "state": "on"}); assert p["result"]["power"] is None          # <control> form ignored by fake
    _, p = call("/api/command", {"action": "power", "state": "on", "alt": True}); assert p["result"]["power"] == "on"
    _, p = call("/api/command", {"action": "raw", "name": "query-status", "para": "MAC_address"})
    assert p["result"]["replies"] and p["result"]["replies"][0]["para"] == "00:11:22:33:44:55"
    code, p = call("/api/command", {"action": "bogus"}, expect_ok=False); assert code == 400
    print("commands OK")

    # log contains what we did, with increasing ids
    _, p = call("/api/state")
    log = p["result"]["log"]
    ids = [e["id"] for e in log]
    assert ids == sorted(ids) and any("source-selection" in e["m"] for e in log) and any("MAC_address" in e["m"] and e["d"] == "<" for e in log)
    print(f"log OK ({len(log)} entries)")

    # heartbeat happens without any request
    jbl_ui.SESSION.spk.last_beat -= 11
    time.sleep(1.6)
    assert any(n == "heart-alive" for _, n, _ in fake.log[-3:]), fake.log[-3:]
    print("heartbeat OK")

    # speaker goes away -> session notices
    fake.srv.close()
    jbl_ui.SESSION.spk.sock.close()
    time.sleep(1.5)
    _, p = call("/api/state")
    assert not p["result"]["connected"], p
    print("disconnect detection OK")
    print("ALL UI TESTS PASSED")


if __name__ == "__main__":
    main()
