"""Test of jbl_bt.py against a fake speaker on a pseudo-terminal (no Bluetooth needed).

    python3 test_bt.py
"""
import contextlib
import io
import os
import pty
import select
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbl_bt  # noqa: E402


class FakeBtSpeaker(threading.Thread):
    """Answers the Android app's frames the way PROTOCOL.md section 5 describes them."""

    def __init__(self, master_fd):
        super().__init__(daemon=True)
        self.fd = master_fd
        self.volume, self.mute, self.source, self.power, self.eq = 12, 0, 2, 0, 1
        self.dev_name = b"JBL L16 BT"   # not .name: that is the thread name
        self.tone = {0x00: 5, 0x07: 5, 0x08: 5}
        self.clarifi = (1, 5)
        self.log = []

    def reply(self, cmd):
        if cmd[:2] == b"\x00\x01":
            return bytes([0x00, 0x02, 0b00111111, 0b0011, 0x00])
        if cmd[:2] == b"\x06\x01":
            return bytes([0x06, 0x02, 0, 1, 2, 9]) + b"US" + bytes([0, 0, 0, 3]) + bytes([1, 9])
        if cmd[:2] == b"\x0b\x01":
            return bytes([0x0B, 0x02, self.power])
        if cmd[:2] == b"\x0b\x03":
            self.power ^= 1
            return b""
        if cmd[:2] == b"\x02\x01":
            return bytes([0x02, 0x02, self.mute, self.volume])
        if cmd[:2] == b"\x02\x03":
            self.volume = cmd[2]
            return b""
        if cmd[:2] == b"\x02\x04":
            self.mute = cmd[2]
            return b""
        if cmd[:2] == b"\x0e\x01":
            return bytes([0x0E, 0x02, self.source])
        if cmd[:2] == b"\x0e\x03":
            self.source = cmd[2]
            return b""
        if cmd[:2] == b"\x01\x01":
            return bytes([0x01, 0x02, 0, self.eq])
        if cmd[:2] == b"\x01\x03":
            self.eq = cmd[2]
            return b""
        if cmd[:2] == b"\x04\x01":
            return bytes([0x04, 0x02, len(self.dev_name)]) + self.dev_name
        if cmd[:2] == b"\x04\x03":
            self.dev_name = cmd[3:3 + cmd[2]]
            return b""
        if cmd[:2] == b"\x03\x05":
            ip = b"10.0.0.51"
            return bytes([0x03, 0x06, len(ip)]) + ip
        if cmd[:2] == b"\x0d\x02":
            if cmd[2] == 0x05:
                return bytes([0x0D, 0x03, 0x05, *self.clarifi])
            return bytes([0x0D, 0x03, cmd[2], self.tone.get(cmd[2], 0)])
        if cmd[:2] == b"\x0d\x04":
            if cmd[2] == 0x05:
                self.clarifi = (cmd[3], cmd[4])
            elif cmd[2] == 0x0A:
                self.tone = {k: 5 for k in self.tone} if cmd[3] == 0 else self.tone
            else:
                self.tone[cmd[2]] = cmd[3]
            return b""
        if cmd[:2] == b"\x05\x06":
            return bytes([0x05, 0x07, 0x04])
        return b""

    def run(self):
        while True:
            r, _w, _x = select.select([self.fd], [], [], 0.5)
            if not r:
                continue
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                return
            if not data:
                return
            self.log.append(data)
            out = self.reply(data)
            if out:
                os.write(self.fd, out)


def run(port, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = jbl_bt.main(["--port", port, "--timeout", "1.0", *args])
    print(f"$ {' '.join(args)}  (rc={rc})\n{out.getvalue().rstrip()}\n")
    return rc, out.getvalue()


def main():
    master, slave = pty.openpty()
    port = os.ttyname(slave)
    fake = FakeBtSpeaker(master)
    fake.start()

    rc, o = run(port, "capabilities")
    assert rc == 0 and "Device EQ, Volume Control, Wireless Network Setup, Device Name Setup, Firmware Upgrade, Version query" in o and "Alarm Sync, Power Status control" in o and "Series ID" not in o, o
    rc, o = run(port, "version")
    assert rc == 0 and "application 1.2.9" in o and "region US" in o and "bootloader 3" in o and "dsp 3" in o, o   # the app reads DSP from offset 10, inside the bootloader bytes
    rc, o = run(port, "status")
    assert rc == 0 and "power" in o and "on" in o and "mute 0, volume 12" in o and "bluetooth" in o and "mode 1" in o and "JBL L16 BT" in o and "10.0.0.51" in o, o
    rc, o = run(port, "volume", "25"); assert rc == 0 and "volume 25" in o, o
    rc, o = run(port, "mute", "on"); assert rc == 0 and "mute 1" in o, o
    rc, o = run(port, "source", "aux"); assert rc == 0 and "aux" in o, o
    rc, o = run(port, "power"); assert rc == 0 and "off" in o, o
    rc, o = run(port, "name", "Kitchen L16"); assert rc == 0 and "Kitchen L16" in o, o
    rc, o = run(port, "eq", "3"); assert rc == 0 and "mode 3" in o, o
    rc, o = run(port, "tone", "7", "4", "6"); assert rc == 0 and "level 7" in o and "level 4" in o and "level 6" in o, o
    rc, o = run(port, "tone", "off"); assert rc == 0 and o.count("level 5") == 3, o
    rc, o = run(port, "clarifi", "on", "8"); assert rc == 0 and "on 1, level 8" in o, o
    rc, o = run(port, "usb"); assert rc == 0 and "no USB drive" in o, o
    rc, o = run(port, "raw", "06", "01"); assert rc == 0 and "06 02 00 01 02 09" in o, o
    rc, o = run(port, "raw", "7f", "01"); assert rc == 1 and "(no reply)" in o, o
    assert b"\x02\x03\x19" in fake.log and b"\x0e\x03\x03" in fake.log and b"\x04\x03\x0bKitchen L16" in fake.log, fake.log
    # helpers
    assert jbl_bt.version_fields(bytes([6, 2, 0, 0, 0, 5, 69, 85, 0, 0, 0, 2, 0, 7])) == {"application": "5", "region": "EU", "bootloader": "2.0.7", "dsp": "7"}
    assert jbl_bt.capability_names(bytes([0, 2, 0x81, 0x08])) == ["Device EQ", "Key event", "Bass Boost Control"]
    rc, o = run(port, "ports")
    assert rc in (0, 1), o
    print("ALL BLUETOOTH TESTS PASSED")


if __name__ == "__main__":
    main()
