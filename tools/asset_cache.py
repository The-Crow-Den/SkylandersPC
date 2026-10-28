# SPDX-License-Identifier: GPL-3.0-or-later
"""Private content-addressed cache of verified asset-mod outputs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

# 3: shrunken LZMA blocks are lengthened by re-encoding, never padded (revision 1
# padded inside the stream and crashed; 2 stored them short and misread blocks).
OUTPUT_REVISION=3


def digest_file(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def stage(cache,source_data,recipe,destination,patch):
    """Return metadata and stage one immutable result without recompressing a hit.

    The original bytes and cached output are hashed on every use. A cache entry
    never changes recipe validation or permits changes to the source install.
    """
    source_hash=hashlib.sha256(source_data).hexdigest()
    if source_hash!=recipe['source_sha256']:raise ValueError('asset source hash mismatch')
    cache=Path(cache).absolute()
    if cache.resolve()!=cache or cache.is_symlink():raise ValueError('redirected asset cache')
    cache.mkdir(parents=True,exist_ok=True)
    # OUTPUT_REVISION changes when patch output for the same recipe changes.
    key=hashlib.sha256(json.dumps(dict(recipe=recipe,output_revision=OUTPUT_REVISION),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    entry=cache/key;data_path=entry/'asset';manifest=entry/'manifest.json';record=None
    if entry.exists():
        try:
            if entry.is_symlink() or data_path.is_symlink() or manifest.is_symlink() or manifest.stat().st_size>8192:raise ValueError('redirected cache entry')
            record=json.loads(manifest.read_text())
            if (record.get('version')!=1 or record.get('source_sha256')!=source_hash or
                record.get('recipe_sha256')!=key or not data_path.is_file() or data_path.stat().st_size!=record['size'] or
                digest_file(data_path)!=record['output_sha256']):record=None
        except (OSError,ValueError,KeyError,TypeError):record=None
    if record is not None:
        os.link(data_path,destination)
        return dict(source_sha256=source_hash,output_sha256=record['output_sha256'],cache='hit')
    modified,metadata=patch(source_data,recipe)
    # Publishing a new entry never overwrites an existing cache or a game file.
    if not entry.exists():
        with tempfile.TemporaryDirectory(prefix='.asset-',dir=cache) as temporary:
            temporary=Path(temporary);(temporary/'asset').write_bytes(modified)
            record=dict(version=1,source_sha256=source_hash,recipe_sha256=key,output_sha256=metadata['output_sha256'],size=len(modified))
            (temporary/'manifest.json').write_text(json.dumps(record,sort_keys=True)+'\n')
            try:
                entry.mkdir();os.link(temporary/'asset',data_path);os.link(temporary/'manifest.json',manifest)
            except FileExistsError:pass
    # A corrupt cache is bypassed, rather than trusted or modified in place.
    Path(destination).write_bytes(modified)
    return dict(metadata,cache='miss')
