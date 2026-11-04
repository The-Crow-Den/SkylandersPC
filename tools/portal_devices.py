# SPDX-License-Identifier: GPL-3.0-or-later
"""Physical Portal of Power detection for the launcher and run_session.

Listing only reads sysfs; it never sends a report, so the portal is not reset.
The native `skylanders-portal-list --identify` reads each portal's model."""
import os
from pathlib import Path

VIRTUAL = 'virtual'
AUTO = 'auto'
ACTIVISION = 0x1430
# Unconfirmed on the user's hardware: 0x0150 is the HID portal used by
# PS3/PS4/Wii/Wii U; 0x1f17 is reported for the Xbox 360 wired portal.
HID_PORTAL = 0x0150
XBOX360_PORTAL = 0x1F17
UDEV_RULE_NAME = '70-skylanders-portals.rules'
# Gives the logged-in user (systemd uaccess) access to portals: the hidraw node
# of HID portals, and the raw USB device of Xbox portals for libusb.
UDEV_RULE = '''# Skylanders Portal of Power access for the logged-in user.
KERNEL=="hidraw*", ATTRS{idVendor}=="1430", ATTRS{idProduct}=="0150", TAG+="uaccess"
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="1430", ATTR{idProduct}!="0150", TAG+="uaccess"
'''


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def _hex(text):
    try:
        return int(text, 16)
    except ValueError:
        return -1


def list_portals(sysfs='/sys'):
    """Connected portals: dicts with id, name, family and access."""
    sysfs = Path(sysfs)
    found = []
    hidraw = sysfs / 'class/hidraw'
    for node in sorted(hidraw.iterdir()) if hidraw.is_dir() else ():
        fields = dict(line.split('=', 1) for line in _read(node / 'device/uevent').splitlines() if '=' in line)
        parts = fields.get('HID_ID', '').split(':')
        if len(parts) != 3 or _hex(parts[0]) != 3 or _hex(parts[1]) != ACTIVISION or _hex(parts[2]) != HID_PORTAL:
            continue
        device = '/dev/' + node.name
        found.append({'id': 'hid:' + device, 'name': fields.get('HID_NAME') or 'HID portal',
                      'family': 'hid', 'path': device})
    usb = sysfs / 'bus/usb/devices'
    for node in sorted(usb.iterdir()) if usb.is_dir() else ():
        if _hex(_read(node / 'idVendor')) != ACTIVISION or _hex(_read(node / 'idProduct')) in (HID_PORTAL, -1):
            continue
        product = _hex(_read(node / 'idProduct'))
        family = 'xbox360' if product == XBOX360_PORTAL else 'xbox-one'
        bus, address = _read(node / 'busnum'), _read(node / 'devnum')
        found.append({'id': f'xbox:{bus}-{address}', 'name': 'Xbox 360 portal' if family == 'xbox360' else 'Xbox One portal',
                      'family': family, 'path': f'/dev/bus/usb/{int(bus or 0):03d}/{int(address or 0):03d}'})
    for portal in found:
        portal['accessible'] = os.access(portal['path'], os.R_OK | os.W_OK)
    return found


def valid_choice(value):
    return isinstance(value, str) and '\0' not in value and (
        value in (VIRTUAL, AUTO) or value.startswith('hid:/dev/hidraw') or value.startswith('xbox:'))


def label(portal):
    note = '' if portal.get('accessible', True) else '  ·  needs the udev rule'
    return f"Real portal: {portal['name']} ({portal['family']}){note}"


def access_help():
    return (f'Install the udev rule so your user can open portals:\n'
            f'  python3 {Path(__file__).resolve()} --udev-rule | sudo tee /etc/udev/rules.d/{UDEV_RULE_NAME}\n'
            f'  sudo udevadm control --reload && sudo udevadm trigger\n'
            f'then unplug and replug the portal.')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--udev-rule']:
        sys.stdout.write(UDEV_RULE)
    else:
        for portal in list_portals():
            print(portal['id'], '\t', label(portal))
