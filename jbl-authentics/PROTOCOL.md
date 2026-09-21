# JBL Authentics L8 / L16 — control protocol notes

Reverse engineered from the Android **JBL Music 3.0** app (package `com.harman.jblmusicflow`, built 2017‑11‑17) plus the public Node‑RED flow for the L8 at https://github.com/erikwihlborg76/jbl-authentics.

**Confidence:** nothing in this document was tested against real hardware by its author. Items marked **[L8 verified]** were confirmed on an L8 by the Node‑RED author; everything else is exactly what the app's code sends and expects. Both models share one code path in the app; it tells them apart only by whether the UPnP `modelDescription` contains `L16` or `L8`, and the only UI difference is that the Phono source is shown for the L16.

Platform background: the Wi‑Fi side is an SMSC/Microchip **JukeBlox CX870‑3IB** module (DM870A, ARM926 running Linux). The control daemon speaks Harman's "HK API" family, the same XML‑over‑TCP scheme as Harman Kardon AVR/BDS products, with product category `MM`.

---

## 1. Discovery (SSDP)

The app binds local UDP port 12580, joins `239.255.255.250`, sets multicast TTL 4, and sends the following every 5 s, up to 6 times:

```
M-SEARCH * HTTP/1.1\r\n
MX: 3\r\n
HOST: 239.255.255.250:1900\r\n
MAN: "ssdp:discover"\r\n
ST: upnp:rootdevice\r\n
\r\n
```

A response is treated as an Authentics when **either**

* the raw SSDP response text contains `jbl_authentics` (case‑insensitive), **or**
* the `LOCATION` URL ends in `description.xml` or `dd.xml` and that document's `<modelName>` (or `<friendlyName>` when modelName is empty or `none`) contains `jbl_authentics`.

From the device description the app reads `friendlyName` (display name), `modelDescription` (must contain `L16` or `L8`), `modelName`, `manufacturer`, `manufacturerURL`. The speaker's IP is taken from the `LOCATION` URL; the third colon‑separated field of `USN` is kept as the UUID.

Display‑name clean‑up in the app suggests the factory names: Wi‑Fi friendly names of the form `JBL_L16_WF…` ("WF" = Wi‑Fi) and Bluetooth names containing `JBL L16`, with control‑capable Bluetooth names ending in `BT`.

The Node‑RED author skipped SSDP and resolved the hostname `JBL-L8` instead (the hostname is editable in the speaker's web UI on port 80).

---

## 2. Transport and framing

* **TCP port 10025**, one connection per session. The app uses a 15 s connect timeout and a 60 s read timeout and keeps the socket open while any control screen is visible.
* Requests are HTTP‑shaped but not HTTP. Exact bytes (each header line ends in CRLF, then a blank line, then the body with no trailing newline):

```
POST MM HTTP/1.1\r\n
Host: :10025\r\n
User-Agent: Harman Remote Controller/1.0\r\n
Content-Length: <byte length of body>\r\n
\r\n
<?xml version="1.0" encoding="UTF-8"?> <harman> <mm> <common> <control> <name>NAME</name> <zone>ZONE</zone> <para>PARA</para> </control> </common> </mm> </harman>
```

The app never fills in the Host IP, so `Host: :10025` is literally what it sends. `MM` is the product category (Harman AVRs use `AVR`, BDS players `HK_APP`). `ZONE` is `Main Zone` for everything except `heart-alive` and `bye-bye`, which use an empty zone. Parameters are not XML‑escaped by the app.

* **Responses** arrive on the same socket. The app reads up to 5120 bytes, splits on CRLF and takes the first line that starts with `<?xml version="1.0" encoding="UTF-8"?>`; it then substring‑searches `<name>`, `<zone>` and `<para>`. The SAX variant of the parser expects this shape:

```
<?xml version="1.0" encoding="UTF-8"?><harman><mm><common><status><name>volume</name><zone>Main Zone</zone><para>20</para></status></common></mm></harman>
```

Whether the speaker prefixes an HTTP‑style header line is unknown; scanning the stream for `<harman>…</harman>` handles both cases. Several messages can arrive in one read (the app only parses the first, which is a bug you should not copy).

* **Heartbeat:** once connected the app sends `heart-alive` (empty zone and para) every 10 s; the speaker answers with a status named `heart-alive`. After 3 unanswered beats the app declares the speaker gone. `bye-bye` exists in the command table (also empty zone) but the Authentics screens never send it.
* **Timing used by the app:** ~150 ms between consecutive queries, slider changes debounced by 100 ms, opening queries re‑sent every 200 ms until answered.

---

## 3. Commands the app sends to an Authentics

| Purpose | `<name>` | `<para>` | Notes |
|---|---|---|---|
| Power on / off | `power-on` / `power-off` | *(empty)* | Tablet UI only. **The Node‑RED author reports these do nothing on the L8**; sending a `<status>` element (instead of `<control>`) with name `power` and para `on`/`off` worked for him. Try both. |
| Select source | `source-selection` | `Airplay`, `Bluetooth`, `Dlna`, `OPTICAL1`, `AUX`, `Phono` | `OPTICAL1`, `Dlna` **[L8 verified]**. The "SPOTIFY/DLNA" button sends `Dlna`; Spotify Connect is not a selectable source, the app just opens Spotify. `Phono` only on the L16. |
| Volume step | `volume-up` / `volume-down` | *(empty)* | **[L8 verified]** |
| Volume absolute | `set_system_volume` | `0`…`39` | The app maps its 0–100 slider with round(p × 39 / 100). "Mute" in the app is just volume 0. |
| Mute | `mute-on` / `mute-off` / `mute-toggle` | *(empty)* | In the shared table but never sent by the Authentics screens. Unverified. |
| Tone: bass / mid / high | `set_bass_level` / `set_mid_level` / `set_high_level` | `0`…`10` | 5 = flat. Setting a level presumably switches manual EQ on; the app never sends an explicit "on". |
| Tone reset / manual EQ off | `set_manual_mode` | `off` | Sent by both the on/off switch and the "Restore" button. |
| Clari‑Fi ("signal doctor") | `signal_doctor_control` | `on\|\|<level>` or `off` | Two pipe characters. Level `0`…`9`, default 5. The app hides the level slider when `sys_version` is in 129…199. |
| Rename | `set_device_name` | new name | Factory names `JBL L16` / `JBL L8`; the app strips a leading `JBL L16 ` for display. |
| Heartbeat | `heart-alive` | *(empty, zone empty)* | every 10 s |
| Query | `query-status` | see below | one query per message |

`query-status` parameters the Authentics screens use: `power`, `volume`, `source`, `bass_level`, `signal_doctor`, `spectrum_data`, `device_name`, `sys_version`. Defined in the table but unused for this product: `mute`, `Manual_EQ`, `MAC_address`, `playback`, `battery_level`, `eq_mode`.

The shared table also carries AVR/BDS names (`play`, `pause`, `next`, `previous`, `forward`, `reverse`, `home`, `up`, `down`, `left`, `right`, `ok`, `back`, `options`, `settings`, `sleep`, `standby`, `info`, `set_eq_mode` with `Stereo Widening`/`Jazz`/`Rock`/`Gaming`/`Basic`, …). No Authentics screen sends them; the speaker may or may not accept them.

---

## 4. Status messages the app understands

| `<name>` | `<para>` | Notes |
|---|---|---|
| `power` | `on` / `off` | compared case‑insensitively |
| `volume` | integer `0`…`39` | |
| `source` | `bluetooth`, `airplay`, `dlna`, `optical1`, `aux`, `phono` | compared lower‑cased |
| `bass_level` | `on\|\|<ignored>@<b><m><h>` | text before `\|\|` is the manual‑EQ state (`on`/`off`); after `@` three single characters give bass, mid, high as `0`…`9`, with `:` meaning 10. The app ignores whatever sits between `\|\|` and `@`; capture a real reply to learn what it is. |
| `signal_doctor` | `off` or `on\|\|<level>` | |
| `spectrum_data` | binary | the para's raw bytes taken in pairs, big‑endian, one 16‑bit value per band. The app polls this every 300 ms while the Clari‑Fi screen is open and draws however many bands it receives. |
| `sys_version` | integer string, e.g. `129`, `200` | firmware version with the dot removed |
| `device_name` | string | |
| `heart-alive` | | heartbeat acknowledgement |
| `MAC_address`, `mute`, `Manual_EQ` | | queryable per the table, never parsed by the Authentics screens |

---

## 5. Bluetooth control channel (SPP, Android only)

iOS apps cannot open Bluetooth Classic serial links without Apple's MFi program, so the iOS app almost certainly used Wi‑Fi only. The Android app opens RFCOMM with the standard SPP UUID `00001101-0000-1000-8000-00805F9B34FB` to the paired speaker whose name contains `JBL L16` / `JBL L8`, and exchanges raw frames with **no length prefix and no checksum**: `[command_id, sub_id, payload…]`. Replies start with the same `command_id`.

| Function | Send (hex) | Reply |
|---|---|---|
| Capability bitmap | `00 01` | `00 xx b1 b2 b3`; bit flags in order: Device EQ, Volume Control, Wireless Network Setup, Device Name Setup, Firmware Upgrade, Version query, Room EQ, key event (byte 1); Alarm Sync, Power Status control, Series ID, Bass Boost Control (byte 2, low bits) |
| Query volume/mute | `02 01` | `02 xx <mute> <volume 0–39>` |
| Set volume | `02 03 <vol>` | |
| Mute on / off | `02 04 01` / `02 04 00` | |
| Query name | `04 01` | `04 xx <len> <name bytes>` |
| Set name | `04 03 <len> <name bytes>` | |
| Query version | `06 01` | `06 xx a b c d rr rr bl bl bl bl …`; app version 4 bytes, region 2, bootloader 4, DSP 2 (the app reads DSP from offset 10, overlapping the bootloader bytes) |
| Key events | `08 02 00 02` vol+, `08 02 00 01` vol−, `08 02 00 11` mute, `08 02 00 1A` bass+, `08 02 00 19` bass− | |
| Power | query `0B 01` → `0B xx <0 on, 1 off, 2 closing>`; `0B 03 00 20` on/off (identical bytes, i.e. a toggle); `0B 03 01 20` / `0B 03 02 20` long‑press down / up | |
| Query EQ setting | `0D 02 <type>` | `0D xx <type> <value…>` |
| Set EQ setting | `0D 04 <type> <value…>` | types: `00` bass, `07` mid, `08` high (values 0–10); `05` Clari‑Fi, payload `<on 0/1> <level 0–9>`; `06` spectrum, reply `<count> <hi lo>×count`; `0A` tone on/off `<0/1>` |
| Query / set source | `0E 01` → `0E xx <src>`; `0E 03 <src>` | src: 0 Dock, 1 AirPlay/DLNA, 2 Bluetooth, 3 Aux, 4 Optical, 5 Phono, 6 DLNA, 7 TV |
| Wi‑Fi setup ("Easy setup through BT") | `03 01` list networks → `03 02 <count>` then one `03 03 <id> <ssid_len> <ssid> <enc> <auth> <wep_idx> <pw_len> <pw>` per network; join with `03 04 <ssid_len> <ssid> <enc> <auth> <wep_idx> <pw_len> <pw>`; `03 05` → `03 06 <len> <ip string>` | password ≤ 64 bytes; `enc` 0 = open network |
| Firmware over BT | `05 06` trigger / USB check → `05 07 <0 start, 1 reject, 2 error (+timeout byte), 3 has USB, 4 no USB>`; `05 01` + packet count, file size, CRC32 (each 4 bytes big‑endian); `05 02 <pkt# 4 bytes BE> <128 data bytes>` → `05 03 <4 bytes> <ok flag>`; result `05 09 <0 fail, 1 ok, 2 error>` | This is the JBL Pulse mechanism; the Authentics screens only describe USB‑stick updates |

---

## 6. Getting the speaker onto Wi‑Fi without the app

The app offers three methods for the Authentics:

1. **Easy setup (through BT)** — the SPP `03 01` / `03 04` messages above (Android only).
2. **Manual setup** — press the Wi‑Fi button on the speaker, join the hotspot it raises, open its web‑based setup page in a browser. The app merely opens the browser; no app needed.
3. **WPS** — push‑button on speaker and router, or PIN mode by long‑pressing the WPS button and entering the speaker's PIN in the router's UI.

Methods 2 and 3 need no app at all, so new owners are never locked out by the app's disappearance.

---

## 7. Firmware updates

* Version index: `http://storage.harman.com/Authentics/Authentics_L16_upgrade_index.xml` (L8: `Authentics_L8_upgrade_index.xml`). The document contains a `<Release ID="x.yy">` element; the app compares `ID` with the dot removed against `sys_version`. An HTTP 404 is treated as "already up to date".
* Procedure the app shows: download the file from `www.JBL.com/JBL/Authentics` to a USB drive, plug it into the speaker, hold **Power + Source for 5 s**, wait for the speaker to update and switch itself off.
* JBL's support note says units that shipped without Spotify Connect had to be updated at a service centre, so there is a firmware/hardware split. Record your unit's `sys_version` and keep any `.bin` you can still find (try the Wayback Machine for the index URL and the download page).

---

## 7b. Bootloader web page and firmware upload over HTTP (observed on a real L16)

When the JukeBlox module's main firmware is not running, port 80 serves a page titled `Bl_Index` (bootloader index) with only a "Current status / IP address" box and an "Update Your Products Firmware" form, and every other port (10025, AirPlay 5000/7000, UPnP 8080, 8889) refuses connections. Bluetooth keeps working because it is a separate chip. The server is GoAhead (`/goform/…` handlers); the page includes `images/Brand-Icon-Microchip.png` and the script `airplayRelJavScr.js`, which holds the update logic below.

**Upload:** `POST /goform/aformNetFwUpdateHandler`, `multipart/form-data`, file field name `appFirmware`. The page submits it into a hidden iframe, then drives the state machine by polling.

**Polling:** `POST /goform/aformNetFwHandler` with body `pollStatus=N` (`application/x-www-form-urlencoded`). Replies are text fields joined by the separator `qwhgpstgriz`: `type`, `number of flags`, the flags (the first flag is the reply kind), the data, and the literal `EndRes`. Data fields are joined by `zirgtspghwq`. A bare `GET` returns `qwhgpstgrizEndRes`.

| `pollStatus` | Reply kind | Data | Meaning |
|---|---|---|---|
| `1` | 1 | `<state>zirgtspghwq<percent>` | transfer progress; state 0 idle, 1 started, 2 downloading, 3 download complete, 4 verifying image, 5 download update flash, 6 download update done, 7 download failed, 8 update failed. The page repeats `1` until percent is 100, then sends `2`. |
| `2` | 2 | `<code>zirgtspghwq<CurFw>zirgtspghwq<NewFw>` | validation of the uploaded image; code 0 or 1 accepted (the page then shows "CurFw / NewFw" and asks to confirm), 2 invalid for this player, 3–5 invalid, 999 no multipart upload received, 1000 not ready, poll again |
| `3` | 3 | `1` | confirm: start flashing |
| `4` | 4 | `<state>zirgtspghwq<percent>` | flash progress; 0 not started, 1 erasing, 2 burning, 3 finished. On 3 the page polls `POST /goform/aformHandlerRestartNotify` with `pollStatus=0` every 1.5 s until the reply type is 7 ("System Restarted") and reloads. |

`python3 jbl_authentics.py fwstatus <ip>` sends `1` and `2` and decodes the answers without uploading anything. The manual's USB procedure (file in the root of a USB stick in the top "iPad" USB port, hold Power + Source for five seconds) is the other way in, and needs the same file. The bootloader rejects images meant for another player, so an L8 image should fail validation rather than brick an L16, but do not rely on that.

## 8. Things to verify on real hardware

1. Whether `power-on` / `power-off` work as `<control>` or only as a `<status>` element.
2. The exact framing of replies (header line before the XML or not) and whether the speaker ever pushes unsolicited status when a physical knob or button is used (`monitor` in the reference client).
3. The unknown field between `||` and `@` in `bass_level`.
4. Band count and scaling of `spectrum_data`.
5. Whether `mute-on/off/toggle`, `MAC_address`, `Manual_EQ` and the AVR‑style transport commands are accepted.
6. The UPnP `description.xml` contents (`friendlyName`, `modelName`, `modelDescription`), which the app relies on for identification.
7. What the speaker's web UI on port 80 exposes, and whether the JukeBlox HTTP API on port 8889 that Philips Fidelio speakers expose is present.

---

## 9. Provenance

Derived from reading the decompiled JBL Music 3.0 Android app and the public Node‑RED flow linked above. No vendor code or assets are reproduced here; the byte strings and XML above are protocol facts needed for interoperability.
