# SPDX-License-Identifier: GPL-3.0-or-later
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import windows_inventory_check as check


class WindowsInventoryTest(unittest.TestCase):
    def test_unlisted_binaries_reported(self):
        inventory = json.loads((check.ROOT / 'LICENSES/windows-bundled-components.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            for name in ('SkylandersPC.exe', '_internal/PyQt6/Qt6/bin/QtWebEngineProcess.exe',
                         '.local/native-gpu-build/libSDL3.dll', '_internal/mystery.dll'):
                (bundle / name).parent.mkdir(parents=True, exist_ok=True); (bundle / name).write_bytes(b'MZ..')
            (bundle / 'tools').mkdir(); (bundle / 'tools/readme.txt').write_text('not a binary', encoding='utf-8')
            msys2 = [{'file': '.local/native-gpu-build/libSDL3.dll', 'package': 'sdl3', 'license': 'Zlib'}]
            self.assertEqual(check.unlisted(bundle, inventory, msys2), ['_internal/mystery.dll'])


if __name__ == '__main__':
    unittest.main()
