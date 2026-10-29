# SPDX-License-Identifier: GPL-3.0-or-later
"""Trophy names, details and grades from the user's own PSN account.

The flow follows the public PlayStation app sign-in used by psnawp
(MIT): npsso cookie -> authorization code -> access token -> trophy API.
The npsso value is never stored, logged or passed on the command line.
"""
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

AUTH = 'https://ca.account.sony.com/api/authz/v3/oauth/'
API = 'https://m.np.playstation.com/api/trophy/v1/npCommunicationIds/'
CLIENT = '09515159-7237-4370-9b40-3806e67c0891'
BASIC = 'Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A='
REDIRECT = 'com.scee.psxandroid.scecompcall://redirect'
GRADES = {'platinum': 'P', 'gold': 'G', 'silver': 'S', 'bronze': 'B'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):return None


def access_token(npsso):
    npsso = npsso.strip()
    if not re.fullmatch(r'[A-Za-z0-9]{40,128}', npsso):raise ValueError('That does not look like an npsso value.')
    query = urllib.parse.urlencode(dict(access_type='offline', client_id=CLIENT, redirect_uri=REDIRECT,
                                        response_type='code', scope='psn:mobile.v2.core psn:clientapp'))
    request = urllib.request.Request(AUTH+'authorize?'+query, headers={'Cookie': 'npsso='+npsso})
    try:
        urllib.request.build_opener(_NoRedirect).open(request, timeout=20)
        location = ''
    except urllib.error.HTTPError as response:
        location = response.headers.get('Location', '')
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get('code', [''])[0]
    if not code:raise ValueError('PSN sign-in was refused. Sign in at playstation.com again and copy a fresh npsso.')
    body = urllib.parse.urlencode(dict(code=code, redirect_uri=REDIRECT, grant_type='authorization_code',
                                       token_format='jwt')).encode()
    request = urllib.request.Request(AUTH+'token', data=body, headers={
        'Authorization': BASIC, 'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)['access_token']


def fetch(npwr, token):
    if not re.fullmatch(r'NPWR\d{5}_\d{2}', npwr):raise ValueError('invalid trophy communication ID')
    def get(path):
        request = urllib.request.Request(API+npwr+path+'?npServiceName=trophy',
                                         headers={'Authorization': 'Bearer '+token})
        with urllib.request.urlopen(request, timeout=20) as response:return json.load(response)
    title = get('/trophyGroups').get('trophyTitleName', '')
    rows = {}
    for trophy in get('/trophyGroups/all/trophies')['trophies']:
        group = trophy.get('trophyGroupId', 'default')
        rows[int(trophy['trophyId'])] = dict(name=trophy.get('trophyName', ''), detail=trophy.get('trophyDetail', ''),
            grade=GRADES.get(trophy.get('trophyType', ''), ''), hidden=bool(trophy.get('trophyHidden')),
            group=0 if group == 'default' else int(group))
    if not rows:raise ValueError('PSN returned no trophies for this game.')
    return title, rows


def write_catalogue(store, npwr, title, rows):
    """Write TROP.XML into each cached catalogue whose IDs match the PSN list."""
    written = []
    for catalogue in sorted((Path(store)/'catalogues').glob(npwr+'-*')):
        icons = {int(p.stem[4:]) for p in (catalogue/'Icons').glob('TROP[0-9][0-9][0-9].PNG')}
        if icons and icons != set(rows):raise ValueError('PSN trophy list does not match the installed game.')
        document = ET.Element('trophyconf');ET.SubElement(document, 'title-name').text = title
        for i, row in sorted(rows.items()):
            item = ET.SubElement(document, 'trophy', id=str(i), ttype=row['grade'] or '?', gid=str(row['group']),
                                 hidden='yes' if row['hidden'] else 'no')
            ET.SubElement(item, 'name').text = row['name'];ET.SubElement(item, 'detail').text = row['detail']
        target = catalogue/'Xml'/'TROP.XML'
        if target.is_symlink():raise ValueError('redirected trophy XML')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(ET.tostring(document, encoding='utf-8', xml_declaration=True));written.append(target)
    if not written:raise ValueError('Start the game once so its trophy set is prepared, then try again.')
    return written


def main():
    import argparse, getpass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('store', type=Path, help='native trophy store, e.g. ~/.local/share/skylanders-pc/trophies/CUSA00626')
    parser.add_argument('npwr', help='trophy communication ID, e.g. NPWR06603_00')
    args = parser.parse_args()
    title, rows = fetch(args.npwr, access_token(getpass.getpass('npsso: ')))
    for path in write_catalogue(args.store, args.npwr, title, rows):print(path)


if __name__ == '__main__':
    main()
