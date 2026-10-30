# SPDX-License-Identifier: GPL-2.0-or-later
"""Writes OPTIONS.md: every SKY_RENDERER_<name> option the renderer reads, from the code."""
import re, pathlib, collections, sys
root = pathlib.Path(sys.argv[1])
files = sorted(p for p in root.rglob('*') if p.suffix in ('.cpp', '.h', '.c') and 'third_party' not in p.parts)
name_re = re.compile(r'"SKY_RENDERER_([A-Z0-9_]+)"')
reads = collections.defaultdict(list)

def clean(text):
    text = re.sub(r'^(renderer|skylanders)( \([a-z-]+\))?:?\s*', '', text.strip())
    return text.replace('|', '\\|')

def nearby_comment(lines, i, name):
    # A comment naming the option within 12 lines above (or on the line), else the comment block
    # right above the read.
    for j in range(i, max(-1, i - 12), -1):
        if 'SKY_RENDERER_' + name in lines[j] and '//' in lines[j]:
            block = [lines[j].split('//', 1)[1].lstrip('/ ').strip()]
            k = j + 1
            while k < len(lines) and lines[k].strip().startswith('//'):
                block.append(lines[k].strip().lstrip('/ ').strip()); k += 1
            return ' '.join(block)
    block = []
    j = i - 1
    while j >= 0 and i - j < 8:
        t = lines[j].strip()
        if t.startswith('//'):
            block.insert(0, t.lstrip('/ ').strip())
        elif block or not (t.startswith('static') or 'getenv' in t or t.endswith('{') or t == ''):
            break
        j -= 1
    if block:
        return ' '.join(block)
    for j in range(i, max(-1, i - 15), -1):
        m = re.match(r'\s*(?:[\w:<>&*]+\s+)+([\w:~]+)\(', lines[j])
        if m and not lines[j].strip().startswith(('if', 'return', 'static const')):
            return f'(read in {m.group(1)})'
    return ''

def default_of(window):
    w = ' '.join(window)
    if re.search(r"!\s*env\s*\|\|\s*env\[0\]\s*!=\s*'0'|!\(\s*\w+\s*&&\s*\w+\[0\]\s*==\s*'0'\)", w):
        return 'on; `0` turns it off'
    if re.search(r"\w+\s*&&\s*\w+\[0\]\s*==\s*'1'|!=\s*nullptr|\w+\s*&&\s*\w+\[0\]\s*!=\s*'0'", w):
        return 'off; `1` (or a value) turns it on'
    m = re.search(r'Flag\("SKY_RENDERER_\w+",\s*(true|false)\)', w)
    if m:
        return 'on' if m.group(1) == 'true' else 'off'
    m = re.search(r'Number\("SKY_RENDERER_\w+",\s*([-\w]+)\)', w)
    if m:
        return f'`{m.group(1)}`'
    m = re.search(r':\s*([0-9][0-9_]*(?:ull|u|ll)?)\s*;', w) or re.search(r'\?\s*[^:]+:\s*([0-9][\w.]*)', w)
    if m:
        return f'`{m.group(1).rstrip("ul")}`'
    return ''

def category(name, text):
    t = name + ' ' + text.lower()
    if name.startswith('EXP_') or 'experiment' in text.lower():
        return 'experiment'
    if re.search(r'TRACE|_LOG\b|LOG$|DUMP|WATCH|STATS|CHECK|VERIFY|PROFILE|CAPTURE|TRIGGER|REPORT|SELFTEST|PRINT|MARKERS|VALIDATION|TIMELINE|SECTIONS?\b|BREADCRUMB', name) or 'diagnostic' in text.lower():
        return 'diagnostic'
    if '(tests)' in text or 'for testing' in text or 'scripted tests' in text:
        return 'test'
    return 'behaviour'

for p in files:
    lines = p.read_text(errors='replace').splitlines()
    for i, line in enumerate(lines):
        for m in name_re.finditer(line):
            window = lines[max(0, i - 1):i + 3]
            if not any(k in ' '.join(window) for k in ('getenv', 'Flag(', 'Number(')):
                continue
            reads[m.group(1)].append((p.relative_to(root), i + 1, nearby_comment(lines, i, m.group(1)), default_of(window)))

order = ['behaviour', 'diagnostic', 'experiment', 'test']
rows = collections.defaultdict(list)
for name, sites in reads.items():
    text = next((c for _, _, c, _ in sites if c and not c.startswith('(read in')), '') or next((c for _, _, c, _ in sites if c), '')
    default = next((d for *_, d in sites if d), '')
    where = ', '.join(sorted({f'`{s[0]}`' for s in sites}))
    rows[category(name, text)].append((name, default, clean(text), where))
out = ['# skyrender options', '',
       'Every `SKY_RENDERER_<name>` environment variable the renderer reads, generated from the code',
       '(`tools/gen_options.py`; run it again after adding or removing an option). The host sets a few',
       'itself (SkylandersPS4 `native/gpu_backend.cpp`); the old `BB_<name>` spellings are taken over at',
       'load (`gpu/shim/legacy_options.cpp`). "Default" is read off the code and may be blank where it',
       'is computed; the description is the comment at the read.', '']
titles = {'behaviour': 'Behaviour and tuning', 'diagnostic': 'Diagnostics (off unless set)',
          'experiment': 'Experiments (A/B switches for hunting bugs)', 'test': 'Test hooks'}
for cat in order:
    out += [f'## {titles[cat]} ({len(rows[cat])})', '', '| Option | Default | Description | Read in |', '|---|---|---|---|']
    for name, default, text, where in sorted(rows[cat]):
        out.append(f'| `{name}` | {default} | {text[:400]} | {where} |')
    out.append('')
pathlib.Path(sys.argv[2]).write_text('\n'.join(out))
print({c: len(rows[c]) for c in order}, 'total', sum(len(v) for v in rows.values()))
