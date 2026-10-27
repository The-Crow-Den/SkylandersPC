# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
import json
from pathlib import Path
import tempfile
from tools.audit_imports import audit, markdown, nid, registrations


class ImportAuditTests(unittest.TestCase):
    def test_unscoped_symbol_and_declaration_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = nid('sceExample') + '#library#module'
            metadata = root / 'metadata.json'
            metadata.write_text(json.dumps({'imports': [{'name': identity}, {'name': 'module_start'}]}))
            source = root / 'reference.cpp'
            source.write_text('''// int sceExample(int wrong) { misleading comment }
int sceExample(int value) { return value; }
LIB_FUNCTION("''' + nid('sceExample') + '''", "library", 1, "module", sceExample);''')
            report = audit([metadata], [root], root, [])
            entry = next(r for r in report['imports'] if r['identity'] == identity)
            self.assertEqual(entry['reference_signatures'], ['int sceExample(int value)'])
            self.assertEqual(entry['name_evidence'], 'scoped registration')
            self.assertIn('Unscoped symbols', markdown(report))

    def test_known_nid(self):
        self.assertEqual(nid('sceVideoRecordingGetStatus'), 'fZJQzFK4Gv4')

    def test_scoped_and_wrapped_registrations(self):
        text = '''LIB_FUNCTION("abc", "libScePosix", 1, "libkernel",
                   ORBIS(posix_pthread_mutex_lock));
                   LIB_FUNCTION("abc", "other", 1, "module", another);'''
        self.assertEqual(registrations(text), [('abc#libScePosix#libkernel', 'posix_pthread_mutex_lock'),
                                              ('abc#other#module', 'another')])
