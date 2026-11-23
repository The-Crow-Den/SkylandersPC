# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time card before the first launch: how to open the in-game PC menu.

Only the controller shortcut is shown (both sticks pressed in together); the
menu's keyboard keys still work but have no icons here. Whether the card was
seen is kept per user in .local/launcher-tips.json, outside the repository.
"""
import json
from pathlib import Path

TIP = 'pc-menu'


def path(root):
    return Path(root)/'.local/launcher-tips.json'


def seen(root, tip=TIP):
    try:
        file = path(root)
        if file.is_symlink() or file.stat().st_size > 4096:return False
        value = json.loads(file.read_text())
        return isinstance(value, dict) and value.get(tip) is True
    except (OSError, ValueError):
        return False


def mark(root, tip=TIP):
    file = path(root)
    try:
        value = json.loads(file.read_text()) if file.is_file() and not file.is_symlink() else {}
        if not isinstance(value, dict):value = {}
    except (OSError, ValueError):
        value = {}
    value[tip] = True
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        temporary = file.with_name(file.name+'.tmp');temporary.write_text(json.dumps(value)+'\n');temporary.replace(file)
    except OSError:
        pass  # worst case the card shows again next time


try:
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
    from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
except ImportError:  # source checks run without Qt
    QDialog = object
    QWidget = object


BUTTON = QColor(14, 20, 27) if QWidget is not object else None
ACCENT = QColor(152, 223, 239) if QWidget is not object else None


class SticksArt(QWidget):
    """Two thumbsticks being pressed in, drawn in the launcher's own style."""
    def __init__(self, parent=None):
        super().__init__(parent);self.setFixedSize(360, 150)

    def stick(self, painter, centre, letter):
        x, y = centre.x(), centre.y()
        # Press arrow above the stick.
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(ACCENT)
        painter.drawRect(QRectF(x-5, y-74, 10, 16))
        painter.drawPolygon(QPolygonF([QPointF(x-15, y-58), QPointF(x+15, y-58), QPointF(x, y-42)]))
        # Base ring, cap and letter.
        painter.setBrush(QColor(42, 48, 58));painter.drawEllipse(centre, 46, 46)
        painter.setBrush(BUTTON);painter.setPen(QPen(ACCENT, 3));painter.drawEllipse(centre, 36, 36)
        painter.setPen(QColor(255, 255, 255));font = QFont();font.setPixelSize(30);font.setWeight(QFont.Weight.Black);painter.setFont(font)
        painter.drawText(QRectF(x-36, y-36, 72, 72), Qt.AlignmentFlag.AlignCenter, letter)

    def paintEvent(self, event):
        painter = QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        middle = self.height()/2+22
        self.stick(painter, QPointF(90, middle), 'L')
        self.stick(painter, QPointF(self.width()-90, middle), 'R')
        painter.setPen(QColor(200, 200, 210));font = QFont();font.setPixelSize(34);font.setWeight(QFont.Weight.Bold);painter.setFont(font)
        painter.drawText(QRectF(self.width()/2-30, middle-30, 60, 60), Qt.AlignmentFlag.AlignCenter, '+')


class MenuTipDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle('The PC menu');self.setModal(True);self.setObjectName('menuTip')
        self.setStyleSheet('''
            QDialog#menuTip { background: #171719; }
            QLabel#tipKicker { color: #98dfef; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
            QLabel#tipTitle { color: #ffffff; font-size: 24px; font-weight: 800; }
            QLabel#tipBody { color: #c3c3cc; font-size: 14px; }
            QPushButton#tipDone { background: #fafafa; color: #10121a; border: none; border-radius: 12px; padding: 12px 28px; font-size: 15px; font-weight: 800; }
            QPushButton#tipDone:hover { background: #e4f7fb; }
        ''')
        layout = QVBoxLayout(self);layout.setContentsMargins(40, 36, 40, 32);layout.setSpacing(14)
        kicker = QLabel('BEFORE YOU PLAY');kicker.setObjectName('tipKicker');kicker.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(kicker)
        title = QLabel('Open the PC menu any time');title.setObjectName('tipTitle');title.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(title)
        art = QHBoxLayout();art.addStretch();art.addWidget(SticksArt(self));art.addStretch();layout.addLayout(art)
        body = QLabel('Press <b>both sticks in</b> at the same time.<br>The menu has the virtual portal, your settings and more.<br>Do the same again to close it.')
        body.setObjectName('tipBody');body.setAlignment(Qt.AlignmentFlag.AlignCenter);body.setWordWrap(True);layout.addWidget(body)
        row = QHBoxLayout();row.addStretch()
        done = QPushButton('Got it');done.setObjectName('tipDone');done.setDefault(True);done.clicked.connect(self.accept);row.addWidget(done)
        row.addStretch();layout.addSpacing(8);layout.addLayout(row)
        self.setFixedWidth(520)
