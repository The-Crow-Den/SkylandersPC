# SPDX-License-Identifier: GPL-3.0-or-later
"""Library presentation layered over the existing native session controller."""
from functools import lru_cache
from pathlib import Path
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap, QIcon, QRadialGradient, QPen
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMessageBox, QMenu, QStackedWidget)
try:
    from . import game_library
    from . import launcher_library as library
except ImportError:
    import game_library
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


def logo_palette(path, fallback=('#326080', '#bd9ad8')):
    """The logo's dominant hue and a contrasting accent, for a matching backdrop."""
    image = QImage(str(path)) if path else QImage()
    if image.isNull():
        return QColor(fallback[0]), QColor(fallback[1])
    image = image.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio).convertToFormat(QImage.Format.Format_ARGB32)
    bins = [[0.0, 0.0, 0.0, 0.0] for _ in range(12)]
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 200 or color.hsvSaturationF() < .35 or color.valueF() < .25:
                continue
            weight = color.hsvSaturationF() * color.valueF()
            entry = bins[int(max(color.hsvHueF(), 0) * 12) % 12]
            entry[0] += weight; entry[1] += color.redF() * weight; entry[2] += color.greenF() * weight; entry[3] += color.blueF() * weight
    ranked = sorted(range(12), key=lambda i: -bins[i][0])
    if not bins[ranked[0]][0]:
        return QColor(fallback[0]), QColor(fallback[1])
    def average(i):
        w, r, g, b = bins[i]; return QColor.fromRgbF(r / w, g / w, b / w)
    primary = ranked[0]
    accent = next((i for i in ranked[1:] if bins[i][0] > bins[primary][0] * .08 and min((i - primary) % 12, (primary - i) % 12) >= 2), None)
    return average(primary), average(accent) if accent is not None else average(primary).lighter(150)


def shade(color, value, saturation=1.0, alpha=255):
    result = QColor.fromHsvF(max(color.hsvHueF(), 0), min(1, color.hsvSaturationF() * saturation), value)
    result.setAlpha(alpha); return result


class SkyCanvas(QWidget):
    def __init__(self, *, show_portal=True):
        super().__init__()
        self.show_portal = show_portal
        self.game = {}; self.palette_cache = {}; self.anchor = None
        # Every game's portal matches the Swap Force logo's width (set by the shell).
        self.portal_logo_width = None

    def colors(self):
        key = (self.game.get('logo', ''), self.game.get('top'), self.game.get('bottom'))
        if key not in self.palette_cache:
            self.palette_cache[key] = logo_palette(key[0], (key[1] or '#326080', key[2] or '#bd9ad8'))
        return self.palette_cache[key]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        primary, accent = self.colors()
        w, h = self.width(), self.height()
        sky = QLinearGradient(0, 0, 0, h)
        sky.setColorAt(0, shade(primary, .16, .9)); sky.setColorAt(.55, shade(primary, .08, .7)); sky.setColorAt(1, QColor('#0b0b0e'))
        p.fillRect(self.rect(), sky)
        def glow(x, y, radius, color, alpha):
            gradient = QRadialGradient(x, y, radius)
            inner = QColor(color); inner.setAlpha(alpha); outer = QColor(color); outer.setAlpha(0)
            gradient.setColorAt(0, inner); gradient.setColorAt(1, outer); p.fillRect(self.rect(), gradient)
        glow(w * .56, h * .45, max(w, h) * .42, shade(primary, .9, 1.0), 95)
        glow(w * .80, h * .78, max(w, h) * .38, shade(accent, .8, 1.0), 38)
        glow(w * .30, h * .20, max(w, h) * .30, shade(accent, .7, .8), 22)
        # Floor light under the logo, like a portal glow.
        floor = QRadialGradient(w * .56, h * 1.02, w * .45)
        lit = shade(accent, .9, 1.0, 46); floor.setColorAt(0, lit); lit = QColor(lit); lit.setAlpha(0); floor.setColorAt(1, lit)
        p.fillRect(self.rect(), floor)
        # A faint, fixed sparkle field; positions depend only on the game.
        seed = sum(map(ord, self.game.get('id', ''))) or 7
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(70):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff; x = seed % 10000 / 10000
            seed = (seed * 1103515245 + 12345) & 0x7fffffff; y = seed % 10000 / 10000
            seed = (seed * 1103515245 + 12345) & 0x7fffffff; size = .8 + (seed % 100) / 70
            star = shade(accent if i % 3 else primary, 1.0, .35, 30 + seed % 70)
            p.setBrush(star); p.drawEllipse(QRectF(x * w, y * h * .9, size, size))
        if self.show_portal:
            self.paint_portal(p, primary, accent)
        vignette = QRadialGradient(w * .55, h * .5, max(w, h) * .75)
        vignette.setColorAt(.6, QColor(0, 0, 0, 0)); vignette.setColorAt(1, QColor(0, 0, 0, 120))
        p.fillRect(self.rect(), vignette)
        p.end()


    def logo_rect(self):
        """Where the logo is drawn, in canvas coordinates."""
        label = self.anchor
        if label is None or not label.isVisible():
            return QRectF(self.width() * .3, self.height() * .3, self.width() * .45, self.height() * .3)
        pixmap = label.pixmap(); top_left = label.mapTo(self, label.rect().topLeft())
        area = QRectF(top_left.x(), top_left.y(), label.width(), label.height())
        if pixmap is None or pixmap.isNull():
            return area.adjusted(area.width() * .25, 0, -area.width() * .25, 0)
        size = pixmap.deviceIndependentSize()
        return QRectF(area.center().x() - size.width() / 2, area.center().y() - size.height() / 2, size.width(), size.height())

    def paint_portal(self, p, primary, accent):
        """A decorative portal of light beneath the logo, in the logo's colours."""
        logo = self.logo_rect()
        cx = logo.center().x(); width = max(260.0, (self.portal_logo_width or logo.width()) * .78); height = width * .16
        cy = min(self.height() - 120.0, logo.bottom() + height * .9)
        bright = shade(accent, 1.0, .75); deep = shade(primary, .55, 1.0)
        # Light column rising from the portal behind the logo.
        beam = QLinearGradient(0, cy, 0, logo.top() - 40)
        beam.setColorAt(0, shade(bright, 1.0, 1.0, 70)); beam.setColorAt(1, shade(bright, 1.0, 1.0, 0))
        column = QPainterPath(); column.moveTo(cx - width * .42, cy); column.lineTo(cx - width * .30, logo.top() - 40)
        column.lineTo(cx + width * .30, logo.top() - 40); column.lineTo(cx + width * .42, cy); column.closeSubpath()
        p.fillPath(column, beam)
        halo = QRadialGradient(cx, cy, width * .75)
        halo.setColorAt(0, shade(bright, 1.0, 1.0, 85)); halo.setColorAt(1, shade(bright, 1.0, 1.0, 0))
        p.save(); p.translate(cx, cy); p.scale(1, .32); p.translate(-cx, -cy)
        p.fillRect(QRectF(cx - width, cy - width, width * 2, width * 2), halo); p.restore()
        # Platform: base, lit rim, inner rings.
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(shade(primary, .14, 1.0, 230))
        p.drawEllipse(QRectF(cx - width / 2, cy - height / 2 + height * .28, width, height))
        face = QRadialGradient(cx, cy, width / 2)
        face.setColorAt(0, shade(deep, .9, 1.0, 200)); face.setColorAt(.75, shade(deep, .45, 1.0, 220)); face.setColorAt(1, shade(deep, .25, 1.0, 235))
        p.setBrush(face); p.drawEllipse(QRectF(cx - width / 2, cy - height / 2, width, height))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(shade(bright, 1.0, 1.0, 210), 2.5)); p.drawEllipse(QRectF(cx - width / 2, cy - height / 2, width, height))
        p.setPen(QPen(shade(bright, 1.0, 1.0, 110), 1.2)); p.drawEllipse(QRectF(cx - width * .38, cy - height * .38, width * .76, height * .76))
        p.setPen(QPen(shade(bright, 1.0, 1.0, 60), 1)); p.drawEllipse(QRectF(cx - width * .24, cy - height * .24, width * .48, height * .48))
        # Sparks drifting up from the rim; fixed per game.
        seed = (sum(map(ord, self.game.get('id', ''))) or 7) * 7919
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(16):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff; t = seed % 1000 / 1000
            seed = (seed * 1103515245 + 12345) & 0x7fffffff; rise = seed % 1000 / 1000
            x = cx + (t - .5) * width * .8; y = cy - rise * (cy - logo.top() + 30); r = 1.2 + (1 - rise) * 1.8
            spark = QRadialGradient(x, y, r * 3)
            spark.setColorAt(0, shade(bright, 1.0, .5, int(200 * (1 - rise * .7)))); spark.setColorAt(1, shade(bright, 1.0, .5, 0))
            p.setBrush(spark); p.drawEllipse(QRectF(x - r * 3, y - r * 3, r * 6, r * 6))


LOGO_BOX = QSize(610, 280)      # the Swap Force logo fills this; others match its width
LOGO_MAX_HEIGHT = 330


@lru_cache(maxsize=16)
def visible_fraction(path, threshold=64):
    """Share of the image width holding opaque artwork, ignoring margins and soft glow."""
    image = QImage(path)
    if image.isNull():
        return 1.0
    small = image.scaledToWidth(min(400, image.width())).convertToFormat(QImage.Format.Format_ARGB32)
    columns = [x for x in range(small.width())
               if any(small.pixel(x, y) >> 24 > threshold for y in range(small.height()))]
    return (columns[-1] - columns[0] + 1) / small.width() if columns else 1.0


def logo_size(path, reference):
    """Display size giving the logo the same visible width as the reference logo."""
    image, model = QImage(path), QImage(reference)
    if image.isNull():
        return LOGO_BOX
    if model.isNull():
        return image.size().scaled(LOGO_BOX, Qt.AspectRatioMode.KeepAspectRatio)
    target = model.size().scaled(LOGO_BOX, Qt.AspectRatioMode.KeepAspectRatio).width() * visible_fraction(reference)
    width = target / visible_fraction(path)
    return image.size().scaled(QSize(round(width), LOGO_MAX_HEIGHT), Qt.AspectRatioMode.KeepAspectRatio)


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
            try:
                library.sync_installations(self.root, self.library)
            except (OSError, ValueError) as error:
                self.log.append(f'Installations could not be loaded: {error}')
            self.legacy = self.takeCentralWidget()
            self.legacy.setParent(self);self.legacy.hide()
            self.views = QStackedWidget();self.setCentralWidget(self.views)
            self.canvas = SkyCanvas();self.views.addWidget(self.canvas)
            self.setWindowTitle('Skylanders PC')
            self.resize(1440, 850); self.setMinimumSize(1000, 680)
            layout = QHBoxLayout(self.canvas); layout.setContentsMargins(18,18,32,24); layout.setSpacing(32)
            rail = QWidget(); rail.setObjectName('libraryRail'); rail.setFixedWidth(104)
            self.rail = QVBoxLayout(rail); self.rail.setContentsMargins(10,22,10,16); self.rail.setSpacing(12)
            layout.addWidget(rail)
            main = QVBoxLayout(); layout.addLayout(main, 1)
            top = QHBoxLayout()
            heading = QLabel('Library'); heading.setStyleSheet('font-size: 22px; font-weight: 600;')
            top.addWidget(heading); top.addStretch()
            self.button(top, 'Open games folder', self.open_games_folder)
            for title, callback in [('Skylanders Manager', self.manager), ('Settings', self.game_settings)]:
                pill = self.button(top, title, callback)
                if title == 'Settings':
                    pill.setObjectName('gameSettings');pill.setToolTip('Settings and tweaks for the selected game')
                pill.setStyleSheet('background: rgba(20,20,26,0.6); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px 18px; font-size: 14px;')
            main.addLayout(top); main.addStretch(3)
            self.brand = QLabel('SKYLANDERS'); self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.brand.setStyleSheet('font-size: 64px; font-weight: 900; color: white;')
            main.addWidget(self.brand)
            self.subtitle = QLabel(); self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.subtitle.setStyleSheet('font-size: 40px; font-weight: 900; color: #fff2b1;')
            main.addWidget(self.subtitle)
            self.canvas.anchor = self.brand
            main.addStretch(3)
            bottom = QHBoxLayout()
            self.trophies = self.button(bottom, 'Trophies  —%', self.trophy_tracker)
            self.trophies.setIcon(utility_icon('trophy'));self.trophies.setIconSize(QSize(24,24))
            self.trophies.setStyleSheet('background: transparent; border: none; text-align: left; color: #a9a9b1; padding: 12px 0; font-size: 14px;')
            self.install_note = QLabel(); self.install_note.setWordWrap(True)
            self.install_note.setStyleSheet('color: #a9a9b1;');bottom.addWidget(self.install_note,1)
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
                QWidget#libraryRail { background: rgba(14,14,18,0.62); border: 1px solid rgba(255,255,255,0.08); border-radius: 24px; }
                QPushButton#gameIcon { border: 1px solid transparent; background: rgba(255,255,255,0.05); border-radius: 16px; padding: 6px; font-size: 14px; font-weight: 600; }
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
            try:
                game_library.select(self.root, self.game.get('installation'))
            except (OSError, ValueError) as error:
                self.log.append(f'Installation selection could not be saved: {error}')

        def open_games_folder(self):
            try:
                library.open_games_folder(self.root)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, 'Cannot open Games folder', str(error))

        def refresh_game(self):
            choices = []
            try:
                library.sync_installations(self.root, self.library)
                choices = game_library.for_game(self.root, self.game)
            except (OSError, ValueError) as error:
                self.log.append(str(error))
            self.refresh_readiness()
            themed = supplied_artwork(self.root, self.game)
            self.canvas.game = themed
            reference = supplied_artwork(self.root, {'id': 'swap-force'}).get('logo', '')
            self.canvas.portal_logo_width = logo_size(reference, reference).width() if Path(reference).is_file() else None
            self.canvas.update()
            logo = QPixmap(themed['logo'])
            self.brand.clear(); self.subtitle.clear()

            self.brand.setVisible(not themed['composite'])
            self.subtitle.hide()
            if not themed['composite']:
                if not logo.isNull():
                    self.brand.setPixmap(logo.scaled(logo_size(themed['logo'], reference),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                else:
                    self.brand.setText(self.game['name'])
            ready = self.play.isEnabled()
            self.primary.setText('PLAY' if ready else ('INSTALLED' if choices else 'INSTALL'))
            self.primary.setEnabled(ready or not choices)
            if choices and not ready:
                entry = game_library.resolve_entry(self.root, game=self.game)
                message = 'Game files installed. Setup is still needed before you can play.' if game_library.supported(self.root, entry) else 'Game files installed. This game is not supported yet.'
                self.install_note.setText(message)
            else:
                self.install_note.clear()
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
            if self.play.isEnabled():
                self.launch()
                return
            self.install()

        def launch(self):
            if self.process is not None: return

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
            session_status = self.status.text()
            if hasattr(self, 'session_universal'):
                self.apply_values(self.session_universal)
            if hasattr(self,'canvas'):
                self.loading_wheel.set_active(False);self.launch_status.hide()
                self.session_stop.setVisible(False); self.primary.setEnabled(True); self.refresh_game()
                self.status.setText(session_status)
            if hasattr(self,'portal_page') and self.views.currentWidget() is self.portal_page:
                self.portal_page.refresh()

        def closeEvent(self, event):
            if self.process is None: self.persist()
            super().closeEvent(event)
    return LibraryLauncher
