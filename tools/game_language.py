# SPDX-License-Identifier: GPL-3.0-or-later
"""Console system language for a session; each title profile lists what it offers.

The game reads the PS4 system language parameter and picks its own text and
voice set; the host reports the chosen code through SKY_SYSTEM_LANGUAGE.
"""
import json
from pathlib import Path

# PS4 SCE_SYSTEM_PARAM_LANG values.
CODES = {
    'ja-JP': 0, 'en-US': 1, 'fr-FR': 2, 'es-ES': 3, 'de-DE': 4, 'it-IT': 5, 'nl-NL': 6, 'pt-PT': 7,
    'ru-RU': 8, 'ko-KR': 9, 'zh-TW': 10, 'zh-CN': 11, 'fi-FI': 12, 'sv-SE': 13, 'da-DK': 14,
    'nb-NO': 15, 'pl-PL': 16, 'pt-BR': 17, 'en-GB': 18, 'tr-TR': 19, 'es-419': 20, 'ar': 21, 'fr-CA': 22,
}
NAMES = {
    'ja-JP': 'Japanese', 'en-US': 'English (US)', 'fr-FR': 'French (France)', 'es-ES': 'Spanish (Spain)',
    'de-DE': 'German', 'it-IT': 'Italian', 'nl-NL': 'Dutch', 'pt-PT': 'Portuguese (Portugal)', 'ru-RU': 'Russian',
    'ko-KR': 'Korean', 'zh-TW': 'Chinese (Traditional)', 'zh-CN': 'Chinese (Simplified)', 'fi-FI': 'Finnish',
    'sv-SE': 'Swedish', 'da-DK': 'Danish', 'nb-NO': 'Norwegian', 'pl-PL': 'Polish', 'pt-BR': 'Portuguese (Brazil)',
    'en-GB': 'English (UK)', 'tr-TR': 'Turkish', 'es-419': 'Spanish (Latin America)', 'ar': 'Arabic',
    'fr-CA': 'French (Canada)',
}
DEFAULT = 'en-US'


def offered(root, profile_id):
    """Languages a title profile lists, in its order; English (US) when none are listed."""
    path = Path(root) / 'profiles' / f'{profile_id}.json'
    try:
        languages = json.loads(path.read_text()).get('languages', [DEFAULT])
    except (OSError, ValueError, AttributeError):
        return [DEFAULT]
    if not isinstance(languages, list) or not languages or any(item not in CODES for item in languages):
        raise ValueError(f'{path.name} has an invalid language list')
    return languages


def choose(root, profile_id, requested):
    """(language, note): the requested language, or English (US) when the title lacks it."""
    if requested not in CODES:
        raise ValueError(f'unknown language {requested}')
    languages = offered(root, profile_id)
    if requested in languages:
        return requested, None
    return DEFAULT, f'{NAMES[requested]} is not offered for this game; using {NAMES[DEFAULT]}'


def narration(language):
    """Movie narration language name for a system language, matched by its base language."""
    return {'en': 'English', 'es': 'Spanish', 'fr': 'French', 'pt': 'Portuguese', 'de': 'German',
            'it': 'Italian', 'nl': 'Dutch'}.get(language.split('-')[0])
