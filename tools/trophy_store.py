# SPDX-License-Identifier: GPL-3.0-or-later
"""Private trophy catalogue preparation and native/shadPS4 progress continuity.

TRP layout and AES-CBC derivation follow shadPS4's documented extractor:
https://github.com/shadps4-emu/shadPS4/blob/main/src/core/file_format/trp.cpp
No trophy key or decrypted game metadata is included in project source.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tomllib
import xml.etree.ElementTree as ET
try:from . import launcher_trophies
except ImportError:import launcher_trophies


def entries(path):
    path=Path(path);size=path.stat().st_size;result={}
    with path.open('rb') as source:
        header=source.read(96)
        if len(header)!=96 or header[:4]!=b'\xdc\xa2M\0':raise ValueError('invalid trophy archive')
        count,stride=struct.unpack_from('>II',header,16)
        if not 0<count<=10000 or not 64<=stride<=4096 or 96+count*stride>size:raise ValueError('invalid trophy archive table')
        for _ in range(count):
            row=source.read(stride);name=row[:32].split(b'\0')[0].decode('ascii');offset,length,flag=struct.unpack_from('>QQI',row,32)
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}',name) or name in result or offset<96+count*stride or offset+length>size or length>4*1024*1024:raise ValueError('invalid trophy archive entry')
            result[name]=(offset,length,flag)
    return result


def configured_key(path):
    """Read only the explicitly supplied private key/config; never print it."""
    if path is None:return None
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>2*1024*1024:raise ValueError('invalid private trophy-key configuration')
    data=path.read_text().strip()
    candidates=[]
    if re.fullmatch(r'[0-9a-fA-F]{32}',data):candidates.append(data)
    else:
        def visit(value):
            if not isinstance(value,dict):return
            for key,item in value.items():
                if 'troph' in key.lower() and 'key' in key.lower() and isinstance(item,str):candidates.append(item)
                visit(item)
        try:config=json.loads(data) if data.startswith("{") else tomllib.loads(data)
        except (ValueError,tomllib.TOMLDecodeError):raise ValueError("invalid private trophy-key configuration") from None
        visit(config)
    candidates=[value for value in candidates if re.fullmatch(r'[0-9a-fA-F]{32}',value) and set(value)!={'0'}]
    if len(set(candidates))!=1:raise ValueError('no unique configured trophy key found')
    return bytes.fromhex(candidates[0])


def decrypt_xml(data,key,npwr):
    if len(key)!=16 or not re.fullmatch(r'NPWR\d{5}_\d{2}',npwr) or len(data)<32 or (len(data)-16)%16:raise ValueError('invalid encrypted trophy XML')
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    derive=Cipher(algorithms.AES(key),modes.CBC(bytes(16))).encryptor()
    derived=derive.update(npwr.encode().ljust(16,b'\0'))+derive.finalize()
    decryptor=Cipher(algorithms.AES(derived),modes.CBC(data[:16])).decryptor();plain=decryptor.update(data[16:])+decryptor.finalize()
    end=plain.rfind(b'>')
    if end<0:raise ValueError('trophy XML could not be decrypted with the supplied local key')
    plain=plain[:end+1]
    if b'<!DOCTYPE' in plain.upper() or b'<!ENTITY' in plain.upper():raise ValueError('unsafe trophy XML')
    try:root=ET.fromstring(plain)
    except ET.ParseError:raise ValueError('trophy XML could not be decrypted with the supplied local key') from None
    if root.tag!='trophyconf':raise ValueError('decrypted data is not a trophy catalogue')
    return plain


def clean_text(value):return re.sub(r'[\x00-\x1f]+',' ',str(value))


def prepare(root,install,session,*,store=None,key_config=None):
    root,session=Path(root),Path(session)
    trp=install.source('sce_sys/trophy/trophy00.trp')
    if not trp.is_file():
        candidates=sorted((install.base/'sce_sys/trophy').glob('*.trp'))
        if len(candidates)!=1:return {'available':False,'reason':'No unique trophy set found'}
        trp=candidates[0]
    binding=install.source('sce_sys/npbind.dat').read_bytes()
    identifiers=set(re.findall(rb'NPWR\d{5}_\d{2}',binding))
    if len(identifiers)!=1:raise ValueError('no unique trophy communication ID')
    npwr=identifiers.pop().decode();table=entries(trp)
    title_id=install.title_id
    store=Path(store).absolute() if store else Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'skylanders-pc/trophies'/title_id
    if store.resolve()!=store.absolute() or store.is_symlink():raise ValueError('redirected native trophy store')
    cache=store/'catalogues'
    if cache.resolve()!=cache or cache.is_symlink():raise ValueError('redirected trophy catalogue cache')
    cache.mkdir(parents=True,exist_ok=True)
    checksum=hashlib.sha256(trp.read_bytes()).hexdigest();catalogue=cache/(npwr+'-'+checksum)
    if catalogue.is_symlink():raise ValueError('redirected trophy catalogue cache')
    catalogue.mkdir(exist_ok=True);icons=catalogue/'Icons';xml=catalogue/'Xml'
    if icons.is_symlink() or xml.is_symlink():raise ValueError('redirected trophy catalogue cache')
    icons.mkdir(exist_ok=True);xml.mkdir(exist_ok=True)
    key=configured_key(key_config)
    with trp.open('rb') as source:
        for name,(offset,size,flag) in table.items():
            if flag==0 and name.endswith('.PNG'):
                target=icons/name
                if target.is_symlink():raise ValueError('redirected trophy icon')
                if not target.exists():source.seek(offset);data=source.read(size);target.write_bytes(data)
            elif flag==3 and name.endswith('.ESFM') and key is not None:
                target=xml/name.replace('.ESFM','.XML')
                if target.is_symlink():raise ValueError('redirected trophy XML')
                if not target.exists():source.seek(offset);plain=decrypt_xml(source.read(size),key,npwr);target.write_bytes(plain)
    definition=next((path for path in [xml/'TROP_01.XML',xml/'TROP.XML',xml/'TROPCONF.XML'] if path.is_file()),None)
    game={'id':'trap-team','name':'Trap Team','installed_paths':[str(install.base)]}
    _,external_definition,external_progress,_=launcher_trophies.game_sources(root,game)
    if definition is None and external_definition:definition=Path(external_definition)
    ids={int(name[4:7]) for name in table if re.fullmatch(r'TROP\d{3}\.PNG',name)}
    if not ids or max(ids)>=128:raise ValueError('trophy IDs exceed the supported PS4 flag array')
    if definition:
        title,rows=launcher_trophies.read_xml(definition)
        if set(rows)!=ids:raise ValueError('trophy catalogue does not match installed IDs')
    else:
        title='Skylanders Trap Team';rows={i:dict(id=i,name=f'Trophy {i:03}',detail='',grade='',hidden=False,unlocked=False,timestamp='') for i in ids}
    destination=session/'trophies';destination.mkdir(exist_ok=True)
    grade={'P':1,'G':2,'S':3,'B':4}
    for user in (4096,4097):
        directory=store/'users'/str(user)
        if directory.resolve()!=directory or directory.is_symlink():raise ValueError('redirected native trophy user')
        directory.mkdir(parents=True,exist_ok=True);progress=directory/(npwr+'.xml')
        if progress.is_symlink():raise ValueError('redirected native trophy record')
        saved={}
        if progress.is_file():
            _,saved=launcher_trophies.read_xml(progress)
            if set(saved)!=ids:raise ValueError('native trophy record has different IDs')
        elif user==4096 and external_progress:
            _,saved=launcher_trophies.read_xml(external_progress)
            if set(saved)!=ids:raise ValueError('previous trophy progress has different IDs')
        lines=['SKYTROPHIES1\t'+npwr+'\t'+clean_text(title)]
        document=ET.Element('trophyconf');ET.SubElement(document,'title-name').text=title
        for i,row in sorted(rows.items()):
            unlocked=bool(saved.get(i,{}).get('unlocked',False));timestamp=saved.get(i,{}).get('timestamp','') or '0'
            if not str(timestamp).isdigit():timestamp='0'
            lines.append('\t'.join(map(str,[i,grade.get(row['grade'],0),row.get('group',0),int(row['hidden']),int(unlocked),timestamp,clean_text(row['name']),clean_text(row['detail'])])))
            item=ET.SubElement(document,'trophy',id=str(i),ttype=row['grade'] or '?',gid=str(row.get('group',0)),hidden='yes' if row['hidden'] else 'no',unlockstate='true' if unlocked else 'false',timestamp=str(timestamp))
            ET.SubElement(item,'name').text=row['name'];ET.SubElement(item,'detail').text=row['detail']
        (destination/f'{user}.tsv').write_text('\n'.join(lines)+'\n')
        if not progress.exists():
            with progress.open('xb') as output:output.write(ET.tostring(document,encoding='utf-8',xml_declaration=True))
    return dict(available=True,npwr=npwr,store=str(store),catalogues=str(destination),icons=str(icons),definitions=str(definition) if definition else None,
                encrypted=definition is None,total=len(ids),trp_sha256=checksum,
                reason='Decrypted trophy catalogue ready' if definition else 'Trophy key is not configured; IDs and future unlocks can be recorded, but names remain encrypted')


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Prepare private trophy metadata and preserve per-user unlock records')
    parser.add_argument('--game-root',type=Path,default=Path(__file__).resolve().parents[1]/'Game')
    parser.add_argument('--trophy-config',type=Path,help='private shadPS4 TOML/JSON or raw trophy-key file')
    parser.add_argument('--store',type=Path,help='override the normal home-directory trophy store')
    args=parser.parse_args()
    try:
        try:from .game_install import discover
        except ImportError:from game_install import discover
        import tempfile
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='trophy-catalogue-') as directory:
            result=prepare(root,discover(args.game_root),Path(directory),store=args.store,key_config=args.trophy_config)
        result.pop('catalogues',None) # Session-only descriptor directory has expired.
        print(json.dumps(result,indent=2))
        return 0 if result.get('available') else 1
    except (OSError,ValueError,ImportError) as error:
        parser.exit(1,'Trophy preparation failed: '+str(error)+'\n')


if __name__=='__main__':raise SystemExit(main())
