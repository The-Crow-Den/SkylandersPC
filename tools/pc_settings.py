# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, local PC preferences shared by the launcher and in-app menu."""
import json
from pathlib import Path
try:
    from .resolution import PRESETS
except ImportError:
    from resolution import PRESETS

QUALITY = {'performance': 'low', 'balanced': 'native', 'high': 'high'}


def validate_settings(value):
    required = {'resolution','quality','fullscreen','fps_counter','frame_limit'}
    if not isinstance(value, dict) or not required.issubset(value) or set(value)-required-{'portal_volume','frame_policy','controller_layout','controller_glyphs'}:
        raise ValueError('invalid PC settings fields')
    if value['resolution'] not in PRESETS or value['quality'] not in QUALITY:
        raise ValueError('unknown PC graphics preset')
    if type(value['fullscreen']) is not bool or type(value['fps_counter']) is not bool:
        raise ValueError('invalid PC display flags')
    if type(value['frame_limit']) is not int or value['frame_limit'] not in (0,30,60):
        raise ValueError('invalid PC frame limit')
    if 'portal_volume' in value and (type(value['portal_volume']) is not int or not 0 <= value['portal_volume'] <= 100):
        raise ValueError('invalid portal speaker volume')
    if 'frame_policy' in value and value['frame_policy'] not in ('auto','manual'):
        raise ValueError('invalid frame policy')
    if 'controller_layout' in value and value['controller_layout'] not in ('auto','keyboard-and-pad'):
        raise ValueError('invalid controller layout')
    if 'controller_glyphs' in value and value['controller_glyphs'] not in ('auto','playstation','xbox','nintendo'):
        raise ValueError('invalid controller glyph style')
    return dict(value)


def load_settings(path):
    return validate_settings(json.loads(Path(path).read_text())) if Path(path).exists() else {}


def save_settings(path, value):
    value = validate_settings(value)
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    temporary.replace(path)
