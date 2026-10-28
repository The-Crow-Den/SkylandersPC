# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional offscreen Qt checks using synthetic extractors and no game data."""
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PyQt6.QtWidgets import QApplication
    from tools.launcher import Launcher
    from tools.launcher_install_dialog import InstallDialog
    QT = True
except ImportError:
    QT = False
from test_game_install import sfo


@unittest.skipUnless(QT,'optional PyQt6 is not installed')
class LauncherUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.window=Launcher(self.root)

    def tearDown(self):
        self.window.close();self.app.processEvents();self.temporary.cleanup()

    def wait(self,condition):
        deadline=time.monotonic()+5
        while not condition():
            self.app.processEvents()
            if time.monotonic()>deadline:self.fail('Qt operation timed out')
            time.sleep(.005)

    def extractor(self,body):
        tool=self.root/'synthetic-extractor'
        tool.write_text('#!/usr/bin/env python3\n'+body);tool.chmod(0o755)
        return tool

    def test_header_settings_opens_selected_game_scope(self):
        from PyQt6.QtWidgets import QPushButton
        self.window.select_game('trap-team')
        self.window.findChild(QPushButton,'gameSettings').click()
        self.assertIs(self.window.settings_page.game,self.window.game)
        self.assertIn('Trap Team',self.window.settings_page.title.text())
        self.assertTrue(any(button.text()=='Tweaks' for button in self.window.settings_page.nav))
        self.window.settings_page.cancel()
        self.window.select_game('swap-force')
        self.window.findChild(QPushButton,'gameSettings').click()
        self.assertEqual(self.window.settings_page.game['id'],'swap-force')
        self.window.settings()
        self.assertIsNone(self.window.settings_page.game)

    def test_per_game_settings_save_direct_tweaks_without_general_controls(self):
        from tools import launcher_library
        self.window.select_game('trap-team');general=self.window.values()
        self.window.game_settings();page=self.window.settings_page
        self.assertIs(page.game,self.window.game)
        self.assertTrue(page.fields['unlock_nightmare'].isEnabled())
        from PyQt6.QtWidgets import QCheckBox,QPushButton
        self.assertFalse(any('Use general' in widget.text() for kind in (QCheckBox,QPushButton) for widget in page.findChildren(kind)))
        page.mod_fields['element-gates'].setChecked(True)
        page.fields['unlock_nightmare'].setChecked(not general['unlock_nightmare'])
        page.save()
        self.assertEqual(self.window.game['settings'],{'unlock_nightmare':not general['unlock_nightmare']})
        saved=launcher_library.load(self.window.library_path)
        trap=next(g for g in saved['games'] if g['id']=='trap-team')
        self.assertEqual(trap['settings'],self.window.game['settings'])
        self.assertEqual(self.window.values(),general)
        self.assertEqual(trap['mods'],{'element-gates':True,'traptanium':False})
        self.assertFalse(page.mod_fields['any-portal'].isEnabled())
        page.open();self.assertIsNone(page.game)
        self.assertEqual(self.window.values(),general)

    def test_settings_page_save_cancel_and_navigation(self):
        from tools import launcher_model
        original=self.window.values()
        self.window.settings()
        page=self.window.settings_page
        self.assertIs(self.window.views.currentWidget(),page)
        self.assertFalse(self.window.legacy.isVisible())
        page.fields['fullscreen'].setChecked(not original['fullscreen'])
        page.cancel()
        self.assertEqual(self.window.values(),original)
        self.window.settings()
        self.assertEqual(page.fields['fullscreen'].isChecked(),original['fullscreen'])
        page.fields['fullscreen'].setChecked(not original['fullscreen'])
        page.save()
        self.assertEqual(launcher_model.load(self.window.preferences)['fullscreen'],not original['fullscreen'])
        self.assertEqual(self.window.values()['fullscreen'],not original['fullscreen'])
        page.select(4)
        self.assertEqual(page.pages.currentIndex(),4)
        page.cancel()
        self.assertIs(self.window.views.currentWidget(),self.window.canvas)

    def test_game_selection_and_collection_persist(self):
        self.assertEqual(len(self.window.library['games']),4)
        self.window.select_game('imaginators')
        self.assertIn('INSTALL',self.window.primary.text())
        self.assertEqual(self.window.canvas.game['id'],'imaginators')
        figure=self.root/'figure.sky';figure.write_bytes(bytes(1024))
        self.window.library['portal']=str(figure)
        self.window.persist()
        from tools.launcher_library import load
        saved=load(self.window.library_path)
        self.assertEqual(saved['selected'],'imaginators');self.assertEqual(saved['portal'],str(figure))
        figure.unlink();self.assertIsNone(load(self.window.library_path)['portal'])

    def test_per_game_launch_keeps_universal_preferences(self):
        from tools import launcher_model
        self.window.select_game('trap-team')
        universal=self.window.values()
        self.window.game['settings']={'resolution':'2160p','fullscreen':True}
        captured=[]
        base=Launcher.__mro__[1]
        with patch.object(base,'launch',autospec=True,side_effect=lambda window:captured.append(window.values())):
            self.window.launch()
        self.assertEqual(captured[0]['resolution'],'2160p')
        self.assertTrue(captured[0]['fullscreen'])
        self.assertEqual(self.window.values(),universal)
        self.assertEqual(launcher_model.load(self.window.preferences),universal)

    def test_in_game_controller_choices_load_and_survive_launch(self):
        pc=self.root/'out/pc-settings.json';pc.parent.mkdir(parents=True,exist_ok=True)
        pc.write_text(json.dumps({'resolution':'1080p','quality':'high','fullscreen':True,'fps_counter':True,'frame_limit':30,
                                  'frame_policy':'auto','portal_volume':30,'controller_layout':'keyboard-and-pad','controller_glyphs':'xbox'}))
        window=Launcher(self.root)
        try:
            window.select_game('trap-team')
            with patch('tools.launcher_model.command',return_value=['python3','-c','pass']):
                window.launch()
            self.wait(lambda:window.process is None)
            saved=json.loads(pc.read_text())
            self.assertEqual(saved['controller_layout'],'keyboard-and-pad')
            self.assertEqual(saved['controller_glyphs'],'xbox')
        finally:
            window.close()

    def test_backdrop_palette_follows_logo_colors(self):
        from PyQt6.QtGui import QImage,QColor
        from tools.launcher_shell import logo_palette
        image=QImage(40,40,QImage.Format.Format_ARGB32);image.fill(QColor(0,0,0,0))
        for y in range(40):
            for x in range(40):
                if y<28:image.setPixelColor(x,y,QColor('#e53815'))
                elif y<36:image.setPixelColor(x,y,QColor('#2f8fd8'))
        path=self.root/'logo.png';image.save(str(path))
        primary,accent=logo_palette(path)
        self.assertLess(abs(primary.hue()-QColor('#e53815').hue()),15)
        self.assertLess(abs(accent.hue()-QColor('#2f8fd8').hue()),15)
        fallback=logo_palette(self.root/'missing.png',('#123456','#654321'))
        self.assertEqual([c.name() for c in fallback],['#123456','#654321'])

    def test_skylanders_manager_edits_and_places_figures(self):
        from test_figure_data import SEED, played
        from tools import figure_data
        assets=self.root/'.local/portal-assets';assets.mkdir(parents=True)
        (assets/'trap-metadata.seed').write_bytes(SEED);(assets/'figure-names.json').write_text(json.dumps({'14:0':'Gill Grunt','16:0':'Spyro'}))
        library=self.root/'out/portal-library/characters';library.mkdir(parents=True)
        (library/'created-water.sky').write_bytes(played(gold=100))
        (library/'created-fresh.sky').write_bytes(figure_data.blank(16,0))
        self.window.manager();page=self.window.portal_page
        self.assertIs(self.window.views.currentWidget(),page)
        self.assertEqual([e.name for e in page.entries],['Gill Grunt','Spyro'])
        page.list.setCurrentRow(1)
        self.assertFalse(page.gold.isEnabled());self.assertFalse(page.notice.isHidden())
        page.list.setCurrentRow(0)
        self.assertFalse(page.save_button.isEnabled())
        page.nickname.setText('Splashy');page.level.setValue(12);page.gold.setValue(4321)
        self.assertTrue(page.save_button.isEnabled())
        page.save()
        saved=figure_data.Figure((library/'created-water.sky').read_bytes(),SEED)
        self.assertEqual((saved.nickname,saved.level,saved.gold),('Splashy',12,4321))
        self.assertTrue(any((self.root/'out/figure-backups').iterdir()))
        page.toggle_portal()
        self.assertEqual(self.window.library['portal'],str(library/'created-water.sky'))
        self.assertEqual(self.window.fields['figure'].text(),str(library/'created-water.sky'))
        page.close_page();self.assertIs(self.window.views.currentWidget(),self.window.canvas)

    def test_loading_wheel_and_stop_until_game_window(self):
        self.window.select_game('trap-team')
        script="import time;print('SKYLANDERS_RUNTIME_LAUNCHED',flush=True);time.sleep(.3);print('SKYLANDERS_RUNTIME_STARTED',flush=True);time.sleep(60)"
        with patch('tools.launcher_model.command',return_value=['python3','-c',script]):
            self.window.launch()
        self.assertEqual(self.window.primary.text(),'LOADING')
        self.assertTrue(self.window.session_stop.isVisibleTo(self.window))
        self.assertTrue(self.window.loading_wheel.isVisibleTo(self.window))
        self.wait(lambda:self.window.launch_status.text()=='Starting game…')
        self.assertTrue(self.window.loading_wheel.isVisibleTo(self.window))
        self.wait(lambda:self.window.runtime_started)
        self.assertFalse(self.window.loading_wheel.isVisibleTo(self.window))
        self.assertTrue(self.window.session_stop.isVisibleTo(self.window))
        self.window.stop_game()
        self.wait(lambda:self.window.process is None)
        self.assertFalse(self.window.session_stop.isVisibleTo(self.window))
        self.assertEqual(self.window.status.text(),'Game stopped at your request.')

    def test_extractor_success_and_matching_update(self):
        tool=self.extractor('import sys,json,base64\nfrom pathlib import Path\n'
            'out=Path(sys.argv[2]);(out/"sce_sys").mkdir()\n'
            '(out/"sce_sys/param.sfo").write_bytes(base64.b64decode(Path(sys.argv[1]).read_text()))\n'
            '(out/"eboot.bin").write_bytes(b"synthetic")\nprint("Synthetic extraction complete")\n')
        self.window.select_game('trap-team');dialog=InstallDialog(self.window)
        dialog.fields['extractor'].setText(str(tool))
        for key,cat,ver in [('game_pkg','gd','01.00'),('update_pkg','gp','01.01')]:
            pkg=self.root/(key+'.pkg')
            pkg.write_text(base64.b64encode(sfo(dict(TITLE_ID='CUSA00626',CATEGORY=cat,APP_VER=ver,CONTENT_ID='test'))).decode())
            dialog.fields[key].setText(str(pkg))
        dialog.begin();self.wait(lambda: 'Extraction validated' in dialog.output.toPlainText())
        self.assertEqual(len(self.window.game['installed_paths']),2)
        self.assertFalse(self.window.play.isEnabled()) # no prepared runtime
        dialog.close()

    def test_extractor_failure_does_not_publish(self):
        tool=self.extractor('import sys\nprint("synthetic failure")\nsys.exit(7)\n')
        pkg=self.root/'base.pkg';pkg.write_bytes(b'synthetic')
        dialog=InstallDialog(self.window)
        dialog.fields['extractor'].setText(str(tool));dialog.fields['game_pkg'].setText(str(pkg))
        dialog.begin();self.wait(lambda: 'exit 7' in dialog.output.toPlainText())
        self.assertNotIn('installed_paths',self.window.game);dialog.close()

    def test_cancel_reaps_extractor_without_publishing(self):
        tool=self.extractor('import time\ntime.sleep(30)\n')
        pkg=self.root/'base.pkg';pkg.write_bytes(b'synthetic')
        dialog=InstallDialog(self.window)
        dialog.fields['extractor'].setText(str(tool));dialog.fields['game_pkg'].setText(str(pkg))
        dialog.begin();dialog.reject();self.wait(lambda: dialog.process is None)
        self.assertIn('cancelled',dialog.output.toPlainText())
        self.assertNotIn('installed_paths',self.window.game);dialog.close()
