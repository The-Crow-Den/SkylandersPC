# SPDX-License-Identifier: GPL-3.0-or-later
"""Check GitHub for a newer published release and install it.

Release installs (the Linux folder with SkylandersPC.AppImage, the Windows
folder with SkylandersPC.exe) update themselves: `download` fetches that
platform's release archive, checks it against the SHA-256 GitHub lists for it
and unpacks it into .local/update-staging. `apply_later` then starts a small
script that waits for the launcher to close, copies the new files over the
install and opens the launcher again. Only files that come with a release are
replaced or removed: prepared game files, builds and the player's data stay.

Git checkout: `git pull --ff-only` when the work tree is clean; native parts
then need rebuilding, as after any pull. Anything else opens the release page.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
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
STAGING = '.local/update-staging'
MANIFEST = '.local/release-files.json'
WINDOWS = os.name == 'nt'


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
        if error.code in (403, 429):  # the API's per-address limit; shared networks hit it
            return latest_from_site(timeout)
        raise
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name', '')
    if not newer(tag):
        return None
    return {'version': tag.lstrip('v'), 'tag': tag, 'url': data.get('html_url', ''),
            'notes': (data.get('body') or '')[:4000],
            'assets': {a['name']: a['browser_download_url'] for a in data.get('assets', [])
                       if isinstance(a, dict) and a.get('name') and a.get('browser_download_url')},
            'digests': {a['name']: a['digest'] for a in data.get('assets', [])
                        if isinstance(a, dict) and a.get('name') and isinstance(a.get('digest'), str)}}


def latest_from_site(timeout=10, opener=urllib.request.urlopen):
    """The latest release from github.com itself (not rate-limited like the API).

    The /releases/latest page redirects to the newest published release's tag;
    checksums come from the release's SHA256SUMS file."""
    request = urllib.request.Request(f'https://github.com/{REPOSITORY}/releases/latest',
                                     headers={'User-Agent': 'SkylandersPC-launcher'}, method='HEAD')
    with opener(request, timeout=timeout) as response:
        final = response.geturl()
    match = re.search(r'/releases/tag/([^/?#]+)$', final)
    if not match or not newer(match.group(1)):return None
    tag = match.group(1);base = f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
    try:sums = fetch(base + 'SHA256SUMS', timeout, limit=1 << 16).decode()
    except urllib.error.HTTPError:return None
    digests = {}
    for line in sums.splitlines():
        found = re.fullmatch(r'([0-9a-f]{64})\s+\*?(\S+)', line.strip())
        if found:digests[found.group(2)] = 'sha256:' + found.group(1)
    return {'version': tag.lstrip('v'), 'tag': tag, 'url': f'https://github.com/{REPOSITORY}/releases/tag/{tag}',
            'notes': '', 'assets': {name: base + name for name in digests}, 'digests': digests}


def install_kind(root=ROOT, windows=WINDOWS, frozen=None):
    root = Path(root)
    if (root / '.git').exists():return 'git'
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if windows and frozen and (root / 'SkylandersPC.exe').is_file():return 'windows'
    if not windows and (root / 'SkylandersPC.AppImage').is_file():return 'linux'
    return 'manual'


def asset_name(release, kind):
    suffix = {'linux': '-linux.tar.gz', 'windows': '-windows.zip'}[kind]
    return f'SkylandersPC-{release["tag"]}{suffix}'


def _safe_name(name):
    path = Path(name.replace('\\', '/'))
    return bool(name) and not path.is_absolute() and '..' not in path.parts and ':' not in name


def download(release, kind, root=ROOT, progress=lambda fraction: None, opener=urllib.request.urlopen):
    """Fetch, verify and unpack the release for this install. Returns the staged folder."""
    root = Path(root);name = asset_name(release, kind)
    url, digest = release['assets'].get(name), release.get('digests', {}).get(name, '')
    if not url:raise ValueError('This release has no download for this computer yet.')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):raise ValueError('The release does not list a checksum for its download.')
    staging = root / STAGING
    shutil.rmtree(staging, ignore_errors=True);staging.mkdir(parents=True)
    archive = staging / name;hasher = hashlib.sha256()
    request = urllib.request.Request(url, headers={'User-Agent': 'SkylandersPC-launcher'})
    with opener(request, timeout=30) as response, archive.open('wb') as out:
        total = int(response.headers.get('Content-Length') or 0);done = 0
        for block in iter(lambda: response.read(1 << 20), b''):
            out.write(block);hasher.update(block);done += len(block)
            if total:progress(min(done / total, 1.0))
    if 'sha256:' + hasher.hexdigest() != digest:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError('The download did not match its published checksum. Nothing was changed.')
    files = staging / 'files'
    try:
        if kind == 'linux':
            with tarfile.open(archive) as bundle:
                members = bundle.getmembers()
                if any(not _safe_name(m.name) for m in members):raise ValueError('unsafe path in the download')
                bundle.extractall(files, filter='data')
            top = files / 'SkylandersPC-linux'
            if not (top / 'tools/launcher.py').is_file():raise ValueError('the download is not a SkylandersPC release')
        else:
            with zipfile.ZipFile(archive) as bundle:
                if any(not _safe_name(n) for n in bundle.namelist()):raise ValueError('unsafe path in the download')
                bundle.extractall(files)
            top = files
            if not (top / 'SkylandersPC.exe').is_file():raise ValueError('the download is not a SkylandersPC release')
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError('The download could not be unpacked: ' + str(error)) from error
    archive.unlink()
    new = sorted(p.relative_to(top).as_posix() for p in top.rglob('*') if p.is_file() or p.is_symlink())
    try:old = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):old = []
    keep = set(new)
    remove = [n for n in old if isinstance(n, str) and n not in keep and _safe_name(n)]
    if kind == 'windows':remove = [n.replace('/', '\\') for n in remove]
    (staging / 'remove.txt').write_text(''.join(n + '\n' for n in remove), encoding='utf-8')
    (top / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (top / MANIFEST).write_text(json.dumps(new), encoding='utf-8')
    (staging / 'version').write_text(release['version'], encoding='utf-8')
    return top


def staged(root=ROOT):
    """The version waiting in the staging folder, or None."""
    try:return (Path(root) / STAGING / 'version').read_text(encoding='utf-8').strip() or None
    except OSError:return None


def apply_later(kind, root=ROOT, pid=None, relaunch=True, popen=subprocess.Popen):
    """Start the script that installs the staged files once this launcher exits."""
    root = Path(root).resolve();staging = root / STAGING;pid = os.getpid() if pid is None else pid
    if kind == 'linux':
        script = staging / 'apply.sh'
        script.write_text(f"""#!/bin/sh
root={_sh(root)}; stage={_sh(staging)}
while kill -0 {int(pid)} 2>/dev/null; do sleep 0.5; done
while IFS= read -r name; do [ -n "$name" ] && rm -f -- "$root/$name"; done < "$stage/remove.txt"
cp -a "$stage/files/SkylandersPC-linux/." "$root/" || exit 1
rm -rf -- "$stage"
{'exec "$root/SkylandersPC.AppImage" >/dev/null 2>&1' if relaunch else ''}
""", encoding='utf-8')
        return popen(['sh', str(script)], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd='/')
    script = staging / 'apply.cmd'
    script.write_text(f"""@echo off
set "ROOT={root}"
set "STAGE={staging}"
:wait
tasklist /FI "PID eq {int(pid)}" 2>nul | find "{int(pid)}" >nul && (ping -n 2 127.0.0.1 >nul & goto wait)
for /f "usebackq delims=" %%f in ("%STAGE%\\remove.txt") do del /q "%ROOT%\\%%f" 2>nul
robocopy "%STAGE%\\files" "%ROOT%" /E /NFL /NDL /NJH /NJS /R:5 /W:1 >nul
if errorlevel 8 exit /b 1
{'start "" "%ROOT%\\SkylandersPC.exe"' if relaunch else ''}
rmdir /s /q "%STAGE%" & exit /b 0
""".replace('\n', '\r\n'), newline='', encoding='utf-8')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    return popen(['cmd', '/c', str(script)], creationflags=flags, cwd=str(root.anchor or root),
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _sh(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


def update_git(root=ROOT, run=subprocess.run):
    status = run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
                 capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
    if status.returncode != 0:
        raise ValueError('git status failed: ' + status.stderr.strip())
    if status.stdout.strip():
        raise ValueError('You have local changes; commit or stash them, then update.')
    pull = run(['git', '-C', str(root), 'pull', '--ff-only'], capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace')
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
