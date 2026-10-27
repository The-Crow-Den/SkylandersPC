# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only trophy catalogue and per-user unlock records. Never infer from gameplay."""
from pathlib import Path
import os
import re
import struct
import xml.etree.ElementTree as ET


def read_xml(path):
    path=Path(path)
    if path.stat().st_size>2*1024*1024:raise ValueError('Trophy XML is too large')
    data=path.read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('Trophy XML cannot contain entity declarations')
    try:root=ET.fromstring(data)
    except ET.ParseError as error:raise ValueError('Invalid trophy XML') from error
    if root.tag!='trophyconf':raise ValueError('Expected a trophyconf document, not a game save')
    trophies={}
    for node in root.findall('trophy'):
        identity=int(node.get('id','-1'))
        if not 0<=identity<10000 or identity in trophies:raise ValueError('Invalid or duplicate trophy ID')
        if node.get('unlockstate','false').lower() not in ('true','false','0','1'):
            raise ValueError('Invalid trophy unlock state')
        trophies[identity]={'id':identity,'name':node.findtext('name') or f'Trophy {identity:03}',
            'detail':node.findtext('detail') or '', 'grade':node.get('ttype','').upper(),
            'hidden':node.get('hidden','no')=='yes','unlocked':node.get('unlockstate','false').lower() in ('true','1'),
            'timestamp':node.get('timestamp',''),'group':int(node.get('gid','0'))}
        if not 0<=trophies[identity]['group']<128:raise ValueError('Invalid trophy group')
    if not trophies:raise ValueError('No trophies found in this document')
    return root.findtext('title-name',''),trophies


def archive(path):
    path=Path(path);size=path.stat().st_size;entries={}
    with path.open('rb') as stream:
        header=stream.read(96)
        if len(header)!=96 or header[:4]!=b'\xdc\xa2M\0':raise ValueError('Invalid TRP header')
        count,stride=struct.unpack_from('>II',header,16)
        if count>10000 or not 64<=stride<=4096 or 96+count*stride>size:raise ValueError('Invalid TRP table')
        for _ in range(count):
            entry=stream.read(stride);name=entry[:32].split(b'\0')[0].decode('ascii')
            offset,length=struct.unpack_from('>QQ',entry,32)
            if offset<96+count*stride or offset+length>size:raise ValueError('TRP entry is outside the archive')
            if re.fullmatch(r'TROP\d{3}\.PNG',name):entries[int(name[4:7])]=(offset,length)
    return entries


def game_sources(root,game):
    root=Path(root);folders=[Path(p) for p in game.get('installed_paths',[])]
    if game['id']=='trap-team':
        try:
            try:from .game_install import discover
            except ImportError:from game_install import discover
            folders.insert(0,discover(root/'Game').base)
        except (OSError,ValueError):pass
    trp=None;npwr=None
    for folder in folders:
        candidates=sorted((folder/'sce_sys/trophy').glob('*.trp'))
        if candidates:
            if len(candidates)>1:raise ValueError('Multiple trophy sets found; select a trophy XML explicitly')
            trp=candidates[0]
            binding=folder/'sce_sys/npbind.dat'
            if binding.is_file() and binding.stat().st_size<1024*1024:
                matches=set(re.findall(rb'NPWR\d{5}_\d{2}',binding.read_bytes()))
                if len(matches)==1:npwr=matches.pop().decode()
            break
    definitions=game.get('trophy_definitions','');progress=game.get('trophy_progress','')
    if npwr:
        homes=[root/'.local/share/shadPS4',Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'shadPS4']
        for home in homes:
            if not definitions:
                for relative in (f'trophy/{npwr}/Xml/TROP.XML',f'trophy/{npwr}/Xml/TROP_01.XML'):
                    if (home/relative).is_file():definitions=str(home/relative);break
            candidate=home/'home'/str(game.get('trophy_user','1000'))/'trophy'/(npwr+'.xml')
            if not progress and candidate.is_file():progress=str(candidate)
    if npwr and game['id']=='trap-team':
        native=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'skylanders-pc/trophies/CUSA00626'
        record=native/'users'/str(game.get('native_trophy_user','4096'))/(npwr+'.xml')
        if not game.get('trophy_progress') and record.is_file():progress=str(record)
        if not definitions:
            for cache in sorted((native/'catalogues').glob(npwr+'-*')):
                for filename in ('TROP_01.XML','TROP.XML','TROPCONF.XML'):
                    if (cache/'Xml'/filename).is_file():definitions=str(cache/'Xml'/filename);break
                if definitions:break
    return trp,definitions,progress,npwr


def snapshot(root,game):
    trp,definitions,progress,npwr=game_sources(root,game)
    rows={};title='';message=[]
    if definitions:title,rows=read_xml(definitions)
    if progress:
        saved_title,saved=read_xml(progress)
        if npwr and Path(progress).stem.startswith('NPWR') and Path(progress).stem!=npwr:raise ValueError('User trophy record belongs to a different trophy set')
        normalize=lambda value:re.sub(r'[^a-z0-9]','',value.lower())
        if rows and (set(saved)!=set(rows) or (title and saved_title and normalize(title)!=normalize(saved_title))):
            raise ValueError('User trophy record does not match this catalogue')
        title=title or saved_title
        rows=rows or saved
        for key in rows:rows[key]={**rows[key],'unlocked':saved[key]['unlocked']}
        message.append('Unlocks read from '+str(progress))
    elif rows:
        rows={key:{**row,'unlocked':None} for key,row in rows.items()}
    icons=archive(trp) if trp else {}
    if not rows:
        rows={key:dict(id=key,name=f'Trophy {key:03}',detail='Name and requirements need decrypted trophy XML.',grade='',hidden=False,unlocked=None) for key in icons}
    if rows:
        normalized=re.sub(r'[^a-z0-9]','',title.lower());game_name=re.sub(r'[^a-z0-9]','',game['name'].lower())
        if normalized and game_name not in normalized:raise ValueError('Trophy XML title does not match the selected game')
        if icons and set(rows)!=set(icons):raise ValueError('Trophy XML does not match the installed trophy IDs')
    if not progress:
        message.append('No user trophy record found. Unlock status is unknown.')
        if game['id']=='trap-team':message.append('Native unlocks are recorded from trophy API requests after catalogue setup; ordinary game saves cannot reconstruct past unlocks.')
    if not definitions and icons:message.append('Installed trophy names are encrypted; link decrypted trophy XML to show names and requirements.')
    if not rows:message.append('No trophy catalogue found for this game.')
    known=bool(rows) and all(row['unlocked'] is not None for row in rows.values())
    earned=sum(row['unlocked'] is True for row in rows.values())
    return dict(rows=list(rows.values()),earned=earned,total=len(rows),percent=earned*100//len(rows) if known else None,
                message='\n'.join(message),trp=trp,icons=icons)


def icon_bytes(data,identity):
    entry=data['icons'].get(identity)
    if not entry or entry[1]>2*1024*1024:return b''
    with data['trp'].open('rb') as stream:
        stream.seek(entry[0]);return stream.read(entry[1])
