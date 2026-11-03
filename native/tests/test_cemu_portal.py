# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the complete generated-figure test with a real junction on Windows."""
from pathlib import Path
import subprocess
import sys
import tempfile
from filesystem_fixtures import directory_link

with tempfile.TemporaryDirectory(prefix='sky-portal-fixture-') as temporary:
    root = Path(temporary)
    target = root / 'outside'
    target.mkdir()
    marker = target / 'marker'
    marker.write_bytes(b'unchanged')
    link = root / 'redirect'
    directory_link(link, target)
    result = subprocess.run([str(Path(sys.argv[1]).resolve()), '--directory-link',
                             str(link).encode('utf-8').hex()],
                            capture_output=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError(f'portal test failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
    if marker.read_bytes() != b'unchanged':
        raise AssertionError('outside portal fixture was modified')
    print(result.stdout, end='')
