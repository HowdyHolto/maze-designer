# Where things stand (evening of 2026-09-20)

## The speaker
- JBL Authentics L16 at 10.0.0.51 (MAC A4:DB:30:A9:C8:1B, name `JBL_L16_WF`). Bluetooth works ("JBL L16 BT").
- The Wi-Fi module (SMSC/Microchip JukeBlox CX870) is stuck in its bootloader: only port 80 answers, serving the
  bootloader page `Bl_Index`. No AirPlay, DLNA, Spotify or control port (10025) until the module runs its application.
- The main board is now at firmware 1.2.9 (it was 2.3.7 when we started; the USB update downgraded it).

## What was tried
- Web upload through the bootloader page, with the module image extracted from `JBL_L16.HUI` (browser, urllib,
  hand-built HTTP/1.0, browser-identical request, 100 KB test): every attempt ends in "download failed" at 0 % with
  the connection closed, from the idle state too. Validation afterwards reports "file invalid" (code 5).
- USB-stick update (FAT32, MBR, `JBL_L16.HUI` in the root, top USB port, Power + Source 5 s), twice. Each run takes
  about 30 minutes; the module drops off Wi-Fi during it and comes back reset, in the bootloader, state idle.
  After run 1 there was no `JBL_L16_Version_Log.txt` on the stick. Run 2's stick has not been checked yet.
- The firmware file is verified intact: container checksum (negative sum of 32-bit words), all four section checksums,
  and the module image's three internal CRC-32s all match (`python3 jbl_authentics.py fwinfo JBL_L16.HUI`).

## Two explanations remain
1. The module receives the image but refuses or fails to store it (flash fault or a stuck persistent state).
2. The main board skips the module step, e.g. it treats the module's stored firmware as newer than the 1.2.9 file.

## Tomorrow, in this order
1. Check the stick from run 2 for `JBL_L16_Version_Log.txt`; paste its contents if it exists.
2. Pair the Mac with "JBL L16 BT" (System Settings > Bluetooth), then in the folder:
   `python3 jbl_bt.py ports`, then `python3 jbl_bt.py --port /dev/cu.<the JBL entry> version` and `... status`.
   Paste the output with the raw bytes. This asks the main board what versions it believes are installed, over the
   one channel that works without the module. `jbl_bt.py` has only been tested against a simulated speaker.
3. Decide from that which explanation holds, then pick the next step: Bluetooth-side diagnostics, more bootloader-page
   experiments (`fwhandlers`, `fwstatus --watch`), or, as a last resort, the module's serial console inside the speaker.

## Tools in this folder (all committed on branch `claude/reverse-engineer-speaker-app-627yvx`)
- `jbl_authentics.py`: discover, probe, status and control over TCP 10025, web, fwinfo, fwstatus (`--watch`, both
  update handlers), fwhandlers, fwflash, fwprepare (experimental).
- `jbl_ui.py` (+ `Start JBL UI.command`): local web UI on http://127.0.0.1:8765.
- `jbl_bt.py`: Bluetooth serial client (capabilities, version, status, volume, mute, source, power, name, eq, tone,
  clarifi, usb, raw, monitor).
- `fake_speaker.py`, `test_fake_speaker.py`, `test_ui.py`, `test_bt.py`: simulator and tests, all passing.
- `PROTOCOL.md`: everything learned about the protocol, the bootloader page, the firmware file and the update sequence.

## Kept for later
- Standby auto-off: the module's full firmware has a "Standby Mode" switch (config key `WakeOnOnlyAirplay`,
  handler `aformHandlerConfigureStandByMode`); the phono dongle can be handled by `power-on` + `source-selection Phono`
  from an automation once the control port is back.
- Open app roadmap: Python library (done) -> Home Assistant -> iOS.
