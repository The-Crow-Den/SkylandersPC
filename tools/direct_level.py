# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in exact-build Chapter One start in an isolated session game root."""
import hashlib
import os
from pathlib import Path

US_ALCHEMY_SHA256='4a6ef12f93459c0c696df40d369fc6b840ea742a67fb92d8fa34ab82cab0d35a'
TITLE=b'startLevel = "Title"'
CHAPTER_ONE=b'startLevel = "Level_313_Tutorial"'


def prepare(game_root,session_root,*,expected_sha256=US_ALCHEMY_SHA256):
    """Atomically replace only the session copy; refuse foreign or linked paths."""
    game=Path(game_root).resolve()
    session=Path(session_root).resolve()
    if not game.is_relative_to(session) or game==session:
        raise ValueError('direct level requires private session game root')
    config=game/'alchemy.xml'
    if config.is_symlink():raise ValueError('direct level refuses symlinked config')
    original=config.read_bytes()
    before=hashlib.sha256(original).hexdigest()
    if before!=expected_sha256:raise ValueError('direct level refuses unknown alchemy.xml')
    if original.count(TITLE)!=1:raise ValueError('direct level startLevel mismatch')
    replacement=original.replace(TITLE,CHAPTER_ONE)
    temporary=game/'alchemy.xml.fps-direct.tmp'
    with temporary.open('xb') as stream:stream.write(replacement)
    try:os.replace(temporary,config)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {'target':'Level_313_Tutorial','source_sha256':before,
            'session_sha256':hashlib.sha256(replacement).hexdigest(),
            'session_file':str(config),'private_only':True}
