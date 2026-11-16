# Changelog

## 1.0.0

First release. An unofficial, open-source desktop spell book for the **Harry Potter Magic Caster Wand** and its
**Magic Caster Box**, for people whose phone app no longer works.

### Highlights
- **Spell book interface** with seven pages: Devices, Spells, Teach, Practice, Cast, Lights and Notes.
- **Connects to the wand and base** over Bluetooth Low Energy, with automatic reconnection and live status
  (battery, lid, wand in base, USB power).
- **About 75 spells** with gesture diagrams and descriptions. Teach the book your own version of each spell by
  casting it three times, then **cast freely** with a live motion trace and history.
- **Practice mode** that favours the spells you find hard and learns from your mistakes.
- **Actions**: a recognised spell can press keys, run a program, open a web page, call a webhook or play a sound.
- **Wand's own recognition** is used where the wand provides it (Protego has been seen), alongside the book's.
- **Voice incantations (opt-in)**: say a spell's name, with or without a swish of the wand. Offline, nothing recorded.
- **System tray and background mode**, optional start with Windows, notifications.
- Lights, buzz, and synthesised page-turn sounds (three styles).

### Notes
- Windows 10/11 with Bluetooth LE. The EXE is unsigned, so Windows SmartScreen may ask you to confirm
  ("More info" then "Run anyway").
- Firmware updates are deliberately **not** implemented: flashing unknown firmware can permanently brick a device.
- Gesture and voice recognition were developed with one wand and mostly synthetic data. Expect to teach a few
  casts per spell and to adjust the sensitivity and voice confidence sliders.
- Unofficial; not affiliated with Warner Bros., the Wizarding World or the makers of the wand. Protocol and spell
  diagrams credit [eigger/hass-magic-caster-wand](https://github.com/eigger/hass-magic-caster-wand) (MIT).
