# SPDX-License-Identifier: GPL-3.0-or-later
"""Skylands-inspired Qt presentation. Artwork stays in the user's local dump/cache."""
from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout


STYLE = '''
QMainWindow, QWidget#canvas { background: #101012; color: #f5f5f7; }
QWidget { color: #f5f5f7; font-family: "Cantarell", "DejaVu Sans", sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #a9a9b1; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#pageTitle { font-size: 29px; font-weight: 800; }
QLabel#muted { color: #a9a9b1; }
QWidget#sidebar { background: #171719; border-right: 1px solid #343438; }
QWidget#footer { background: #171719; border-top: 1px solid #343438; }
QWidget#sheet { background: #222225; border: 1px solid #343438; border-radius: 12px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QPushButton { background: #303034; border: 1px solid #45454c; border-radius: 7px; padding: 10px 16px; font-weight: 600; }
QPushButton:hover { background: #3b3b40; border-color: #98dfef; }
QPushButton:pressed { background: #222225; }
QPushButton:focus { border: 2px solid #90e8ff; }
QPushButton:disabled { color: #6d8498; background: #142536; border-color: #22394b; }
QPushButton#nav { text-align: left; border: none; background: transparent; color: #a9a9b1; padding: 14px 16px; }
QPushButton#nav:hover { color: white; background: #303034; }
QPushButton#nav:checked { color: #a1efff; background: #353539; border-left: 3px solid #78e2f4; border-radius: 0px; }
QPushButton#play { background: #f5f5f7; color: #171719; border: none; border-radius: 12px; font-size: 16px; font-weight: 700; padding: 16px 30px; }
QPushButton#play:hover { background: #dedee3; }
QPushButton#play:disabled { background: #41515d; color: #8b9ca9; border-color: #5a6b77; }
QPushButton#feature { text-align: left; background: #222225; border: 1px solid #2c4b63; padding: 16px; border-radius: 11px; }
QPushButton#feature:hover { background: #173c55; border-color: #98dfef; }
QLineEdit, QComboBox, QTextEdit { background: #252528; border: 1px solid #343438; border-radius: 6px; padding: 9px; selection-background-color: #237b99; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #89e6fa; }
QComboBox { min-height: 22px; }
QComboBox QAbstractItemView { background: #222225; color: white; selection-background-color: #353539; }
QCheckBox { spacing: 11px; padding: 5px 0; }
QCheckBox::indicator { width: 20px; height: 20px; border: 1px solid #53798f; background: #0b1e30; border-radius: 5px; }
QCheckBox::indicator:checked { background: #54cce5; border: 4px solid #1b536c; }
QCheckBox::indicator:focus { border-color: #ffe3a1; }
QSlider::groove:horizontal { height: 5px; background: #294357; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #5acde6; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #d5f8ff; border: 2px solid #4da7bf; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #385b73; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
'''


def text_label(text, name=None):
    label = QLabel(text)
    if name: label.setObjectName(name)
    label.setWordWrap(True)
    return label


def crystal_icon(color='#8ce5ff', size=32):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size/32, size/32)
    path = QPainterPath(); path.moveTo(16, 2); path.lineTo(25, 10)
    path.lineTo(21, 25); path.lineTo(16, 31); path.lineTo(11, 25)
    path.lineTo(7, 10); path.closeSubpath()
    gradient = QLinearGradient(6, 4, 25, 28)
    gradient.setColorAt(0, QColor('#dbfaff')); gradient.setColorAt(.45, QColor(color)); gradient.setColorAt(1, QColor('#1c638d'))
    painter.fillPath(path, gradient); painter.setPen(QPen(QColor('#d5faff'), .9)); painter.drawPath(path)
    painter.drawLine(16, 2, 12, 11); painter.drawLine(12, 11, 16, 31)
    painter.drawLine(12, 11, 25, 10); painter.end()
    return QIcon(pixmap)


class Hero(QWidget):
    def __init__(self, root):
        super().__init__()
        self.setMinimumHeight(330)
        try:
            try:
                from .game_library import resolve
            except ImportError:
                from game_library import resolve
            artwork = resolve(root).source('sce_sys/pic1.png')
        except (OSError,ValueError):
            artwork = root/'.local/unavailable-artwork.png'
        self.art = QPixmap(str(artwork))
        row = QHBoxLayout(self); row.setContentsMargins(30, 32, 20, 26)
        left = QVBoxLayout(); left.setSpacing(13)
        left.addWidget(text_label('THE PORTAL IS YOURS', 'eyebrow'))
        title = text_label('Return to\nSkylands.')
        title.setStyleSheet('font-family: "Cantarell"; font-size: 39px; font-weight: 900; color: #fff8e8;')
        left.addWidget(title)
        body = text_label('Your Skylanders. Your adventure.\nReady for another round of trouble?')
        body.setStyleSheet('color: #c3d9e8; font-size: 13px; line-height: 1.5;')
        left.addWidget(body)
        left.addStretch()
        tag = text_label('TRAPTANIUM POWERED  /  PC')
        tag.setStyleSheet('font-size: 9px; letter-spacing: 1px; color: #96daeb; font-weight: 700;')
        left.addWidget(tag)
        row.addLayout(left, 44); row.addStretch(56)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath(); clip.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),14,14)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor('#163d62'))
        if not self.art.isNull():
            # Use the actual game branding at its original aspect ratio. The
            # left edge dissolves into the copy area; no game image is rewritten.
            width = int(self.width()*.73)
            height = int(width*self.art.height()/self.art.width())
            p.drawPixmap(self.width()-width, (self.height()-height)//2, width, height, self.art)
        veil = QLinearGradient(0,0,self.width(),0)
        for stop, color in ((0,'#222225'),(.29,'#222225'),(.47,'#e010283e'),(.65,'#0010283e')):
            veil.setColorAt(stop,QColor(color))
        p.fillRect(self.rect(),veil)
        p.setPen(QPen(QColor('#5287a1'),1)); p.drawPath(clip)


class PortraitStrip(QWidget):
    def __init__(self, root):
        super().__init__()
        self.setMinimumHeight(106)
        self.portraits = [(QPixmap(str(root/f'.local/portal-assets/{i:02}.image')), name)
                         for i,name in ((8,'Golden Queen'),(6,'Kaos'),(33,'Wolfgang'))]

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width=(self.width()-20)/3
        for i,(art,name) in enumerate(self.portraits):
            x=i*(width+10);rect=QRectF(x,0,width,self.height()-1)
            clip=QPainterPath();clip.addRoundedRect(rect,9,9)
            p.save();p.setClipPath(clip);p.fillRect(rect,QColor('#19324e'))
            if not art.isNull():
                p.drawPixmap(rect.toRect(),art,art.rect())
            overlay=QLinearGradient(0,0,0,self.height());overlay.setColorAt(0,QColor('#00091929'));overlay.setColorAt(.45,QColor('#30091929'));overlay.setColorAt(1,QColor('#f4091929'))
            p.fillRect(rect,overlay);p.restore()
            p.setPen(QPen(QColor('#41617c'),1));p.drawPath(clip)
            p.setPen(QColor('#f4e0b5'));p.setFont(QFont('Cantarell',9,QFont.Weight.Bold))
            p.drawText(rect.adjusted(9,0,-5,-9),Qt.AlignmentFlag.AlignBottom|Qt.AlignmentFlag.AlignLeft,name)


def feature_card(title, subtitle, color, callback):
    button = QPushButton(f'{title}  ›\n{subtitle.replace("&", "&&")}')
    button.setObjectName('feature')
    button.setMinimumHeight(86);button.clicked.connect(callback)
    return button
