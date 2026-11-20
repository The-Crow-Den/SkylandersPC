# SPDX-License-Identifier: GPL-3.0-or-later
"""Check GitHub for a newer published release and, where it is safe, install it.

The launcher code always runs from the checkout (the AppImage only carries
Python), so the checkout is what gets updated. Git checkout: `git pull --ff-only` when the work tree is clean; native parts then
need rebuilding, as after any pull. Anything else (Windows bundle, source
archive) opens the release page.
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .version import VERSION
except ImportError:
    from version import VERSION

REPOSITORY = 'The-Crow-Den/SkylandersPC'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
ROOT = Path(__file__).resolve().parents[1]


def parse(version):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(version).strip())
    if not match:
        raise ValueError('Not a release version: ' + str(version))
    return tuple(int(part) for part in match.groups())


def newer(candidate, current=VERSION):
    try:
        return parse(candidate) > parse(current)
    except ValueError:
        return False


def fetch(url, timeout=10, limit=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'SkylandersPC-launcher', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read() if limit is None else response.read(limit)


def latest(timeout=10):
    """The newest published (non-draft, non-prerelease) release, or None."""
    try:
        data = json.loads(fetch(API, timeout, limit=4 << 20))
    except urllib.error.HTTPError as error:
        if error.code == 404:  # nothing published yet
            return None
        raise
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name', '')
    if not newer(tag):
        return None
    return {'version': tag.lstrip('v'), 'tag': tag, 'url': data.get('html_url', ''),
            'notes': (data.get('body') or '')[:4000],
            'assets': {a['name']: a['browser_download_url'] for a in data.get('assets', [])
                       if isinstance(a, dict) and a.get('name') and a.get('browser_download_url')}}


def install_kind(root=ROOT):
    return 'git' if (Path(root) / '.git').exists() else 'manual'


def update_git(root=ROOT, run=subprocess.run):
    status = run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
                 capture_output=True, text=True, timeout=30)
    if status.returncode != 0:
        raise ValueError('git status failed: ' + status.stderr.strip())
    if status.stdout.strip():
        raise ValueError('You have local changes; commit or stash them, then update.')
    pull = run(['git', '-C', str(root), 'pull', '--ff-only'], capture_output=True, text=True, timeout=300)
    if pull.returncode != 0:
        raise ValueError('git pull failed: ' + (pull.stderr or pull.stdout).strip())
    return pull.stdout.strip()


def main():
    release = latest()
    if not release:
        print('Up to date (' + VERSION + ').'); return 0
    print('Update available:', release['version'], release['url'])
    if '--apply' in sys.argv:
        if install_kind() == 'git':print(update_git())
        else:print('Download it from', release['url'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
