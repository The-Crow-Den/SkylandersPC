# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve a supplied base and matching update; never modify either dump."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil

try:
    from .workspace import read_sfo
except ImportError:
    from workspace import read_sfo


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}\.\d{2}', value):
        raise ValueError('Invalid game APP_VER')
    return tuple(map(int, value.split('.')))


@dataclass(frozen=True)
class Install:
    base: Path
    update: Path | None
    title_id: str
    app_version: str

    def source(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Game asset must be relative to the install')
        if self.update and (self.update / relative).is_file():
            return self.update / relative
        return self.base / relative

    def materialize(self, output):
        """Hard-link immutable assets; update files win, including SFO/eboot."""
        output = Path(output)
        if any(root and output.resolve().is_relative_to(root.resolve())
               for root in (self.base,self.update)):
            raise ValueError('Merged game must be outside the original dumps')
        if output.exists():
            raise ValueError('Merged game destination already exists')
        for root in (self.base, self.update):
            if root and (root.is_symlink() or any(p.is_symlink() for p in root.rglob('*'))):
                raise ValueError('Game installation refuses symlinks')
        output.mkdir(parents=True)
        try:
            for root in (self.base, self.update):
                if not root:
                    continue
                for source in root.rglob('*'):
                    target = output / source.relative_to(root)
                    if source.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif source.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            if not target.is_file():
                                raise ValueError('Game update file/directory conflict')
                            target.unlink()
                        os.link(source, target)
                    else:
                        raise ValueError('Game installation requires regular files')
        except BaseException:
            shutil.rmtree(output)
            raise
        return output


def discover(directory):
    candidates = []
    for path in sorted(Path(directory).iterdir()):
        sfo = path / 'sce_sys/param.sfo'
        if path.is_dir() and not path.is_symlink() and sfo.is_file():
            if sfo.is_symlink() or sfo.parent.is_symlink():
                raise ValueError('Game metadata must not be a symlink')
            meta = read_sfo(sfo.read_bytes())
            if meta.get('TITLE_ID') in ('CUSA00697', 'CUSA00626'):
                version(meta.get('APP_VER'))
                candidates.append((path, meta))
    bases = [(p, m) for p, m in candidates if m.get('CATEGORY') == 'gd']
    if len(bases) != 1:
        raise ValueError('Expected exactly one Trap Team base dump in Game/')
    base, identity = bases[0]
    if any(m.get('CATEGORY')=='gp' and m['TITLE_ID']==identity['TITLE_ID'] and
           m.get('CONTENT_ID')!=identity.get('CONTENT_ID') for _,m in candidates):
        raise ValueError('Game update content ID differs from its base')
    updates = [(p, m) for p, m in candidates if m.get('CATEGORY') == 'gp' and
               m['TITLE_ID'] == identity['TITLE_ID'] and
               m.get('CONTENT_ID') == identity.get('CONTENT_ID')]
    updates.sort(key=lambda row: version(row[1]['APP_VER']))
    if len(updates)>1 and updates[-1][1]['APP_VER']==updates[-2][1]['APP_VER']:
        raise ValueError('Ambiguous game update version')
    selected = updates[-1] if updates else None
    if selected and version(selected[1]['APP_VER']) <= version(identity['APP_VER']):
        raise ValueError('Game update must be newer than its base')
    return Install(base, selected[0] if selected else None, identity['TITLE_ID'],
                   selected[1]['APP_VER'] if selected else identity['APP_VER'])
