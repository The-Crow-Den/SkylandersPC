#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch identification portraits into a private cache; no artwork is bundled."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import urllib.request
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
TREE='https://api.github.com/repos/chotchki/skylander-portal-controller/git/trees/main?recursive=1'
RAW='https://raw.githubusercontent.com/chotchki/skylander-portal-controller/main/'


def supported(identity):
    return (identity<=32 or 100<=identity<=115 or identity in (404,416,419,430) or
            450<=identity<=485 or 502<=identity<=543 or 3000<=identity<=3015 or
            200<=identity<=209 or 230<=identity<=233 or 300<=identity<=308)


def image_entries(tree):
    if tree.get('truncated'):raise ValueError('truncated portrait catalogue')
    rows=[]
    for item in tree.get('tree',[]):
        match=re.fullmatch(r'data/images/([0-9a-f]{6})-([0-9a-f]{4})/thumb.png',item['path'])
        if match:
            identity,variant=int(match[1],16),int(match[2],16)
            if supported(identity) and variant<0x4000:
                rows.append(dict(id=identity,variant=variant,url=RAW+item['path'],blob_sha=item.get('sha')))
    return sorted(rows,key=lambda row:(row['id'],row['variant']))


def download(url,limit):
    request=urllib.request.Request(url,headers={'User-Agent':'SkylandersPC-PortraitCache/1.0'})
    with urllib.request.urlopen(request,timeout=25) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('portrait response exceeds limit')
    return data


def prepare(destination,tree_file=None):
    destination=Path(destination).absolute()
    if destination.is_symlink() or destination.resolve()!=destination:raise ValueError('redirected portrait cache')
    destination.mkdir(parents=True,exist_ok=True)
    catalogue=json.loads((ROOT/'profiles/trap-team-portal.json').read_text())
    if tree_file:tree=json.loads(Path(tree_file).read_text())
    else:
        cache=destination/'catalogue.json'
        if not cache.exists():cache.write_bytes(download(TREE,8*1024*1024))
        tree=json.loads(cache.read_text())
    characters=image_entries(tree)
    jobs=[dict(kind='villain',index=i,url=v['portrait_url'],cache=f'{i:02}.image') for i,v in enumerate(catalogue['villains'])]
    jobs += [dict(row,kind='figure',cache=f"figure-{row['id']:06x}-{row['variant']:04x}.image") for row in characters]
    elements=['Water','Life','Air','Earth','Fire','Undead','Magic','Tech','Light','Dark','Kaos']
    special={'Light':'sun','Dark':'moon','Kaos':'kaos'}
    jobs += [dict(kind='element',index=i,url=('https://www.darkspyro.net/images/trapteam/element_'+special[name]+'.png' if name in special else 'https://www.darkspyro.net/images/skylanders/element_'+name.lower()+'_h.png'),cache='element-'+name+'.image') for i,name in enumerate(elements)]
    for job in jobs:
        if job.get('id')==6:
            job['url']='https://www.darkspyro.net/images/skylanders/skylander_dino-rang.jpg'
            job['cache']=f"verified-dino-{job['variant']:04x}.image"
            job.pop('blob_sha',None)
    def fetch(job):
        path=destination/job['cache']
        try:
            if path.is_symlink():raise ValueError('redirected portrait file')
            data=path.read_bytes() if path.exists() else download(job['url'],4*1024*1024)
            if len(data)>4*1024*1024:raise ValueError('oversized cached portrait')
            if job.get('blob_sha'):
                blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                if blob!=job['blob_sha']:raise ValueError('portrait differs from indexed upstream image')
            with Image.open(io.BytesIO(data)) as image:
                if image.width*image.height>16*1024*1024:raise ValueError('oversized portrait dimensions')
                picture=image.convert('RGBA')
            if not path.exists():
                temporary=path.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(path)
            return job,picture,dict(url=job['url'],sha256=hashlib.sha256(data).hexdigest(),cache=job['cache'])
        except (OSError,ValueError) as error:return job,None,dict(url=job['url'],error=str(error))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(fetch,jobs):results.append(result)
    # First 46 cells retain villain ordering. Other cells are explicitly mapped
    # by figure identity, never by a saved collection's changing list index.
    cell=96;columns=16;rows=(len(jobs)+columns-1)//columns
    atlas=Image.new('RGBA',(columns*cell,rows*cell),(0,0,0,0));mapping=[];element_mapping=[];sources=[];missing=[]
    for slot,(job,picture,source) in enumerate(results):
        if picture is None:missing.append(source);continue
        source.update(cell=slot,kind=job['kind']);sources.append(source)
        if job['kind']=='element':
            picture=ImageOps.contain(picture,(cell-16,cell-16),Image.Resampling.LANCZOS);element_mapping.append((job['index'],slot))
        elif job['kind']=='villain':picture=ImageOps.fit(picture,(cell-8,cell-8),Image.Resampling.LANCZOS)
        else:
            picture=ImageOps.contain(picture,(cell-8,cell-8),Image.Resampling.LANCZOS)
            mapping.append((job['id'],job['variant'],slot))
        atlas.alpha_composite(picture,(slot%columns*cell+(cell-picture.width)//2,slot//columns*cell+(cell-picture.height)//2))
    content=struct.pack('<II',*atlas.size)+atlas.tobytes()
    temporary=destination/'portraits.rgba.tmp';temporary.write_bytes(content);temporary.replace(destination/'portraits.rgba')
    lines=[f'SKYPORTRAITS1 {columns} {rows}']+[f'{identity} {variant} {slot}' for identity,variant,slot in mapping]
    temporary=destination/'portrait-index.txt.tmp';temporary.write_text('\n'.join(lines)+'\n');temporary.replace(destination/'portrait-index.txt')
    (destination/'element-index.txt').write_text('\n'.join(f'{element} {cell}' for element,cell in element_mapping)+'\n')
    record=dict(schema_version=2,atlas_sha256=hashlib.sha256(content).hexdigest(),dimensions=list(atlas.size),columns=columns,rows=rows,
                figure_portraits=len(mapping),villain_portraits=sum(j['kind']=='villain' and p is not None for j,p,_ in results),
                sources=sources,missing=missing,note='Third-party identification artwork; private cache only, not a redistribution grant.')
    (destination/'sources.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:record[key] for key in ('figure_portraits','villain_portraits','dimensions')},indent=2));print('Missing portraits:',len(missing))
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/portal-assets');parser.add_argument('--tree-file',type=Path)
    args=parser.parse_args();prepare(args.out,args.tree_file)
