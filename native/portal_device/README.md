# Physical portals

Status: milestones 1–3 of the "any real portal" goal are implemented, but they
have **not been tested on hardware**. No portal was attached while this was
written.

## Layout

- `native/portal_device/protocol.*`: the report protocol shared by every
  portal: reset `R`, activate `A`, status `S`, query `Q`, write `W`, colour
  `C`, Trap Team speaker `M`. It also holds the firmware-id table that names
  the model from the reset reply.
- `native/portal_device/transports.cpp`: transports.
  - `hid`: PS3/PS4/Wii/Wii U portals, `1430:0150`, through
    `native/platform/hid.hpp` (hidraw on Linux, the Windows HID API in
    `hid_windows.cpp`, which has not been built or tested yet).
  - `xbox`: Xbox 360 portals over libusb, with a two-byte frame header
    removed. The header values are unconfirmed, and frames that don't match
    are logged. Xbox One portals are detected but refused: their GIP
    handshake has not been recorded.
- `native/portal_device/virtual_transport.cpp`: the virtual portal (the
  Cemu portal core used by `SKY_VIRTUAL_PORTAL`) behind the same interface.
- `native/hle/real_portal_bus.*`: libSceUsbd for the game, backed by the
  chosen portal. The game sees that device's own USB descriptors (read
  from sysfs) and HID report descriptor. Nothing is invented: string
  descriptors aren't available through hidraw, so requests for them fail.
- `skylanders-portal-list [--identify]`: JSON list of connected portals.
  `--identify` resets each portal to read its model and capabilities.

## Using a portal

```
python3 tools/run_session.py --list-portals
python3 tools/run_session.py --portal-device auto            # or hid:/dev/hidrawN
```

The launcher's Portal page also has a choice between real portals and the
virtual one. Without access to the device, install the udev rule:

```
python3 tools/portal_devices.py --udev-rule | sudo tee /etc/udev/rules.d/70-skylanders-portals.rules
sudo udevadm control --reload && sudo udevadm trigger
```

## Figure writes

Writes to real figures are refused unless `--allow-figure-writes` is given
(`SKY_PORTAL_FIGURE_WRITES=1`). Before the first write to a figure in a
session, the bus reads all 64 blocks and saves them, with mode 0600, to
`$XDG_DATA_HOME/skylanders-pc/portal-backups/<uid>-<time>.sky` (folder mode
0700). If the backup fails, the write is refused. These files are private
figure data and must never be tracked.

## Tests

`native/tests/test_portal_device.cpp` replays the synthetic transcript
`native/tests/data/portal_transcript_hid.txt`, which holds no figure contents,
through the protocol core and the USB bus. `tests/test_portal_devices.py`
covers detection against a fake sysfs and the launcher choice.

## Not done yet

- Hardware confirmation of the USB ids (`lsusb`) and the firmware-id table.
- Traps and the portal speaker on a real Trap Team portal. Audio is passed
  through, but nobody has listened to it.
- Xbox portals in game. The PS4 game opens `1430:0150`; an Xbox portal has
  a different identity, and presenting it as `0150` would fake it.
- Mixed mode (a real portal plus virtual figures), hot-plug recovery, and
  building and testing on Windows.
