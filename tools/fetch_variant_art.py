#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scrape figure variant artwork into a private cache.

The portrait catalogue in fetch_portal_portraits.py has no art for many variants
(Giants, Legendary/Dark/Nitro decos, traps, SuperChargers). Each figure that
catalogue lacks is matched by name against darkSpyro's per-game figure pages,
then against the Skylanders Fandom wiki through its MediaWiki API. Candidates
are tried in that order until one downloads. Every image's page and URL is
recorded. No artwork is bundled.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import io
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
DARKSPYRO='https://www.darkspyro.net'
DARKSPYRO_GAMES=('skylanders','giants','swapforce','trapteam','superchargers')
API='https://skylanders.fandom.com/api.php'
FIGURES='https://raw.githubusercontent.com/dolphin-emu/dolphin/master/Source/Core/Core/IOS/USB/Emulated/Skylanders/Skylander.cpp'
CATALOGUE='https://api.github.com/repos/chotchki/skylander-portal-controller/git/trees/main?recursive=1'
AGENT='SkylandersPC-VariantArt/1.0'
# Deco words that the wikis write differently in names.
RENAME={"Eon's Elite":'Elite','S2':'Series 2','S3':'Series 3','LightCore':'Lightcore'}
# Figure names that neither name pattern produces.
ALIASES={'Kaos (Ultimate)':['Ultimate Kaos Trap'],'Hidden Treasure (Platinum)':['Platinum Treasure Chest'],
         'Scorpion Striker Catapult':['Scorpion Striker'],'Chill (Legendary LightCore)':['Legendary Chill']}


def download(url,limit):
    request=urllib.request.Request(url,headers={'User-Agent':AGENT})
    with urllib.request.urlopen(request,timeout=25) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('response exceeds limit')
    return data


def api(**params):
    params.update(format='json',formatversion=2)
    time.sleep(0.2)
    return json.loads(download(API+'?'+urllib.parse.urlencode(params),8*1024*1024))


def parse_figures(source):
    pattern=r'\{\{(\d+), 0x([0-9A-Fa-f]+)\}, \{"([^"]+)", Game::(\w+), Element::(\w+), Type::(\w+)\}\}'
    return [dict(id=int(i),variant=int(v,16),name=n,game=g,element=e,type=t)
            for i,v,n,g,e,t in re.findall(pattern,source)]


def catalogued(tree):
    # The portrait catalogue keys drop the variant's top (game) nibble.
    keys=set()
    for item in tree.get('tree',[]):
        match=re.fullmatch(r'data/images/([0-9a-f]{6})-([0-9a-f]{4})/thumb.png',item['path'])
        if match:keys.add((int(match[1],16),int(match[2],16)))
    return keys


def candidates(name):
    """Display names for a figure name such as 'Blast Zone (Dark) (Top)'."""
    base=re.sub(r'\s*\((Top|Bottom)\)$','',name)
    match=re.fullmatch(r'(.+?) \((.+)\)',base)
    if not match:titles=[base,base+' (Vehicle)',base+' (Trap)']
    else:
        core,deco=match[1],RENAME.get(match[2],match[2])
        titles=[f'{deco} {core}',f'{core} ({deco})']
        if deco=='Elite':titles.append(f"Eon's Elite {core}")
    return ALIASES.get(name,[])+titles


def key(name):
    return re.sub(r'[^a-z0-9]','',name.lower())


def parse_darkspyro(page,page_url):
    """Map normalized image names to (alt text, absolute image URL) on a figure page."""
    found={}
    for src,alt in re.findall(r'<img src="(/images/[^"]+\.(?:jpg|png))" alt="([^"]+)"',page):
        alt=html.unescape(alt)
        found.setdefault(key(alt),(alt,page_url,DARKSPYRO+src))
    return found


def darkspyro_index(cache):
    index={}
    for game in DARKSPYRO_GAMES:
        path=cache/f'darkspyro-{game}.html';url=f'{DARKSPYRO}/{game}/figures/'
        if not path.exists():
            path.write_bytes(download(url,4*1024*1024));time.sleep(0.5)
        for name,value in parse_darkspyro(path.read_text(errors='replace'),url).items():index.setdefault(name,value)
    return index


def resolve_pages(titles):
    """Map each requested title to (page title, original image URL) via pageimages."""
    found={}
    for start in range(0,len(titles),50):
        chunk=titles[start:start+50]
        data=api(action='query',titles='|'.join(chunk),prop='pageimages',piprop='original',redirects=1)['query']
        alias={t:t for t in chunk}
        for step in ('normalized','redirects'):
            for row in data.get(step,[]):
                for title,value in alias.items():
                    if value==row['from']:alias[title]=row['to']
        pages={page['title']:page for page in data.get('pages',[])}
        for title,target in alias.items():
            page=pages.get(target)
            if page and not page.get('missing') and page.get('original'):
                found[title]=(page['title'],page['original']['source'])
    return found


def search_file(query):
    """Fall back to the best-ranked image file whose name contains every query word."""
    words=[w.lower() for w in re.findall(r"[\w'-]+",query)]
    hits=api(action='query',list='search',srsearch=query,srnamespace=6,srlimit=10)['query']['search']
    for hit in hits:
        title=hit['title']
        if re.search(r'\.(png|jpe?g|webp)$',title,re.I) and all(w in title.lower() for w in words):
            info=api(action='query',titles=title,prop='imageinfo',iiprop='url')['query']['pages'][0]
            if info.get('imageinfo'):return title,info['imageinfo'][0]['url']
    return None


def prepare(destination,figures_file=None,tree_file=None,everything=False,fandom=True):
    destination=Path(destination).absolute()
    if destination.is_symlink():raise ValueError('redirected variant art cache')
    destination.mkdir(parents=True,exist_ok=True)
    source=Path(figures_file).read_bytes() if figures_file else download(FIGURES,4*1024*1024)
    figures=parse_figures(source.decode())
    if not figures:raise ValueError('no figures parsed from figure list')
    if not everything:
        cached=ROOT/'.local/portal-assets/catalogue.json'
        tree_path=Path(tree_file) if tree_file else cached if cached.exists() else None
        tree=json.loads(tree_path.read_text() if tree_path else download(CATALOGUE,8*1024*1024))
        have=catalogued(tree)
        figures=[f for f in figures if (f['id'],f['variant']&0xfff) not in have]
    wanted={f['name']:candidates(f['name']) for f in figures}
    darkspyro=darkspyro_index(destination)
    pages=resolve_pages(sorted({t for titles in wanted.values() for t in titles})) if fandom else {}
    jobs=[];unresolved=[]
    for figure in figures:
        titles=wanted[figure['name']];options=[]
        for title in titles:
            if key(title) in darkspyro:
                alt,page,url=darkspyro[key(title)]
                options.append(dict(source='darkspyro',query=alt,page=page,url=url));break
        if fandom:
            hit=next(((t,*pages[t]) for t in titles if t in pages),None)
            if hit:options.append(dict(source='fandom-page',query=hit[0],page=hit[1],url=hit[2]))
            elif not options and (file:=search_file(titles[0])):
                options.append(dict(source='fandom-file',query=titles[0],page=file[0],url=file[1]))
        if options:jobs.append(dict(figure,options=options))
        else:unresolved.append(dict(figure,tried=titles))
    def fetch(job):
        path=destination/f'figure-{job["id"]:06x}-{job["variant"]:04x}.image'
        errors=[]
        if path.is_symlink():return dict(job,error='redirected art file')
        for option in job['options']:
            try:
                meta=path.with_suffix('.json')
                cached=path.exists() and meta.exists() and json.loads(meta.read_text()).get('url')==option['url']
                data=path.read_bytes() if cached else download(option['url'],8*1024*1024)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width*image.height>16*1024*1024:raise ValueError('oversized image dimensions')
                    image.verify()
                if not cached:
                    temporary=path.with_suffix('.tmp');temporary.write_bytes(data);temporary.replace(path)
                    meta.write_text(json.dumps(dict(url=option['url']))+'\n')
                result={k:v for k,v in job.items() if k!='options'}
                return dict(result,**option,cache=path.name,sha256=hashlib.sha256(data).hexdigest())
            except (OSError,ValueError,urllib.error.URLError) as error:errors.append(dict(option,error=str(error)))
        return dict({k:v for k,v in job.items() if k!='options'},error=errors)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,jobs))
    fetched=[r for r in results if 'error' not in r]
    record=dict(schema_version=2,sources=[DARKSPYRO]+([API] if fandom else []),figure_list=FIGURES,
                fetched=fetched,failed=[r for r in results if 'error' in r],unresolved=unresolved,
                note='Third-party identification artwork (darkSpyro; Fandom files are CC BY-SA unless marked); private cache only.')
    (destination/'variant-sources.json').write_text(json.dumps(record,indent=2)+'\n')
    counts={name:sum(r['source']==name for r in fetched) for name in ('darkspyro','fandom-page','fandom-file')}
    print(json.dumps(dict(considered=len(figures),fetched=len(fetched),by_source=counts,
                          failed=len(record['failed']),unresolved=len(unresolved)),indent=2))
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/portal-assets/variant-art')
    parser.add_argument('--figures-file',type=Path,help='local copy of Dolphin Skylander.cpp')
    parser.add_argument('--tree-file',type=Path,help='local copy of the portrait catalogue tree')
    parser.add_argument('--all',action='store_true',help='fetch every figure, not only catalogue gaps')
    parser.add_argument('--no-fandom',action='store_true',help='use darkSpyro only')
    args=parser.parse_args();prepare(args.out,args.figures_file,args.tree_file,args.all,not args.no_fandom)
