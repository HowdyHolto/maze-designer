#!/usr/bin/env python3
"""
fake_speaker.py - a stand-in JBL Authentics for developing without the real one.

    python3 fake_speaker.py              # listens on 127.0.0.1:10025
    python3 fake_speaker.py --port 20025

It answers the same XML status messages the real speaker is expected to send,
keeps volume/source/tone/Clari-Fi/name state, and ignores power-on/power-off
sent as <control> (which is what was reported for the real L8) while honouring
the <status> form. Also importable: FakeSpeaker().start() returns the port.
"""
import argparse
import re
import socket
import threading

XML = b'<?xml version="1.0" encoding="UTF-8"?>'


def status(name, para, zone=b"Main Zone"):
    if isinstance(para, str):
        para = para.encode()
    if isinstance(name, str):
        name = name.encode()
    return (XML + b"<harman><mm><common><status><name>" + name + b"</name><zone>" + zone +
            b"</zone><para>" + para + b"</para></status></common></mm></harman>\r\n")


def _lv(v):
    return ":" if v == 10 else str(v)


class FakeSpeaker:
    def __init__(self, host="127.0.0.1", port=0, verbose=False):
        self.host, self.port, self.verbose = host, port, verbose
        self.state = {"volume": 20, "source": "optical1", "power": "off", "bass": 5, "mid": 5,
                      "high": 5, "manual": "on", "sd": "on||5", "name": "JBL L16", "ver": "200"}
        self.log = []          # (element, name, para) for every request received
        self.srv = None

    def start(self):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((self.host, self.port))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()
        return self.port

    def _accept(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _reply(self, elem, name, para):
        s = self.state
        if name == "heart-alive":
            return status("heart-alive", "", zone=b"")
        if name == "query-status":
            table = {
                "volume": str(s["volume"]), "source": s["source"], "power": s["power"],
                "bass_level": f"{s['manual']}||bass@{_lv(s['bass'])}{_lv(s['mid'])}{_lv(s['high'])}",
                "mute": "off", "manual_EQ": s["manual"], "eq_mode": "off",
                "signal_doctor": s["sd"], "device_name": s["name"], "sys_version": s["ver"],
                "MAC_address": "00:11:22:33:44:55",
                "spectrum_data": bytes([0x01, 0x00, 0x00, 0xff, 0x12, 0x34, 0x00, 0x80]),
            }
            if para in table:
                # Real replies may carry an HTTP-style header; clients must cope with it.
                return b"HTTP/1.1 200 OK\r\n\r\n" + status(para, table[para])
            return b""
        if name == "set_system_volume":
            s["volume"] = max(0, min(39, int(para)))
        elif name == "volume-up":
            s["volume"] = min(39, s["volume"] + 1)
        elif name == "volume-down":
            s["volume"] = max(0, s["volume"] - 1)
        elif name == "source-selection":
            s["source"] = para.lower()
        elif name in ("set_bass_level", "set_mid_level", "set_high_level"):
            s[name.split("_")[1]] = int(para)
            s["manual"] = "on"
        elif name == "set_manual_mode" and para == "off":
            s.update(bass=5, mid=5, high=5, manual="off")
        elif name == "signal_doctor_control":
            s["sd"] = para
        elif name == "set_device_name":
            s["name"] = para
        elif name == "power" and elem == "status":
            s["power"] = para
            return status("power", para)
        # power-on / power-off via <control>: deliberately ignored, as reported for the L8
        return b""

    def _handle(self, conn):
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"</harman>" in buf:
                idx = buf.index(b"</harman>") + len(b"</harman>")
                req, buf = buf[:idx], buf[idx:]
                name = re.search(rb"<name>(.*?)</name>", req)
                para = re.search(rb"<para>(.*?)</para>", req)
                if not name:
                    continue
                name = name.group(1).decode()
                para = para.group(1).decode() if para else ""
                elem = "status" if b"<status>" in req else "control"
                self.log.append((elem, name, para))
                if self.verbose and name != "heart-alive":
                    print(f"<- {elem} {name} {para!r}")
                out = self._reply(elem, name, para)
                if out:
                    try:
                        conn.sendall(out)
                    except OSError:
                        return


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=10025)
    p.add_argument("--bind", default="127.0.0.1")
    args = p.parse_args()
    fake = FakeSpeaker(args.bind, args.port, verbose=True)
    port = fake.start()
    print(f"fake JBL Authentics listening on {args.bind}:{port}  (Ctrl-C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
