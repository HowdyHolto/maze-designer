#!/usr/bin/env python3
"""Talk to a JBL Authentics over its Bluetooth serial channel (SPP), the way the Android app did.

The speaker's main board answers on the Bluetooth serial-port profile even while its Wi-Fi module is
dead, so this works when the network tools cannot. Pair the speaker with the Mac first (System
Settings > Bluetooth, the device called "JBL L16 BT"); macOS then creates a serial device for it
under /dev/cu.* which `ports` lists.

    python3 jbl_bt.py ports                              # list serial devices, pick the JBL one
    python3 jbl_bt.py --port /dev/cu.JBLL16BT version
    python3 jbl_bt.py --port /dev/cu.JBLL16BT status
    python3 jbl_bt.py --port /dev/cu.JBLL16BT volume 20
    python3 jbl_bt.py --port /dev/cu.JBLL16BT raw 00 01

Frames are [command, sub-command, payload...] with no length prefix and no checksum; replies start
with the same command byte. See PROTOCOL.md section 5. Python 3 standard library only.
"""
import argparse
import glob
import os
import select
import sys
import termios
import time
import tty

CAPABILITIES = ["Device EQ", "Volume Control", "Wireless Network Setup", "Device Name Setup", "Firmware Upgrade",
                "Version query", "Room EQ", "Key event", "Alarm Sync", "Power Status control", "Series ID",
                "Bass Boost Control", "Source Switch", "Firmware Recovery Upgrade"]
SOURCES = {"dock": 0, "airplay": 1, "bluetooth": 2, "aux": 3, "optical": 4, "phono": 5, "dlna": 6, "tv": 7}
SOURCE_NAMES = {v: k for k, v in SOURCES.items()}
POWER = {0: "on", 1: "off", 2: "closing (the speaker is dropping the link)"}
USB_STATUS = {0: "update started", 1: "update rejected", 2: "error", 3: "USB drive present", 4: "no USB drive"}
TONE_BANDS = {"bass": 0x00, "mid": 0x07, "high": 0x08}
EXCLUDE = ("Bluetooth-Incoming-Port", "debug-console", "wlan-debug")


def list_ports():
    """Serial devices that could be the speaker's Bluetooth serial channel."""
    found = sorted(glob.glob("/dev/cu.*")) + sorted(glob.glob("/dev/rfcomm*")) + sorted(glob.glob("/dev/ttyUSB*"))
    return [p for p in found if not any(x in p for x in EXCLUDE)]


def guess_port():
    ports = list_ports()
    jbl = [p for p in ports if "jbl" in p.lower() or "l16" in p.lower() or "l8" in p.lower()]
    return (jbl or ports or [None])[0]


class SerialLink:
    """A raw serial connection built on termios, so no third-party package is needed."""

    def __init__(self, path, verbose=False):
        self.path, self.verbose = path, verbose
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[2] |= termios.CLOCAL | termios.CREAD
            attrs[4] = attrs[5] = termios.B115200      # ignored by Bluetooth, harmless elsewhere
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        except termios.error:
            pass                                       # a pseudo-terminal or an odd driver: keep going
        import fcntl
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, data):
        if self.verbose:
            print(f"  > {data.hex(' ')}", file=sys.stderr)
        os.write(self.fd, data)

    def read_frame(self, timeout=2.0, gap=0.15):
        """Bytes that arrive within `timeout`, extended while more keep coming within `gap` seconds."""
        buf = b""
        deadline = time.monotonic() + timeout
        while True:
            wait = (gap if buf else deadline - time.monotonic())
            if wait <= 0:
                break
            r, _w, _x = select.select([self.fd], [], [], wait)
            if not r:
                break
            chunk = os.read(self.fd, 4096)
            if not chunk:
                break
            buf += chunk
        if buf and self.verbose:
            print(f"  < {buf.hex(' ')}", file=sys.stderr)
        return buf

    def drain(self):
        while self.read_frame(0.05):
            pass

    def query(self, cmd, timeout=2.0):
        """Send a frame and return the first reply that starts with the same command byte (or b"")."""
        self.drain()
        self.write(bytes(cmd))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.read_frame(deadline - time.monotonic())
            if not frame:
                break
            if frame[0] == cmd[0]:
                return frame
            print(f"  (unsolicited: {frame.hex(' ')})", file=sys.stderr)
        return b""


def version_fields(rev):
    """The app's DeviceVersion.read: app version 4 bytes at 2, region 2 chars at 6, bootloader 4 bytes at 8,
    DSP 2 bytes at 10 (yes, overlapping the bootloader bytes, exactly as the app reads them)."""
    def ver(b):
        b = list(b)
        while b and b[0] == 0:
            b = b[1:]
        return ".".join(str(x) for x in b) if b else "0"
    out = {}
    if len(rev) >= 6:
        out["application"] = ver(rev[2:6])
    if len(rev) >= 8:
        out["region"] = rev[6:8].decode("ascii", "replace")
    if len(rev) >= 12:
        out["bootloader"] = ver(rev[8:12])
        out["dsp"] = ver(rev[10:12])
    return out


def capability_names(rev):
    """Bits of rev[2] (8 flags) then the low 4 bits of rev[3], in CAPABILITIES order, as the app maps them."""
    names = []
    if len(rev) >= 4:
        bits = [(rev[2] >> i) & 1 for i in range(8)] + [(rev[3] >> i) & 1 for i in range(4)]
        names = [n for n, b in zip(CAPABILITIES, bits) if b]
    return names


def show(label, frame, meaning=""):
    hx = frame.hex(" ") if frame else "(no reply)"
    print(f"{label:<14} {hx}" + (f"   {meaning}" if meaning else ""))


def cmd_ports(args, _link=None):
    ports = list_ports()
    if not ports:
        print("no serial devices found. Pair the speaker in System Settings > Bluetooth first; the device is "
              "called 'JBL L16 BT'. macOS creates /dev/cu.<name> for a paired device that offers a serial port.")
        return 1
    best = guess_port()
    for p in ports:
        print(f"{p}{'   <- likely the speaker' if p == best else ''}")
    return 0


def cmd_capabilities(args, link):
    rev = link.query([0x00, 0x01], args.timeout)
    show("capabilities", rev, ", ".join(capability_names(rev)) if rev else "")
    return 0 if rev else 1


def cmd_version(args, link):
    rev = link.query([0x06, 0x01], args.timeout)
    show("version", rev, "  ".join(f"{k} {v}" for k, v in version_fields(rev).items()) if rev else "")
    return 0 if rev else 1


def cmd_status(args, link):
    rc = 1
    rev = link.query([0x0B, 0x01], args.timeout)
    show("power", rev, POWER.get(rev[2], "?") if len(rev) > 2 else "")
    rc = 0 if rev else rc
    rev = link.query([0x02, 0x01], args.timeout)
    show("volume", rev, f"mute {rev[2]}, volume {rev[3]}" if len(rev) > 3 else "")
    rev = link.query([0x0E, 0x01], args.timeout)
    show("source", rev, SOURCE_NAMES.get(rev[2], f"code {rev[2]}") if len(rev) > 2 else "")
    rev = link.query([0x01, 0x01], args.timeout)
    show("eq mode", rev, f"mode {rev[3]}" if len(rev) > 3 else "")
    rev = link.query([0x04, 0x01], args.timeout)
    show("name", rev, rev[3:3 + rev[2]].decode("utf-8", "replace") if len(rev) > 3 else "")
    rev = link.query([0x03, 0x05], args.timeout)
    show("ip address", rev, rev[3:3 + rev[2]].decode("ascii", "replace") if len(rev) > 3 else "")
    rev = link.query([0x06, 0x01], args.timeout)
    show("version", rev, "  ".join(f"{k} {v}" for k, v in version_fields(rev).items()) if rev else "")
    return rc


def cmd_volume(args, link):
    v = int(args.value)
    if not 0 <= v <= 39:
        print("volume must be 0-39", file=sys.stderr)
        return 2
    link.write(bytes([0x02, 0x03, v]))
    time.sleep(0.3)
    rev = link.query([0x02, 0x01], args.timeout)
    show("volume", rev, f"mute {rev[2]}, volume {rev[3]}" if len(rev) > 3 else "")
    return 0


def cmd_mute(args, link):
    link.write(bytes([0x02, 0x04, 1 if args.state == "on" else 0]))
    time.sleep(0.3)
    rev = link.query([0x02, 0x01], args.timeout)
    show("volume", rev, f"mute {rev[2]}, volume {rev[3]}" if len(rev) > 3 else "")
    return 0


def cmd_source(args, link):
    link.write(bytes([0x0E, 0x03, SOURCES[args.name]]))
    time.sleep(0.5)
    rev = link.query([0x0E, 0x01], args.timeout)
    show("source", rev, SOURCE_NAMES.get(rev[2], f"code {rev[2]}") if len(rev) > 2 else "")
    return 0


def cmd_power(args, link):
    # the app sends the same bytes for on and off: it is a toggle
    link.write(bytes([0x0B, 0x03, 0x00, 0x20]))
    time.sleep(1.0)
    rev = link.query([0x0B, 0x01], args.timeout)
    show("power", rev, POWER.get(rev[2], "?") if len(rev) > 2 else "")
    return 0


def cmd_name(args, link):
    name = args.new_name.encode("utf-8")[:32]
    link.write(bytes([0x04, 0x03, len(name)]) + name)
    time.sleep(0.5)
    rev = link.query([0x04, 0x01], args.timeout)
    show("name", rev, rev[3:3 + rev[2]].decode("utf-8", "replace") if len(rev) > 3 else "")
    return 0


def cmd_eq(args, link):
    link.write(bytes([0x01, 0x03, int(args.mode)]))
    time.sleep(0.3)
    rev = link.query([0x01, 0x01], args.timeout)
    show("eq mode", rev, f"mode {rev[3]}" if len(rev) > 3 else "")
    return 0


def cmd_tone(args, link):
    if args.bass in ("off", "on"):
        link.write(bytes([0x0D, 0x04, 0x0A, 1 if args.bass == "on" else 0]))
    else:
        for band, value in zip(("bass", "mid", "high"), (args.bass, args.mid, args.high)):
            v = int(value)
            if not 0 <= v <= 10:
                print("levels are 0-10", file=sys.stderr)
                return 2
            link.write(bytes([0x0D, 0x04, TONE_BANDS[band], v]))
            time.sleep(0.2)
    for band in ("bass", "mid", "high"):
        rev = link.query([0x0D, 0x02, TONE_BANDS[band]], args.timeout)
        show(band, rev, f"level {rev[3]}" if len(rev) > 3 else "")
    return 0


def cmd_clarifi(args, link):
    level = int(args.level or 0)
    link.write(bytes([0x0D, 0x04, 0x05, 1 if args.state == "on" else 0, level]))
    time.sleep(0.3)
    rev = link.query([0x0D, 0x02, 0x05], args.timeout)
    show("clari-fi", rev, f"on {rev[3]}, level {rev[4]}" if len(rev) > 4 else "")
    return 0


def cmd_usb(args, link):
    """The app's 'has USB' check. On the JBL Pulse the same bytes start its Bluetooth firmware transfer,
    so the reply is decoded with both meanings; the Authentics app never sent it."""
    rev = link.query([0x05, 0x06], args.timeout)
    meaning = USB_STATUS.get(rev[2], f"code {rev[2]}") if len(rev) > 2 and rev[1] == 0x07 else ""
    show("usb", rev, meaning)
    return 0 if rev else 1


def cmd_raw(args, link):
    data = bytes(int(x, 16) for x in args.hexbytes)
    rev = link.query(list(data), args.timeout)
    show("reply", rev)
    return 0 if rev else 1


def cmd_monitor(args, link):
    print("printing everything the speaker sends; Ctrl-C to stop")
    try:
        while True:
            frame = link.read_frame(1.0)
            if frame:
                print(f"{time.strftime('%H:%M:%S')}  {frame.hex(' ')}", flush=True)
    except KeyboardInterrupt:
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", help="serial device (default: the /dev/cu.* entry with JBL in its name)")
    p.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for a reply")
    p.add_argument("-v", "--verbose", action="store_true", help="print raw traffic on stderr")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list serial devices").set_defaults(fn=cmd_ports, needs_port=False)
    sub.add_parser("capabilities", help="what the speaker says it supports").set_defaults(fn=cmd_capabilities)
    sub.add_parser("version", help="application, bootloader and DSP versions as the main board reports them").set_defaults(fn=cmd_version)
    sub.add_parser("status", help="power, volume, source, EQ mode, name, IP address, versions").set_defaults(fn=cmd_status)
    s = sub.add_parser("volume"); s.add_argument("value", help="0-39"); s.set_defaults(fn=cmd_volume)
    s = sub.add_parser("mute"); s.add_argument("state", choices=["on", "off"]); s.set_defaults(fn=cmd_mute)
    s = sub.add_parser("source"); s.add_argument("name", choices=sorted(SOURCES)); s.set_defaults(fn=cmd_source)
    sub.add_parser("power", help="toggle standby (the app sends the same bytes for on and off)").set_defaults(fn=cmd_power)
    s = sub.add_parser("name"); s.add_argument("new_name"); s.set_defaults(fn=cmd_name)
    s = sub.add_parser("eq", help="set the EQ mode number"); s.add_argument("mode"); s.set_defaults(fn=cmd_eq)
    s = sub.add_parser("tone", help="bass mid high (0-10 each), or on / off")
    s.add_argument("bass"); s.add_argument("mid", nargs="?"); s.add_argument("high", nargs="?"); s.set_defaults(fn=cmd_tone)
    s = sub.add_parser("clarifi", help="Clari-Fi on <level 0-9> | off"); s.add_argument("state", choices=["on", "off"]); s.add_argument("level", nargs="?"); s.set_defaults(fn=cmd_clarifi)
    sub.add_parser("usb", help="ask whether a USB drive is attached (see the docstring before using it)").set_defaults(fn=cmd_usb)
    s = sub.add_parser("raw", help="send any bytes, e.g. raw 00 01"); s.add_argument("hexbytes", nargs="+"); s.set_defaults(fn=cmd_raw)
    sub.add_parser("monitor", help="print every frame the speaker sends").set_defaults(fn=cmd_monitor)
    args = p.parse_args(argv)
    if args.cmd == "tone" and args.bass not in ("on", "off") and (args.mid is None or args.high is None):
        p.error("tone needs three levels: bass mid high, or on / off")
    if not getattr(args, "needs_port", True):
        return args.fn(args)
    port = args.port or guess_port()
    if not port:
        print("no serial device found; run 'python3 jbl_bt.py ports' after pairing the speaker", file=sys.stderr)
        return 1
    try:
        link = SerialLink(port, args.verbose)
    except OSError as exc:
        print(f"cannot open {port}: {exc}", file=sys.stderr)
        return 1
    try:
        return args.fn(args, link)
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
