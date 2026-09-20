# JBL Authentics L8 / L16 — open control tools

Tools for keeping the JBL Authentics L16 (and L8) usable after Harman abandoned the **JBL Music** app.
The control protocol was recovered from the last Android build of that app; see [`PROTOCOL.md`](PROTOCOL.md).

> **Status:** everything here was derived from the app's code and tested only against a simulated speaker.
> Nothing has been confirmed on a real L16 yet. The community Node‑RED flow confirmed volume, source
> selection and status queries on an L8, which shares the same firmware family. Treat every other
> command as "what the app sends" until you have seen your unit answer it.

What is in this folder:

| File | What it does |
|---|---|
| `PROTOCOL.md` | The reverse‑engineered protocol: discovery, framing, every command and status, Bluetooth channel, Wi‑Fi setup, firmware |
| `jbl_authentics.py` | Python library plus command‑line tool (no dependencies) |
| `jbl_ui.py` | Small local web UI, served from your Mac at `http://127.0.0.1:8765` |
| `fake_speaker.py` | A simulated speaker for developing without the real one |
| `test_fake_speaker.py` | End‑to‑end test of the library against the simulator |
| `test_ui.py` | End‑to‑end test of the web UI's backend against the simulator |

## Requirements

Python 3.8 or newer. On a Mac, `python3 --version` in Terminal will offer to install the Xcode command line tools if Python is missing. Nothing else to install.

## Quick start on the Mac

Double-click **`Start JBL UI.command`**. A Terminal window opens, stays open while the UI runs, and your browser opens the page.
The first time, macOS may refuse because the file came from a download: right-click it and choose **Open**, or go to
System Settings → Privacy & Security and click **Open Anyway**. Do not double-click `jbl_ui.py` itself; that only opens it in a text editor.

Or from Terminal:

```bash
cd jbl-authentics
python3 jbl_ui.py
```

A browser tab opens at `http://127.0.0.1:8765`. Click **Discover** (the speaker must be on the same Wi‑Fi) or type its IP, then **Connect**. The page shows power, source, volume, tone, Clari‑Fi, the device name and firmware version, and a log of every message sent and received.

Command line instead:

```bash
python3 jbl_authentics.py discover
python3 jbl_authentics.py --host 192.168.1.50 status
python3 jbl_authentics.py --host 192.168.1.50 source optical
python3 jbl_authentics.py --host 192.168.1.50 volume 20
python3 jbl_authentics.py --host 192.168.1.50 tone 6 5 7
python3 jbl_authentics.py --host 192.168.1.50 clarifi on 5
python3 jbl_authentics.py --host 192.168.1.50 raw query-status MAC_address
python3 jbl_authentics.py --host 192.168.1.50 monitor      # print everything the speaker sends
```

## Try it without a speaker

```bash
python3 fake_speaker.py            # terminal 1: simulated speaker on 127.0.0.1:10025
python3 jbl_ui.py --host 127.0.0.1 # terminal 2: the UI, already connected to it
python3 test_fake_speaker.py       # automated test of the library
python3 test_ui.py                 # automated test of the UI backend
```

## Verifying on the real speaker

Work through section 8 of `PROTOCOL.md`. The most useful first steps:

1. `python3 jbl_authentics.py discover` — confirms SSDP works and shows the UPnP description fields the app relied on.
2. `python3 jbl_authentics.py --host <ip> status` — confirms the framing and the reply formats.
3. `python3 jbl_authentics.py --host <ip> -v monitor` while turning the physical knobs — shows whether the speaker pushes status changes.
4. Power is the one command with conflicting evidence. Try **Power → On** in the UI both with and without the "status-element form" box ticked and note which one the speaker answers.

Please record what you find (raw log lines are ideal) in `PROTOCOL.md` so the next owner does not have to guess.

## Moving this into its own repository

This folder is self‑contained. To give it its own history:

```bash
git subtree split --prefix=jbl-authentics -b jbl-authentics-only
# then push that branch to a new empty repository
```

or simply copy the folder and `git init` inside it.

## Roadmap

- Confirm the protocol on real hardware and update `PROTOCOL.md`.
- Home Assistant integration (the `harman_kardon_avr` integration in HA core speaks the sibling `AVR` dialect and is a good template).
- Native iOS app: SwiftUI, `NWConnection` for the TCP channel, SSDP via `NWConnectionGroup` (needs the multicast networking entitlement) or Bonjour if the speaker also advertises itself.
- Mirror the last firmware images once someone recovers them from the old Harman index URL.

## Legal note

Interoperability work: the protocol facts were obtained by decompiling the vendor app, which the DMCA and the EU Software Directive permit for this purpose. No vendor code, assets or firmware are included here. JBL and Authentics are trademarks of Harman International; this project is not affiliated with Harman.
