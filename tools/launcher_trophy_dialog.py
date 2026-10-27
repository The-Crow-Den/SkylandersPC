# SPDX-License-Identifier: GPL-3.0-or-later
"""Local trophy browser. Catalogue and user progress remain separate sources."""
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon,QPixmap
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QComboBox,QListWidget,QListWidgetItem,QFileDialog,QMessageBox)
try:
    from . import launcher_trophies as trophies
except ImportError:
    import launcher_trophies as trophies


class TrophyDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.game=owner.game
        self.setWindowTitle(self.game['name']+' · Trophies');self.resize(850,700)
        column=QVBoxLayout(self);column.setContentsMargins(24,24,24,24);column.setSpacing(16)
        self.summary=QLabel();self.summary.setStyleSheet('font-size: 24px; font-weight: 600;');column.addWidget(self.summary)
        controls=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search trophies…');controls.addWidget(self.search,1)
        self.filter=QComboBox();self.filter.addItems(['All trophies','Unlocked','Locked','Unknown']);controls.addWidget(self.filter);column.addLayout(controls)
        self.list=QListWidget();self.list.setWordWrap(True);self.list.setIconSize(QSize(48,48));column.addWidget(self.list,1)
        self.notice=QLabel();self.notice.setWordWrap(True);self.notice.setStyleSheet('color: #a9a9b1;');column.addWidget(self.notice)
        actions=QHBoxLayout();column.addLayout(actions)
        for text,callback in [('Link trophy catalogue',lambda:self.link('trophy_definitions')),('Link user trophy record',lambda:self.link('trophy_progress')),('Refresh',self.refresh),('Close',self.accept)]:
            button=QPushButton(text);button.clicked.connect(callback);actions.addWidget(button)
        self.search.textChanged.connect(self.populate);self.filter.currentIndexChanged.connect(self.populate)
        self.refresh()

    def refresh(self):
        try:self.data=trophies.snapshot(self.owner.root,self.game)
        except (OSError,ValueError,UnicodeError) as error:
            self.data=dict(rows=[],earned=0,total=0,percent=None,message=str(error),icons={})
        data=self.data;percent=f"{data['percent']}%" if data['percent'] is not None else '—%'
        counts=f"{data['earned']} / {data['total']} unlocked" if data['percent'] is not None else f"{data['total']} trophies · Unlock status unknown"
        self.summary.setText(f'{percent}  ·  {counts}');self.notice.setText(data['message']);self.populate();self.owner.refresh_game()

    def populate(self):
        self.list.clear();query=self.search.text().casefold();filter=self.filter.currentIndex()
        for row in self.data['rows']:
            unlocked=row['unlocked'];status='Unlocked' if unlocked is True else ('Locked' if unlocked is False else 'Unknown')
            if filter and status!=['','Unlocked','Locked','Unknown'][filter]:continue
            if query and query not in (row['name']+' '+row['detail']).casefold():continue
            grade={'B':'Bronze','S':'Silver','G':'Gold','P':'Platinum'}.get(row['grade'],'')
            item=QListWidgetItem(row['name']+'  ·  '+status+('  ·  '+grade if grade else '')+'\n'+row['detail'])
            icon=QPixmap()
            try:icon.loadFromData(trophies.icon_bytes(self.data,row['id']))
            except OSError:pass
            if not icon.isNull():item.setIcon(QIcon(icon))
            item.setSizeHint(QSize(0,80));self.list.addItem(item)

    def link(self,key):
        path,_=QFileDialog.getOpenFileName(self,'Choose trophy XML (not a normal game save)','','Trophy XML (*.xml *.XML)')
        if not path:return
        old=self.game.get(key);self.game[key]=path
        try:trophies.snapshot(self.owner.root,self.game)
        except (OSError,ValueError,UnicodeError) as error:
            if old is None:self.game.pop(key,None)
            else:self.game[key]=old
            QMessageBox.warning(self,'Cannot read trophy data',str(error));return
        self.owner.persist();self.refresh()
