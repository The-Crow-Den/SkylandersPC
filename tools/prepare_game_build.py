# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce exact-build private packs from the discovered base/update install."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

try:
    from . import game_install, game_build, patches, link_native
except ImportError:
    import game_install, game_build, patches, link_native

ROOT=Path(__file__).resolve().parents[1]


def prepare(root,variant):
    root=Path(root)
    install=game_install.discover(root/'Game')
    config=game_build.configuration(root,install,variant)
    if (install.title_id,install.app_version)!=('CUSA00626','01.01'):
        raise ValueError('This preparer currently supports the supplied US 01.01 update')
    source=config['executable'];original=source.read_bytes();modified=bytearray(original)
    if variant!='original':
        suffix='one-vblank' if variant=='60' else '60-delta'
        manifest=json.loads((root/f'patches/trap-team-CUSA00626-01.01-{suffix}.experimental.json').read_text())
        for offset,before,after,_ in patches.validate(original,manifest):
            modified[offset:offset+len(before)]=after
    modules=[(name,install.source('sce_module/'+name).read_bytes())
             for name in ('libc.prx','libSceFios2.prx')]
    packed,types,metadata=link_native.link_images([('eboot.bin',bytes(modified)),*modules])
    expected=json.loads(config['resolution'].read_text())['pack_sha256'][variant]
    if hashlib.sha256(packed).hexdigest()!=expected:
        raise ValueError('Linked pack differs from the verified build; check supplied modules')
    if source.read_bytes()!=original:
        raise ValueError('Executable changed during preparation')
    output=config['pack'];output.parent.mkdir(parents=True,exist_ok=True);output.mkdir()
    try:
        (output/'image.pack').write_bytes(packed)
        (output/'imports.types').write_bytes(types)
        (output/'boot.plan').write_bytes(link_native.boot_plan(metadata))
        (output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=('original','60','60-delta'),default='60-delta')
    args=parser.parse_args()
    try:
        print(prepare(ROOT,args.variant))
    except (OSError,ValueError) as error:
        parser.error(str(error))


if __name__=='__main__':main()
