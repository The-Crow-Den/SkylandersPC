# SPDX-License-Identifier: GPL-3.0-or-later
"""Library presentation layered over the existing native session controller."""
from pathlib import Path
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPixmap, QIcon, QRadialGradient, QPen
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMessageBox, QMenu, QStackedWidget)
try:
    from . import launcher_library as library
except ImportError:
    import launcher_library as library


class LoadingWheel(QWidget):
    def __init__(self):
        super().__init__();self.angle=0;self.setFixedSize(26,26)
        self.timer=QTimer(self);self.timer.setInterval(40);self.timer.timeout.connect(self.advance)
        self.hide()

    def advance(self):
        self.angle=(self.angle+12)%360;self.update()

    def set_active(self,active):
        self.setVisible(active)
        if active:self.timer.start()
        else:self.timer.stop()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen=QPen(QColor('#98dfef'),2.5);pen.setCapStyle(Qt.PenCapStyle.RoundCap);p.setPen(pen)
        p.drawArc(QRectF(4,4,18,18),-self.angle*16,260*16);p.end()


def utility_icon(kind):
    image = QPixmap(24,24); image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#c8c8d0'),1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == 'collection':
        for x in (4,14):
            for y in (4,14): p.drawRoundedRect(QRectF(x,y,6,6),1.5,1.5)
    elif kind == 'trophy':
        p.drawRoundedRect(QRectF(7,3,10,11),3,3);p.drawLine(12,14,12,20);p.drawLine(8,21,16,21)
        p.drawArc(QRectF(3,4,7,8),90*16,180*16);p.drawArc(QRectF(14,4,7,8),-90*16,180*16)
    elif kind == 'settings':
        for y,x in ((5,8),(12,16),(19,10)):
            p.drawLine(3,y,21,y);p.setBrush(QColor('#171719'));p.drawEllipse(QRectF(x-2.5,y-2.5,5,5))
    else:
        p.drawLine(12,5,12,19);p.drawLine(5,12,19,12)
    p.end();return QIcon(image)


class SkyCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.game = {}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#101012'))
        glow = QRadialGradient(self.width()*.56,self.height()*.47,self.width()*.55)
        tint = QColor(self.game.get('top','#326080')); tint.setAlpha(32)
        glow.setColorAt(0,tint);glow.setColorAt(1,QColor('#00101012'))
        p.fillRect(self.rect(),glow)
        p.end()


def supplied_artwork(root, game):
    """Resolve supplied logos; launcher backgrounds are deliberately image-free."""
    folder = Path(root) / '.local/launcher-art/supplied'
    logo = {'swap-force': 'swap-force-logo.png', 'trap-team': 'trap-team-logo-cutout.png',
            'superchargers': 'superchargers-logo.png', 'imaginators': 'imaginators-logo.png'}.get(game['id'])
    themed = dict(game)
    themed.update(background='', composite=False)
    if logo and (folder / logo).is_file():
        themed['logo'] = str(folder / logo)
    return themed


def renovated(base):
    class LibraryLauncher(base):
        def __init__(self, root=None):
            if root is None:
                super().__init__()
            else:
                super().__init__(root)
            if self.preferences.exists():
                try:
                    try:
                        from . import launcher_model
                    except ImportError:
                        import launcher_model
                    self.apply_values(launcher_model.load(self.preferences))
                except (OSError, ValueError) as error:
                    self.log.append(str(error))
            self.library_path = self.root / '.local/launcher-library.json'
            try:
                self.library = library.load(self.library_path)
            except (OSError, ValueError) as error:
                self.library = library.defaults()
                self.log.append(f'Library could not be loaded: {error}')
            self.legacy = self.takeCentralWidget()
            self.legacy.setParent(self);self.legacy.hide()
            self.views = QStackedWidget();self.setCentralWidget(self.views)
            self.canvas = SkyCanvas();self.views.addWidget(self.canvas)
            self.setWindowTitle('Skylanders · Portal Library')
            self.resize(1440, 850); self.setMinimumSize(1000, 680)
            layout = QHBoxLayout(self.canvas); layout.setContentsMargins(18,18,32,24); layout.setSpacing(32)
            rail = QWidget(); rail.setObjectName('libraryRail'); rail.setFixedWidth(104)
            self.rail = QVBoxLayout(rail); self.rail.setContentsMargins(10,22,10,16); self.rail.setSpacing(12)
            layout.addWidget(rail)
            main = QVBoxLayout(); layout.addLayout(main, 1)
            top = QHBoxLayout()
            heading = QLabel('Library'); heading.setStyleSheet('font-size: 22px; font-weight: 600;')
            top.addWidget(heading); top.addStretch()
            for title, callback in [('Skylanders Manager', self.manager), ('Settings', self.game_settings)]:
                pill = self.button(top, title, callback)
                if title == 'Settings':
                    pill.setObjectName('gameSettings');pill.setToolTip('Settings and tweaks for the selected game')
                pill.setStyleSheet('background: #222225; border: 1px solid #343438; border-radius: 12px; padding: 12px 18px; font-size: 14px;')
            main.addLayout(top); main.addStretch(3)
            self.brand = QLabel('SKYLANDERS'); self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.brand.setStyleSheet('font-size: 64px; font-weight: 900; color: white;')
            main.addWidget(self.brand)
            self.subtitle = QLabel(); self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.subtitle.setStyleSheet('font-size: 40px; font-weight: 900; color: #fff2b1;')
            main.addWidget(self.subtitle)
            main.addStretch(3)
            bottom = QHBoxLayout()
            self.trophies = self.button(bottom, 'Trophies  —%', self.trophy_tracker)
            self.trophies.setIcon(utility_icon('trophy'));self.trophies.setIconSize(QSize(24,24))
            self.trophies.setStyleSheet('background: transparent; border: none; text-align: left; color: #a9a9b1; padding: 12px 0; font-size: 14px;')
            bottom.addStretch()
            self.loading_wheel=LoadingWheel();bottom.addWidget(self.loading_wheel)
            self.launch_status=QLabel();self.launch_status.setStyleSheet('color: #a9a9b1;');self.launch_status.hide();bottom.addWidget(self.launch_status)
            self.session_stop = self.button(bottom, 'Stop', self.stop_game)
            self.session_stop.setVisible(False)
            self.primary = self.button(bottom, 'INSTALL', self.primary_action)
            self.primary.setObjectName('libraryPlay'); self.primary.setMinimumSize(190,56)
            self.button(bottom, '•••', self.game_menu)
            main.addLayout(bottom)
            self.setStyleSheet(self.styleSheet() + '''
                QWidget#libraryRail { background: #18181c; border: 1px solid #303037; border-radius: 24px; }
                QPushButton#gameIcon { border: 1px solid transparent; background: #202024; border-radius: 16px; padding: 6px; font-size: 14px; font-weight: 600; }
                QPushButton#gameIcon:hover { background: #303037; border-color: #50505a; }
                QPushButton#gameIcon:checked { background: #343e46; color: #f5f5f7; border: 1px solid #98dfef; border-radius: 16px; }
                QPushButton#libraryPlay { background: #fafafa; color: #10121a; border: none; border-radius: 14px; font-family: "Cantarell", "DejaVu Sans", sans-serif; font-size: 17px; font-weight: 700; letter-spacing: 0.5px; }
                QDialog { background: #171719; }
                QListWidget { background: #222225; color: #f5f5f7; border: 1px solid #343438; border-radius: 12px; padding: 10px; }
                QListWidget::item { padding: 12px; border-radius: 6px; }
                QListWidget::item:selected { background: #353539; color: white; }
            ''')
            if self.library['portal'] and Path(self.library['portal']).is_file():
                self.fields['figure'].setText(self.library['portal'])
            self.rebuild_rail()
            try:
                from .launcher_settings import SettingsPage
            except ImportError:
                from launcher_settings import SettingsPage
            self.settings_page = SettingsPage(self);self.views.addWidget(self.settings_page)
            try:
                from .launcher_portal import PortalPage
            except ImportError:
                from launcher_portal import PortalPage
            self.portal_page = PortalPage(self);self.views.addWidget(self.portal_page)

        @property
        def game(self):
            return next(g for g in self.library['games'] if g['id'] == self.library['selected'])

        def persist(self):
            try:
                library.save(self.library_path, self.library)
            except OSError as error:
                QMessageBox.warning(self, 'Cannot save library', str(error))

        def button(self, layout, text, callback):
            button = QPushButton(text); button.clicked.connect(callback); layout.addWidget(button)
            return button

        def rebuild_rail(self):
            while self.rail.count():
                item = self.rail.takeAt(0)
                if item.widget():
                    item.widget().hide(); item.widget().deleteLater()
            for game in self.library['games']:
                button = self.button(self.rail, '',
                                     lambda checked=False, key=game['id']: self.select_game(key))
                button.setObjectName('gameIcon'); button.setCheckable(True)
                button.setChecked(game['id'] == self.library['selected']); button.setFixedSize(82,76)
                button.setToolTip(game['name']); button.setAccessibleName(game['name'])
                logo = QPixmap(supplied_artwork(self.root, game)['logo'])
                if not logo.isNull():
                    button.setIcon(QIcon(logo));button.setIconSize(QSize(70,48))
                else:
                    button.setText({'superchargers':'SC','imaginators':'IM'}.get(game['id'],game['name'][:2].upper()))
            self.rail.addStretch()
            divider = QWidget();divider.setFixedHeight(1);divider.setStyleSheet('background: #38383e;');self.rail.addWidget(divider)
            for kind, name, callback in [('collection','Skylanders Manager',self.manager),('settings','General settings',self.settings)]:
                control = self.button(self.rail,'',callback);control.setIcon(utility_icon(kind));control.setIconSize(QSize(24,24))
                control.setFixedSize(82,48);control.setToolTip(name);control.setAccessibleName(name)
                control.setStyleSheet('background: transparent; border: none; border-radius: 12px;')
            self.refresh_game()

        def select_game(self, key):
            if self.process:
                QMessageBox.information(self, 'Session active', 'Stop the current session before switching games.'); return
            self.library['selected'] = key; self.persist(); self.rebuild_rail()

        def refresh_game(self):
            themed = supplied_artwork(self.root, self.game)
            self.canvas.game = themed; self.canvas.update()
            logo = QPixmap(themed['logo'])
            self.brand.clear(); self.subtitle.clear()

            self.brand.setVisible(not themed['composite'])
            self.subtitle.hide()
            if not themed['composite']:
                if not logo.isNull():
                    self.brand.setPixmap(logo.scaled(610,280,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                else:
                    self.brand.setText(self.game['name'])
            ready = self.game['id'] == 'trap-team' and self.play.isEnabled()
            self.primary.setText('PLAY' if ready else ('SETUP' if self.game['game_pkg'] else 'INSTALL'))
            try:
                try:
                    from .launcher_trophies import snapshot
                except ImportError:
                    from launcher_trophies import snapshot
                data=snapshot(self.root,self.game)
                percent=f"{data['percent']}%" if data['percent'] is not None else '—%'
                self.trophies.setText('Trophies  '+percent)
                self.trophies.setToolTip(f"{data['total']} available trophies. Click to browse.\n"+data['message'])
            except (OSError,ValueError,UnicodeError) as error:
                self.trophies.setText('Trophies  —%');self.trophies.setToolTip(str(error))

        def trophy_tracker(self):
            try:
                from .launcher_trophy_dialog import TrophyDialog
            except ImportError:
                from launcher_trophy_dialog import TrophyDialog
            TrophyDialog(self).exec()

        def primary_action(self):
            if self.process: return
            if self.game['id'] == 'trap-team' and self.play.isEnabled():
                self.launch()
                return
            self.install()

        def launch(self):
            if self.process is not None: return
            if self.game['id'] != 'trap-team':
                QMessageBox.information(self, 'Runtime unavailable', 'The native session runner currently supports Trap Team.'); return
            universal = self.values()
            self.session_universal = universal
            try:
                self.apply_values({**universal, **self.game['settings']})
                try:
                    from .launcher_mods import selection
                except ImportError:
                    from launcher_mods import selection
                self.session_mods = selection(self.root,self.game)
                super().launch()
                if self.process is not None:
                    self.runtime_started=False;self.session_stop.setEnabled(True);self.session_stop.setText('Stop')
                    self.session_stop.show();self.primary.setEnabled(False);self.primary.setText('LOADING')
                    self.launch_status.setText('Preparing game…');self.launch_status.show();self.loading_wheel.set_active(True)
            finally:
                self.apply_values(universal)
                try:
                    try:
                        from . import launcher_model
                    except ImportError:
                        import launcher_model
                    launcher_model.save(self.preferences, universal)
                except OSError as error:
                    self.log.append(f'Universal settings could not be saved: {error}')

        def read_output(self):
            super().read_output()
            if not hasattr(self,'loading_wheel') or self.stopping or getattr(self,'runtime_started',True): return
            if 'SKYLANDERS_RUNTIME_LAUNCHED' in self.output_buffer:
                self.launch_status.setText('Starting game…')
            if 'SKYLANDERS_RUNTIME_STARTED' in self.output_buffer:
                self.runtime_started=True;self.loading_wheel.set_active(False)
                self.launch_status.setText('Game running');self.primary.setText('RUNNING')
                self.status.setText('Session active · F6 opens PC settings in game')

        def stop_game(self):
            super().stop_game()
            if self.process is not None:
                self.session_stop.setEnabled(False);self.session_stop.setText('Stopping…')
                self.launch_status.setText('Stopping session…')

        def settings(self):
            self.settings_page.open()

        def install(self):
            if self.process:
                QMessageBox.information(self, 'Session active', 'Stop the game before installing packages.'); return
            try:
                from .launcher_install_dialog import InstallDialog
            except ImportError:
                from launcher_install_dialog import InstallDialog
            InstallDialog(self).exec()

        def game_menu(self):
            menu = QMenu(self)
            for title, callback in [('Install / update PKGs',self.install), ('Game settings',self.game_settings),
                                    ('Skylanders Manager',self.manager)]:
                menu.addAction(title, callback)
            menu.exec(self.primary.mapToGlobal(self.primary.rect().topRight()))

        def game_settings(self):
            self.settings_page.open(self.game)

        def manager(self):
            self.portal_page.open()

        def finished(self, code, status):
            super().finished(code,status)
            if hasattr(self, 'session_universal'):
                self.apply_values(self.session_universal)
            if hasattr(self,'canvas'):
                self.loading_wheel.set_active(False);self.launch_status.hide()
                self.session_stop.setVisible(False); self.primary.setEnabled(True); self.refresh_game()
            if hasattr(self,'portal_page') and self.views.currentWidget() is self.portal_page:
                self.portal_page.refresh()

        def closeEvent(self, event):
            if self.process is None: self.persist()
            super().closeEvent(event)
    return LibraryLauncher
