# SPDX-License-Identifier: GPL-3.0-or-later
"""Skylanders Manager: the virtual portal collection with progress editing."""
import json
from pathlib import Path
import struct
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QFont, QIcon
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QSpinBox, QProgressBar, QDialog, QFileDialog, QMessageBox, QFrame)
try:
    from . import figure_data
    from .figure_collection import Collection
except ImportError:
    import figure_data
    from figure_collection import Collection

CELL = 96


class Portraits:
    """Identification portraits: the original cached pictures, else the drawer atlas."""
    def __init__(self, root):
        self.cells = {}; self.files = {}; self.atlas = QImage(); self.cache = {}
        folder = Path(root) / '.local/portal-assets'
        try:
            lines = (folder / 'portrait-index.txt').read_text().split('\n')
            for line in lines[1:]:
                parts = line.split()
                if len(parts) == 3: self.cells[(int(parts[0]), int(parts[1]))] = int(parts[2])
            sources = json.loads((folder / 'sources.json').read_text()).get('sources', [])
            self.files = {s['cell']: folder / s['cache'] for s in sources
                          if s.get('kind') == 'figure' and isinstance(s.get('cell'), int) and '/' not in str(s.get('cache', '/'))}
            data = (folder / 'portraits.rgba').read_bytes()
            width, height = struct.unpack('<II', data[:8])
            if len(data) == 8 + width * height * 4:
                self.atlas = QImage(data[8:], width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        except (OSError, ValueError, KeyError, struct.error):
            pass

    def get(self, identity, variant):
        cell = self.cells.get((identity, variant), self.cells.get((identity, 0)))
        if cell is None: return QPixmap()
        if cell not in self.cache:
            picture = QPixmap(str(self.files[cell])) if cell in self.files else QPixmap()
            if picture.isNull() and not self.atlas.isNull():
                columns = self.atlas.width() // CELL
                picture = QPixmap.fromImage(self.atlas.copy((cell % columns) * CELL + 4, (cell // columns) * CELL + 4, CELL - 8, CELL - 8))
            self.cache[cell] = picture
        return self.cache[cell]


def tile(pixmap, size, ring='#98dfef', fallback=''):
    """A rounded portrait card showing the whole picture, rendered for the screen's pixel density."""
    screen = QGuiApplication.primaryScreen(); ratio = screen.devicePixelRatio() if screen else 1.0
    image = QPixmap(int(size * ratio), int(size * ratio)); image.setDevicePixelRatio(ratio); image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    inset = max(1.5, size / 40); card = QRectF(inset, inset, size - 2 * inset, size - 2 * inset); radius = size * .2
    path = QPainterPath(); path.addRoundedRect(card, radius, radius)
    p.fillPath(path, QColor('#1d2c38'))
    if not pixmap.isNull():
        scaled = pixmap.scaled(QSize(int(card.width() * ratio), int(card.height() * ratio)), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        p.setClipPath(path)
        p.drawPixmap(QPointF(card.center().x() - scaled.width() / ratio / 2, card.center().y() - scaled.height() / ratio / 2), scaled)
        p.setClipping(False)
    elif fallback:
        p.setPen(QColor('#cbf5ff')); p.setFont(QFont('Cantarell', max(9, size // 4), QFont.Weight.Bold))
        p.drawText(card, Qt.AlignmentFlag.AlignCenter, fallback[:1].upper())
    p.setPen(QPen(QColor(ring), max(1.2, size / 50))); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(card, radius, radius)
    p.end(); return image


class PortalStage(QWidget):
    """The selected figure standing on a glowing portal."""
    def __init__(self):
        super().__init__(); self.portrait = QPixmap(); self.name = ''; self.active = False
        self.setMinimumSize(190, 220)

    def show_figure(self, portrait, name, active):
        self.portrait, self.name, self.active = portrait, name, active; self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Centre the figure and portal as one group in the available height.
        # Sources are ~128 px; keep near native size so they stay sharp.
        size = int(min(168, self.width() - 60, self.height() - 120)); x = self.width() / 2
        base = min(self.height() - 46, (self.height() + size) / 2 + 10)
        glow = QRadialGradient(x, base - 30, 150)
        glow.setColorAt(0, QColor(63, 214, 255, 90 if self.active else 45)); glow.setColorAt(1, QColor(63, 214, 255, 0))
        p.fillRect(self.rect(), glow)
        p.setBrush(QColor('#142f49')); p.setPen(QPen(QColor('#4a8da8'), 3)); p.drawEllipse(QRectF(x - 110, base - 10, 220, 52))
        p.setBrush(QColor('#204760')); p.setPen(QPen(QColor('#90eaff' if self.active else '#43819b'), 4)); p.drawEllipse(QRectF(x - 110, base - 22, 220, 52))
        p.setPen(QPen(QColor('#4dbbd6'), 1)); p.drawEllipse(QRectF(x - 92, base - 14, 184, 36))
        if self.name and size > 40:
            p.drawPixmap(int(x - size / 2), int(base - size - 6), tile(self.portrait, size, '#90eaff' if self.active else '#5d8ea5', self.name))
        p.end()


class CreateDialog(QDialog):
    def __init__(self, parent, collection, portraits):
        super().__init__(parent); self.setWindowTitle('Create a Skylander'); self.resize(520, 620); self.choice = None
        column = QVBoxLayout(self); column.setContentsMargins(22, 22, 22, 18); column.setSpacing(12)
        title = QLabel('Create a Skylander'); title.setStyleSheet('font-size: 22px; font-weight: 600;'); column.addWidget(title)
        hint = QLabel('New figures start at level 1 and appear in the in-game portal drawer too.')
        hint.setWordWrap(True); hint.setStyleSheet('color: #92929e;'); column.addWidget(hint)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search Skylanders and items'); self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter); column.addWidget(self.search)
        self.list = QListWidget(); self.list.setIconSize(QSize(40, 40)); column.addWidget(self.list, 1)
        for name, identity, variant in collection.choices():
            item = QListWidgetItem(QIcon(tile(portraits.get(identity, variant), 40, '#5d8ea5', name)), name)
            item.setData(Qt.ItemDataRole.UserRole, (identity, variant)); self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda item: self.accept())
        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject); row.addWidget(cancel)
        self.create = QPushButton('Create'); self.create.setObjectName('portalPrimary'); self.create.clicked.connect(self.accept); row.addWidget(self.create)
        column.addLayout(row)
        self.list.currentItemChanged.connect(lambda item, _: self.create.setEnabled(item is not None)); self.create.setEnabled(False)
        if not self.list.count():
            hint.setText('The figure list is unavailable. It is read from the portal sources used by the native build.')

    def filter(self, text):
        for i in range(self.list.count()):
            item = self.list.item(i); item.setHidden(text.strip().lower() not in item.text().lower())

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden(): return
        self.choice = item.data(Qt.ItemDataRole.UserRole); super().accept()


class PortalPage(QWidget):
    def __init__(self, owner):
        super().__init__(); self.owner = owner; self.collection = None; self.entries = []; self.entry = None; self.loading = False
        self.portraits = Portraits(owner.root)
        self.setObjectName('portalPage')
        outer = QHBoxLayout(self); outer.setContentsMargins(36, 28, 36, 24); outer.addStretch()
        content = QWidget(); content.setMaximumWidth(1180); outer.addWidget(content, 1); outer.addStretch()
        layout = QVBoxLayout(content); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(18)
        header = QHBoxLayout(); back = QPushButton('‹  Library'); back.setObjectName('portalBack'); back.clicked.connect(self.close_page)
        header.addWidget(back); header.addStretch()
        self.lock = QLabel('Editing is paused while a game is running'); self.lock.setObjectName('portalLock'); header.addWidget(self.lock)
        layout.addLayout(header)
        title = QLabel('Skylanders Manager'); title.setStyleSheet('font-size: 30px; font-weight: 600;'); layout.addWidget(title)
        intro = QLabel('Your virtual collection. Changes are saved to the figure the game reads, with a backup of the previous state.')
        intro.setStyleSheet('color: #92929e; font-size: 14px;'); intro.setWordWrap(True); layout.addWidget(intro)
        body = QHBoxLayout(); body.setSpacing(20); layout.addLayout(body, 1)

        side = QFrame(); side.setObjectName('portalPanel'); side.setMinimumWidth(270); side.setMaximumWidth(370); body.addWidget(side, 3)
        left = QVBoxLayout(side); left.setContentsMargins(16, 16, 16, 16); left.setSpacing(12)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search your collection'); self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter); left.addWidget(self.search)
        self.list = QListWidget(); self.list.setObjectName('portalList'); self.list.setIconSize(QSize(52, 52))
        self.list.currentRowChanged.connect(self.select); left.addWidget(self.list, 1)
        self.empty = QLabel('No virtual Skylanders yet.\nCreate one or import a figure dump.'); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet('color: #92929e; padding: 30px 0;'); left.addWidget(self.empty)
        actions = QHBoxLayout()
        self.create_button = QPushButton('＋  Create'); self.create_button.setObjectName('portalPrimary'); self.create_button.clicked.connect(self.create)
        self.import_button = QPushButton('Import…'); self.import_button.clicked.connect(self.import_dump)
        actions.addWidget(self.create_button, 1); actions.addWidget(self.import_button, 1); left.addLayout(actions)

        detail = QFrame(); detail.setObjectName('portalPanel'); body.addWidget(detail, 7)
        right = QHBoxLayout(detail); right.setContentsMargins(26, 22, 26, 22); right.setSpacing(26)
        stage_column = QVBoxLayout(); stage_column.setSpacing(10)
        self.stage = PortalStage(); stage_column.addWidget(self.stage, 1)
        self.place = QPushButton('Place on portal'); self.place.clicked.connect(self.toggle_portal); stage_column.addWidget(self.place)
        self.place_hint = QLabel(''); self.place_hint.setWordWrap(True); self.place_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.place_hint.setStyleSheet('color: #92929e; font-size: 12px;'); stage_column.addWidget(self.place_hint)
        right.addLayout(stage_column, 4)

        panel = QWidget(); panel.setMinimumWidth(380); right.addWidget(panel, 6)
        form = QVBoxLayout(panel); form.setContentsMargins(0, 0, 0, 0); form.setSpacing(14)
        self.name = QLabel(); self.name.setStyleSheet('font-size: 26px; font-weight: 700;'); self.name.setWordWrap(True); form.addWidget(self.name)
        self.kind = QLabel(); self.kind.setStyleSheet('color: #98dfef; font-size: 12px; font-weight: 700; letter-spacing: 1px;'); form.addWidget(self.kind)
        self.notice = QLabel(); self.notice.setWordWrap(True); self.notice.setObjectName('portalNotice'); form.addWidget(self.notice)
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(12); form.addLayout(grid)
        def label(text):
            widget = QLabel(text); widget.setStyleSheet('color: #aaaab5; font-weight: 600;'); return widget
        self.nickname = QLineEdit(); self.nickname.setMaxLength(figure_data.NICKNAME_LENGTH); self.nickname.setPlaceholderText('No nickname')
        grid.addWidget(label('Nickname'), 0, 0); grid.addWidget(self.nickname, 0, 1, 1, 2)
        self.level = QSpinBox(); self.level.setRange(1, 20); self.level.setPrefix('Level  ')
        self.level.valueChanged.connect(self.level_changed)
        self.max_level = QPushButton('Max'); self.max_level.clicked.connect(lambda: self.level.setValue(self.level.maximum()))
        grid.addWidget(label('Level'), 1, 0); grid.addWidget(self.level, 1, 1); grid.addWidget(self.max_level, 1, 2)
        self.xp = QSpinBox(); self.xp.setRange(0, figure_data.MAX_XP); self.xp.setGroupSeparatorShown(True); self.xp.setSuffix('  XP')
        self.xp.valueChanged.connect(self.xp_changed)
        grid.addWidget(label('Experience'), 2, 0); grid.addWidget(self.xp, 2, 1, 1, 2)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setFixedHeight(6)
        grid.addWidget(self.progress, 3, 1, 1, 2)
        self.progress_text = QLabel(); self.progress_text.setStyleSheet('color: #92929e; font-size: 12px;'); grid.addWidget(self.progress_text, 4, 1, 1, 2)
        self.gold = QSpinBox(); self.gold.setRange(0, figure_data.MAX_GOLD); self.gold.setGroupSeparatorShown(True); self.gold.setSuffix('  gold')
        self.max_gold = QPushButton('Max'); self.max_gold.clicked.connect(lambda: self.gold.setValue(figure_data.MAX_GOLD))
        grid.addWidget(label('Gold'), 5, 0); grid.addWidget(self.gold, 5, 1); grid.addWidget(self.max_gold, 5, 2)
        self.played = QLabel(); self.played.setStyleSheet('color: #c8c8d0;')
        grid.addWidget(label('Time played'), 6, 0); grid.addWidget(self.played, 6, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        for field in (self.nickname,): field.textChanged.connect(self.mark)
        for field in (self.xp, self.gold): field.valueChanged.connect(self.mark)
        form.addStretch()
        self.feedback = QLabel(); self.feedback.setStyleSheet('color: #92929e; font-size: 12px;'); self.feedback.setWordWrap(True)
        form.addWidget(self.feedback)
        save_row = QHBoxLayout(); save_row.addStretch()
        self.revert = QPushButton('Revert'); self.revert.clicked.connect(lambda: self.show_entry(self.entry)); save_row.addWidget(self.revert)
        self.save_button = QPushButton('Save changes'); self.save_button.setObjectName('portalPrimary'); self.save_button.clicked.connect(self.save)
        save_row.addWidget(self.save_button); form.addLayout(save_row)
        manage = QHBoxLayout()
        self.duplicate_button = QPushButton('Duplicate'); self.duplicate_button.setToolTip('A second copy with its own progress, e.g. for player 2')
        self.duplicate_button.clicked.connect(self.duplicate)
        self.export_button = QPushButton('Export…'); self.export_button.clicked.connect(self.export)
        self.remove_button = QPushButton('Remove'); self.remove_button.setObjectName('portalDanger'); self.remove_button.clicked.connect(self.remove)
        for button in (self.duplicate_button, self.export_button): manage.addWidget(button)
        manage.addStretch(); manage.addWidget(self.remove_button); form.addLayout(manage)

        self.setStyleSheet('''
            QWidget#portalPage { background: #101012; }
            QFrame#portalPanel { background: #18181c; border: 1px solid #303037; border-radius: 20px; }
            QPushButton#portalBack { background: transparent; border: none; color: #aaaab5; padding: 4px 0; text-align: left; }
            QPushButton#portalBack:hover { color: white; }
            QPushButton#portalPrimary { background: #fafafa; color: #10121a; border: none; border-radius: 10px; padding: 10px 18px; font-weight: 700; }
            QPushButton#portalPrimary:hover { background: #dedee3; }
            QPushButton#portalPrimary:disabled { background: #3a3a40; color: #77777f; }
            QPushButton#portalDanger { background: transparent; border: 1px solid #5b3439; color: #ff9aa5; }
            QPushButton#portalDanger:hover { background: #3a1e22; border-color: #ff9aa5; }
            QLabel#portalLock { color: #f1d59a; background: #2b2416; border: 1px solid #5c4a24; border-radius: 10px; padding: 6px 12px; }
            QLabel#portalNotice { color: #cfe9f2; background: #15303b; border: 1px solid #275567; border-radius: 10px; padding: 10px 12px; }
            QListWidget#portalList { background: transparent; border: none; padding: 0; }
            QListWidget#portalList::item { padding: 8px; border-radius: 10px; margin: 1px 0; }
            QListWidget#portalList::item:selected { background: #2a3a44; color: white; }
            QListWidget#portalList::item:hover:!selected { background: #222228; }
            QSpinBox { background: #252528; border: 1px solid #343438; border-radius: 6px; padding: 8px; color: #f5f5f7; }
            QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
            QSpinBox:disabled, QLineEdit:disabled { color: #6d6d75; }
            QProgressBar { background: #2a2a30; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #98dfef; border-radius: 3px; }
        ''')

    # -- data ---------------------------------------------------------------
    def open(self):
        self.refresh(); self.owner.views.setCurrentWidget(self)

    def close_page(self):
        if self.dirty() and QMessageBox.question(self, 'Unsaved changes', 'Discard the changes to this Skylander?') != QMessageBox.StandardButton.Yes:
            return
        self.owner.refresh_game(); self.owner.views.setCurrentWidget(self.owner.canvas)

    def locked(self):
        return self.owner.process is not None

    def refresh(self, select=None):
        try:
            self.collection = self.collection or Collection(self.owner.root)
            self.entries = self.collection.entries(); problem = ''
        except (OSError, figure_data.FigureError) as error:
            self.entries = []; problem = str(error)
        current = select or (self.entry.path if self.entry else None) or self.starting()
        self.list.blockSignals(True); self.list.clear()
        for entry in self.entries:
            self.list.addItem(self.item(entry))
        self.list.blockSignals(False)
        self.list.setVisible(bool(self.entries)); self.empty.setVisible(not self.entries)
        if problem: self.empty.setText(problem)
        self.lock.setVisible(self.locked())
        for button in (self.create_button, self.import_button): button.setEnabled(not self.locked() and self.collection is not None)
        index = next((i for i, e in enumerate(self.entries) if current and e.path == Path(current)), 0 if self.entries else -1)
        self.entry = None; self.list.setCurrentRow(index)
        if index < 0: self.show_entry(None)
        self.filter(self.search.text())

    def starting(self):
        value = self.owner.library.get('portal')
        return Path(value) if value else None

    def starting_bottom(self):
        value = self.owner.library.get('portal_bottom')
        return Path(value) if value else None

    def on_portal(self, entry):
        return entry.path in (self.starting(), self.starting_bottom())

    def item(self, entry):
        figure = entry.figure
        lines = [entry.name + ('   ◉' if self.on_portal(entry) else '')]
        if figure.kind == 'item': lines.append('Magic item')
        elif figure.half: lines.append(f'Swapper {figure.half} half')
        elif figure.editable:
            detail = f'Level {figure.level}  ·  {figure.gold:,} gold'
            lines.append(detail + (f'  ·  “{figure.nickname}”' if figure.nickname else ''))
        else: lines.append('Not played yet')
        item = QListWidgetItem(QIcon(tile(self.portraits.get(figure.identity, figure.variant), 52,
                                          '#90eaff' if self.on_portal(entry) else '#4a6a7c', entry.name)), '\n'.join(lines))
        item.setToolTip(entry.path.name); return item

    def filter(self, text):
        needle = text.strip().lower()
        for i, entry in enumerate(self.entries):
            self.list.item(i).setHidden(bool(needle) and needle not in (entry.name + ' ' + entry.figure.nickname).lower())

    def select(self, row):
        if self.loading: return
        target = self.entries[row] if 0 <= row < len(self.entries) else None
        if self.entry is not None and target is not self.entry and self.dirty():
            if QMessageBox.question(self, 'Unsaved changes', 'Discard the changes to this Skylander?') != QMessageBox.StandardButton.Yes:
                self.list.blockSignals(True); self.list.setCurrentRow(self.entries.index(self.entry)); self.list.blockSignals(False); return
        self.show_entry(target)

    # -- detail -------------------------------------------------------------
    def show_entry(self, entry):
        self.loading = True; self.entry = entry
        figure = entry.figure if entry else None
        editable = bool(figure and figure.editable) and not self.locked()
        if entry:
            on_portal = self.on_portal(entry)
            self.stage.show_figure(self.portraits.get(figure.identity, figure.variant), entry.name, on_portal)
            self.name.setText(entry.name)
            kind = 'MAGIC ITEM' if figure.kind == 'item' else f'SWAPPER {figure.half.upper()} HALF' if figure.half else 'SKYLANDER'
            self.kind.setText(kind + ('  ·  CREATED' if entry.created else '  ·  IMPORTED'))
            self.place.setText('Remove from portal' if on_portal else 'Place on portal')
            self.place_hint.setText('Starts on the portal when you press Play.' if on_portal else
                                    'Choose the figure placed when the game starts. You can swap figures in game with F6.')
            self.nickname.setText(figure.nickname)
            self.level.setMaximum(figure.max_level); self.xp.setMaximum(figure.max_xp)
            self.xp.setValue(figure.xp); self.level.setValue(figure.level); self.gold.setValue(figure.gold)
            seconds = figure.seconds_played
            self.played.setText(f'{seconds // 3600} h {seconds // 60 % 60} min' if seconds else '—')
            if figure.kind == 'item': notice = 'Magic items have no level or gold to edit.'
            elif figure.half: notice = 'Swapper halves are placed together: start with a top half, then add a bottom half. Their progress is kept by the game.'
            elif not figure.editable: notice = 'Not played yet. Place it on the portal in game once, then its level, gold and nickname can be edited here.'
            else: notice = ''
        else:
            self.stage.show_figure(QPixmap(), '', False); self.name.setText('No Skylander selected'); self.kind.setText('')
            notice = ''; self.nickname.clear(); self.xp.setValue(0); self.level.setValue(1); self.gold.setValue(0); self.played.setText('—')
        self.notice.setText(notice); self.notice.setVisible(bool(notice))
        for widget in (self.nickname, self.level, self.max_level, self.xp, self.gold, self.max_gold): widget.setEnabled(editable)
        has = entry is not None and not self.locked()
        for widget in (self.duplicate_button, self.export_button, self.remove_button, self.place): widget.setEnabled(has)
        self.duplicate_button.setEnabled(has and figure.kind == 'character')
        self.export_button.setEnabled(entry is not None)
        self.update_progress(); self.loading = False; self.mark()
        if entry: self.feedback.setText('Saved to the game’s working copy.' if entry.working else 'Never placed in game yet.')
        else: self.feedback.clear()

    def level_changed(self, level):
        if self.loading: return
        if figure_data.level_for(self.xp.value()) != level:
            self.loading = True; self.xp.setValue(figure_data.xp_for(level)); self.loading = False
        self.update_progress(); self.mark()

    def xp_changed(self, xp):
        if self.loading: return
        self.loading = True; self.level.setValue(figure_data.level_for(xp)); self.loading = False
        self.update_progress()

    def update_progress(self):
        xp = self.xp.value(); level = figure_data.level_for(xp)
        if level >= self.level.maximum():
            self.progress.setRange(0, 1); self.progress.setValue(1); self.progress_text.setText('Maximum level')
            return
        start, end = figure_data.LEVEL_XP[level - 1], figure_data.LEVEL_XP[level]
        self.progress.setRange(0, end - start); self.progress.setValue(xp - start)
        self.progress_text.setText(f'{end - xp:,} XP to level {level + 1}')

    def values(self):
        return (self.nickname.text(), self.xp.value(), self.gold.value())

    def dirty(self):
        figure = self.entry.figure if self.entry else None
        return bool(figure and figure.editable) and self.values() != (figure.nickname, figure.xp, figure.gold)

    def mark(self, *_):
        if self.loading: return
        dirty = self.dirty()
        self.save_button.setEnabled(dirty and not self.locked()); self.revert.setEnabled(dirty)
        if dirty: self.feedback.setText('Unsaved changes')

    # -- actions ------------------------------------------------------------
    def guard(self):
        if self.locked():
            QMessageBox.information(self, 'Game running', 'Stop the game before changing your Skylanders. The game is writing to them.')
            self.refresh(); return False
        return True

    def failure(self, title, error):
        QMessageBox.warning(self, title, str(error))

    def save(self):
        if not self.entry or not self.guard(): return
        figure = figure_data.Figure(self.entry.figure.raw, self.collection.seed)
        nickname, xp, gold = self.values()
        try:
            if nickname != figure.nickname: figure.nickname = nickname
            if xp != figure.xp: figure.xp = xp
            if gold != figure.gold: figure.gold = gold
            saved = self.collection.save(self.entry, figure.to_bytes())
        except (OSError, figure_data.FigureError) as error:
            self.failure('Could not save this Skylander', error); return
        if self.starting() == self.entry.path and saved.path != self.entry.path: self.set_starting(saved.path, self.starting_bottom())
        if self.starting_bottom() == self.entry.path and saved.path != self.entry.path: self.set_starting(self.starting(), saved.path)
        self.entry = None; self.refresh(saved.path); self.feedback.setText('Saved. The previous state was backed up to out/figure-backups.')

    def create(self):
        if not self.guard(): return
        dialog = CreateDialog(self, self.collection, self.portraits)
        if not dialog.exec() or dialog.choice is None: return
        try:
            entry = self.collection.create(*dialog.choice)
        except (OSError, figure_data.FigureError) as error:
            self.failure('Could not create this Skylander', error); return
        self.refresh(entry.path); self.feedback.setText(f'{entry.name} created.')

    def import_dump(self):
        if not self.guard(): return
        path, _ = QFileDialog.getOpenFileName(self, 'Import a figure dump', '', 'Figure dumps (*.sky *.bin *.dump);;All files (*)')
        if not path: return
        try:
            entry = self.collection.import_dump(path)
        except (OSError, figure_data.FigureError) as error:
            self.failure('Could not import this figure', error); return
        self.refresh(entry.path); self.feedback.setText(f'{entry.name} imported.')

    def duplicate(self):
        if not self.entry or not self.guard(): return
        try:
            entry = self.collection.duplicate(self.entry)
        except (OSError, figure_data.FigureError) as error:
            self.failure('Could not duplicate this Skylander', error); return
        self.refresh(entry.path); self.feedback.setText('Copy created with the same progress.')

    def export(self):
        if not self.entry: return
        name = (self.entry.figure.nickname or self.entry.name).replace('/', '-')
        path, _ = QFileDialog.getSaveFileName(self, 'Export figure', name + '.sky', 'Figure dumps (*.sky)')
        if not path: return
        try:
            self.collection.export(self.entry, path)
        except OSError as error:
            self.failure('Could not export this figure', error); return
        self.feedback.setText('Exported to ' + path)

    def remove(self):
        if not self.entry or not self.guard(): return
        name = self.entry.figure.nickname or self.entry.name
        if QMessageBox.question(self, 'Remove Skylander', f'Remove {name} from your collection?\n\n'
                'The figure and its progress are moved to out/portal-library/removed and can be restored from there.') != QMessageBox.StandardButton.Yes:
            return
        if self.starting() == self.entry.path: self.set_starting(None)
        elif self.starting_bottom() == self.entry.path: self.set_starting(self.starting())
        try:
            self.collection.remove(self.entry)
        except OSError as error:
            self.failure('Could not remove this Skylander', error); return
        self.entry = None; self.refresh()

    def toggle_portal(self):
        if not self.entry or not self.guard(): return
        path, half = self.entry.path, self.entry.figure.half
        top = self.starting(); top_entry = next((e for e in self.entries if e.path == top), None)
        if path == self.starting_bottom(): self.set_starting(top, None)
        elif path == top: self.set_starting(None)
        elif half == 'bottom':
            # A bottom half only starts under a top half, like the real portal pairing.
            if not (top_entry and top_entry.figure.half == 'top'):
                QMessageBox.information(self, 'Place a top half first', 'Choose a swapper top half as the starting figure, then add this bottom half under it.'); return
            self.set_starting(top, path)
        else: self.set_starting(path, self.starting_bottom() if half == 'top' else None)
        self.refresh(self.entry.path)

    def set_starting(self, path, bottom=None):
        owner = self.owner; value = str(path) if path else None; under = str(bottom) if bottom and path else None
        owner.library['portal'] = value; owner.fields['figure'].setText(value or '')
        owner.library['portal_bottom'] = under; owner.fields['figure_bottom'].setText(under or '')
        for game in owner.library['games']:
            if 'figure' in game['settings']: game['settings']['figure'] = value or ''
            if 'figure' in game['settings'] or 'figure_bottom' in game['settings']: game['settings']['figure_bottom'] = under or ''
        owner.persist()
