# SPDX-License-Identifier: GPL-3.0-or-later
"""Portal report: what an Xbox (or any) Portal of Power looks like over USB.

Xbox portals aren't supported in game yet because nobody with one has recorded
how it talks. Owners can run this with the portal plugged in and send the file
it writes (attach it to a GitHub issue):

    python3 tools/portal_report.py                 # descriptors only, read-only
    python3 tools/portal_report.py --probe         # also asks the portal to identify itself

The report holds the USB descriptors and, with --probe, the raw replies to the
reset ('R'), activate ('A') and status ('S') commands, which name the portal
model and say which slots are occupied. It never reads figures ('Q'), never
writes anything to a figure, and leaves out serial numbers and user names.
Linux only: probing opens /dev/bus/usb directly, so it needs the udev rule from
tools/portal_devices.py (or root), and it detaches xpad from the portal while it
runs.
"""
import argparse
import ctypes
import fcntl
import json
import os
import platform
import struct
import sys
import time
from pathlib import Path

ACTIVISION = 0x1430
HID_PORTAL = 0x0150
REPORT_SIZE = 32
# Xbox 360 portals: 32-byte frames, header 0B 14 both ways. The bare form is
# tried too, so the report shows what an unusual portal answers to.
XBOX360_HEADERS = [(b'\x0b\x14', b'\x0b\x14'), (b'', b'')]
# GIP (Xbox One): the generic power-on message every GIP device accepts.
GIP_POWER_ON = bytes([0x05, 0x20, 0x00, 0x01, 0x00])

# usbdevfs ioctls (x86-64 / aarch64 layout).
USBDEVFS_CLAIMINTERFACE = 0x8004550F
USBDEVFS_RELEASEINTERFACE = 0x80045510
USBDEVFS_BULK = 0xC0185502
USBDEVFS_IOCTL = 0xC0105512
USBDEVFS_DISCONNECT = 0x5516
USBDEVFS_CONNECT = 0x5517


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def parse_descriptors(raw):
    """Device and configuration descriptors from sysfs's `descriptors` blob."""
    result = {'device': None, 'interfaces': []}
    offset, interface = 0, None
    while offset + 2 <= len(raw):
        length, kind = raw[offset], raw[offset+1]
        if length < 2:
            break
        body = raw[offset:offset+length]
        if kind == 1 and len(body) >= 18:
            (_, _, usb, cls, sub, proto, packet, vendor, product, release, _, _, _, configs) = struct.unpack('<BBHBBBBHHHBBBB', body[:18])
            result['device'] = {'usb': f'{usb:04x}', 'class': cls, 'subclass': sub, 'protocol': proto, 'max_packet': packet,
                                'vendor': f'{vendor:04x}', 'product': f'{product:04x}', 'release': f'{release:04x}', 'configurations': configs}
        elif kind == 4 and len(body) >= 9:
            interface = {'number': body[2], 'alternate': body[3], 'class': body[5], 'subclass': body[6], 'protocol': body[7], 'endpoints': [], 'extra': []}
            result['interfaces'].append(interface)
        elif kind == 5 and len(body) >= 7 and interface is not None:
            interface['endpoints'].append({'address': f'{body[2]:02x}', 'type': ('control', 'isochronous', 'bulk', 'interrupt')[body[3] & 3],
                                           'max_packet': struct.unpack('<H', body[4:6])[0], 'interval': body[6]})
        elif kind != 2 and interface is not None:
            interface['extra'].append(body.hex())  # class-specific (HID, Xbox 360 0x21, ...)
        offset += length
    return result


def find(sysfs='/sys'):
    """Every Activision USB device, with its descriptors (no serial numbers)."""
    found = []
    root = Path(sysfs)/'bus/usb/devices'
    for node in sorted(root.iterdir()) if root.is_dir() else ():
        if _read(node/'idVendor') != f'{ACTIVISION:04x}':
            continue
        try:
            raw = (node/'descriptors').read_bytes()
        except OSError:
            raw = b''
        bus, address = _read(node/'busnum'), _read(node/'devnum')
        found.append({'product_id': _read(node/'idProduct'), 'manufacturer': _read(node/'manufacturer'), 'product': _read(node/'product'),
                      'speed': _read(node/'speed'), 'descriptors_hex': raw.hex(), 'parsed': parse_descriptors(raw),
                      'node': f'/dev/bus/usb/{int(bus or 0):03d}/{int(address or 0):03d}'})
    return found


def family(device):
    interfaces = device['parsed']['interfaces']
    if device['product_id'] == f'{HID_PORTAL:04x}' or any(i['class'] == 3 for i in interfaces):
        return 'hid'
    if any(i['class'] == 0xFF and i['subclass'] == 0x47 for i in interfaces):
        return 'xbox-one'
    return 'xbox360'


class Usb:
    """Just enough usbdevfs for interrupt transfers on one interface."""
    def __init__(self, node, number):
        self.fd = os.open(node, os.O_RDWR)
        self.number = number
        self.detached = False
        request = struct.pack('iiP', number, USBDEVFS_DISCONNECT, 0)
        try:
            fcntl.ioctl(self.fd, USBDEVFS_IOCTL, request)
            self.detached = True
        except OSError:
            pass  # no kernel driver bound
        fcntl.ioctl(self.fd, USBDEVFS_CLAIMINTERFACE, struct.pack('I', number))

    def transfer(self, endpoint, data=b'', length=64, timeout=500):
        buffer = ctypes.create_string_buffer(bytes(data), len(data)) if data else ctypes.create_string_buffer(length)
        request = struct.pack('IIIxxxxP', endpoint, len(data) if data else length, timeout, ctypes.addressof(buffer))
        try:
            count = fcntl.ioctl(self.fd, USBDEVFS_BULK, request)
        except TimeoutError:
            return None
        except OSError as error:
            return {'error': error.strerror}
        return buffer.raw[:count]

    def close(self):
        try:
            fcntl.ioctl(self.fd, USBDEVFS_RELEASEINTERFACE, struct.pack('I', self.number))
            if self.detached:
                fcntl.ioctl(self.fd, USBDEVFS_IOCTL, struct.pack('iiP', self.number, USBDEVFS_CONNECT, 0))
        finally:
            os.close(self.fd)


def _hex(value):
    if value is None:
        return 'timeout'
    return value if isinstance(value, dict) else value.hex()


def _drain(usb, endpoint, log, label, reads=4):
    for _ in range(reads):
        reply = usb.transfer(endpoint, length=32, timeout=300)
        log.append({'read': label, 'reply': _hex(reply)})
        if reply is None or isinstance(reply, dict):
            break


def probe(device):
    """Raw replies to identify commands. Never sends 'Q' or 'W'."""
    interface = next((i for i in device['parsed']['interfaces'] if i['alternate'] == 0), None)
    if interface is None:
        return {'error': 'no interface'}
    endpoints = {e['address']: e for e in interface['endpoints'] if e['type'] == 'interrupt'}
    ep_in = next((int(a, 16) for a in endpoints if int(a, 16) & 0x80), None)
    ep_out = next((int(a, 16) for a in endpoints if not int(a, 16) & 0x80), None)
    if ep_in is None or ep_out is None:
        return {'error': 'no interrupt endpoint pair', 'endpoints': list(endpoints)}
    log = []
    try:
        usb = Usb(device['node'], interface['number'])
    except OSError as error:
        return {'error': f'could not open the portal: {error.strerror}. Install the udev rule (see tools/portal_devices.py) or run with sudo.'}
    try:
        kind = family(device)
        _drain(usb, ep_in, log, 'unsolicited')  # GIP devices announce themselves on connect
        if kind == 'xbox-one':
            log.append({'write': GIP_POWER_ON.hex(), 'result': _hex(usb.transfer(ep_out, GIP_POWER_ON))})
            _drain(usb, ep_in, log, 'after power-on')
        headers = XBOX360_HEADERS if kind != 'hid' else [(b'', b'')]
        for out, _ in headers:
            for command in (b'R', b'A\x01', b'S'):
                frame = (out + command).ljust(REPORT_SIZE, b'\0')
                log.append({'write': frame.hex(), 'result': _hex(usb.transfer(ep_out, frame))})
                _drain(usb, ep_in, log, f'after {command[:1].decode()}', reads=3)
        frame = (headers[0][0] + b'A\x00').ljust(REPORT_SIZE, b'\0')  # deactivate again
        usb.transfer(ep_out, frame)
    finally:
        usb.close()
    return {'interface': interface['number'], 'in': f'{ep_in:02x}', 'out': f'{ep_out:02x}', 'log': log}


def report(do_probe=False, sysfs='/sys'):
    devices = find(sysfs)
    for device in devices:
        device['family'] = family(device)
        if do_probe:
            device['probe'] = probe(device)
    for device in devices:
        device.pop('node')  # bus layout of this machine; not needed
    return {'tool': 'portal_report 1', 'system': platform.system(), 'kernel': platform.release(),
            'created': time.strftime('%Y-%m-%d'), 'portals': devices}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--probe', action='store_true', help='also send identify commands (no figure reads or writes)')
    parser.add_argument('--output', default='portal-report.json', help='where to write the report')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        print('portal_report currently runs on Linux only.', file=sys.stderr)
        return 2
    data = report(args.probe)
    if not data['portals']:
        print('No Activision USB device found. Plug the portal in and try again.', file=sys.stderr)
        return 1
    Path(args.output).write_text(json.dumps(data, indent=2)+'\n')
    for device in data['portals']:
        print(f"Found {device['product'] or 'portal'} ({device['family']}, 1430:{device['product_id']})")
        if 'probe' in device and 'error' in device['probe']:
            print('  probe:', device['probe']['error'])
    print(f'Wrote {args.output}. Attach it to an issue at https://github.com/The-Crow-Den/SkylandersPC/issues')
    return 0


if __name__ == '__main__':
    sys.exit(main())
