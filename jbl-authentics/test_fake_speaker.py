"""End-to-end test of jbl_authentics.py against fake_speaker.py on localhost.

    python3 test_fake_speaker.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbl_authentics as ja           # noqa: E402
from fake_speaker import FakeSpeaker, XML, status  # noqa: E402


def main():
    fake = FakeSpeaker()
    port = fake.start()

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
