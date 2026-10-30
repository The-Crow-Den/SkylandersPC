# SPDX-License-Identifier: GPL-3.0-or-later
"""File and folder choosers that work with a controller as well as a mouse.

When the controller was the last input (or in Steam Game Mode) the launcher shows its own
list-based picker with Downloads, Home and removable-storage shortcuts plus a scan for
matching files; otherwise the normal desktop dialog is used."""
import os
from pathlib import Path


def places(home=None, environ=os.environ):
    """[(label, path)] shortcuts that exist: Downloads, Home, then mounted SD cards/USB drives."""
    home = Path(home or Path.home()); found = []
    for label, path in [('Downloads', home / 'Downloads'), ('Home', home)]:
        if path.is_dir(): found.append((label, path))
    user = environ.get('USER') or home.name
    for base in (Path('/run/media') / user, Path('/run/media'), Path('/media') / user):
        try: entries = sorted(base.iterdir()) if base.is_dir() else []
        except OSError: continue
        for entry in entries:
            if entry.is_dir() and entry.name != user and os.path.ismount(entry) and all(entry != p for _, p in found):
                found.append((entry.name, entry))
    return found


def listing(folder, suffixes=(), folders_only=False, hidden=False):
    """(folders, files) in a folder, sorted case-insensitively; files filtered by suffix."""
    folders, files = [], []
    try: entries = list(Path(folder).iterdir())
    except OSError: return [], []
    for entry in entries:
        if entry.name.startswith('.') and not hidden: continue
        try:
            if entry.is_dir(): folders.append(entry)
            elif not folders_only and entry.is_file() and (not suffixes or entry.suffix.lower() in suffixes): files.append(entry)
        except OSError: continue
    key = lambda p: p.name.lower()
    return sorted(folders, key=key), sorted(files, key=key)


def scan(roots, suffixes, depth=4, limit=200):
    """Matching files below roots, breadth first and without following symlinks."""
    found, seen = [], set()
    queue = [(Path(root), 0) for root in roots]
    while queue and len(found) < limit:
        folder, level = queue.pop(0)
        try: real = folder.resolve()
        except OSError: continue
        if real in seen: continue
        seen.add(real)
        folders, files = listing(folder, suffixes)
        found.extend(f for f in files if f not in found)
        if level < depth: queue.extend((f, level + 1) for f in folders if not f.is_symlink())
    return found[:limit]


def size_text(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB': return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
        QPushButton, QVBoxLayout)
except ImportError:
    QDialog = None


def controller_mode(widget):
    try:
        from .launcher_gamepad import game_mode
    except ImportError:
        from launcher_gamepad import game_mode
    navigator, window = None, widget
    while window is not None and navigator is None:
        window = window.window(); navigator = getattr(window, 'gamepad', None); window = window.parentWidget()
    return game_mode() or bool(navigator and navigator.active)


def choose_file(parent, title, suffixes, start=''):
    """A path string, or '' when cancelled. suffixes like ('.pkg',)."""
    if not controller_mode(parent):
        pattern = ' '.join('*' + s for s in suffixes)
        path, _ = QFileDialog.getOpenFileName(parent, title, start, f'{title} ({pattern});;All files (*)')
        return path
    picker = Picker(parent, title, suffixes, start)
    return picker.chosen if picker.exec() else ''


def choose_folder(parent, title, start=''):
    if not controller_mode(parent):
        return QFileDialog.getExistingDirectory(parent, title, start)
    picker = Picker(parent, title, (), start, folders_only=True)
    return picker.chosen if picker.exec() else ''


if QDialog is not None:
    class Picker(QDialog):
        def __init__(self, parent, title, suffixes, start='', folders_only=False):
            super().__init__(parent); self.setWindowTitle(title)
            self.suffixes = tuple(s.lower() for s in suffixes); self.folders_only = folders_only; self.chosen = ''
            self.resize(1000, 620)
            column = QVBoxLayout(self); column.setContentsMargins(24, 22, 24, 20); column.setSpacing(12)
            heading = QLabel(title); heading.setStyleSheet('font-size: 20px; font-weight: 600;'); column.addWidget(heading)
            row = QHBoxLayout(); row.setSpacing(8); column.addLayout(row)
            if not folders_only:
                find = QPushButton('Find ' + '/'.join(s.lstrip('.').upper() for s in self.suffixes) + ' files')
                find.clicked.connect(self.find); row.addWidget(find)
            for label, path in places():
                button = QPushButton(label); button.clicked.connect(lambda c=False, p=path: self.show_folder(p)); row.addWidget(button)
            row.addStretch()
            self.location = QLabel(); self.location.setStyleSheet('color: #a9a9b1;'); self.location.setWordWrap(True); column.addWidget(self.location)
            self.list = QListWidget(); self.list.itemActivated.connect(self.open_item); column.addWidget(self.list, 1)
            footer = QHBoxLayout(); column.addLayout(footer)
            self.hint = QLabel('A open · B cancel · LB/RB switch place'); self.hint.setStyleSheet('color: #92929e;'); footer.addWidget(self.hint, 1)
            cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject); footer.addWidget(cancel)
            if folders_only:
                use = QPushButton('Use this folder'); use.setObjectName('libraryPlay'); use.setMinimumHeight(44)
                use.clicked.connect(self.use_folder); footer.addWidget(use)
            self.places = [p for _, p in places()]; self.folder = None
            # Scanning all of Home is slow; Downloads and removable drives are where PKGs land.
            self.scan_roots = [p for label, p in places() if label != 'Home'] or [Path.home()]
            start = Path(start) if start else None
            if start and start.is_file(): start = start.parent
            if start and start.is_dir(): self.show_folder(start)
            elif not folders_only and self.places: self.find()
            else: self.show_folder(self.places[0] if self.places else Path.home())
            self.list.setFocus()

        def add(self, text, path, kind):
            item = QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, (str(path), kind)); self.list.addItem(item)

        def show_folder(self, folder):
            self.folder = Path(folder); self.list.clear(); self.location.setText(str(self.folder))
            if self.folder.parent != self.folder: self.add('‹  Up one folder', self.folder.parent, 'folder')
            folders, files = listing(self.folder, self.suffixes, self.folders_only)
            for path in folders: self.add('📁  ' + path.name, path, 'folder')
            for path in files:
                try: size = size_text(path.stat().st_size)
                except OSError: size = ''
                self.add(f'{path.name}    {size}', path, 'file')
            if not folders and not files: self.location.setText(str(self.folder) + '  ·  nothing to choose here')
            self.list.setCurrentRow(0)

        def find(self):
            self.folder = None; self.list.clear()
            roots = self.scan_roots
            found = scan(roots, self.suffixes)
            self.location.setText(f'{len(found)} matching files in ' + ', '.join(str(r) for r in roots))
            for path in found:
                try: size = size_text(path.stat().st_size)
                except OSError: size = ''
                self.add(f'{path.name}    {size}    {path.parent}', path, 'file')
            self.list.setCurrentRow(0)

        def open_item(self, item):
            path, kind = item.data(Qt.ItemDataRole.UserRole)
            if kind == 'folder': self.show_folder(path)
            else: self.chosen = path; self.accept()

        def use_folder(self):
            if self.folder is not None: self.chosen = str(self.folder); self.accept()

        def gamepad_page(self, delta):
            # The cycle is: matching-file scan (file mode only), then each place.
            stops = ([] if self.folders_only else [None]) + self.places
            if not stops: return True
            current = stops.index(self.folder) if self.folder in stops else (0 if self.folder is None else -1)
            target = stops[(current + delta) % len(stops)]
            self.find() if target is None else self.show_folder(target); return True
