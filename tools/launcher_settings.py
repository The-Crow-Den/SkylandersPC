# SPDX-License-Identifier: GPL-3.0-or-later
"""Dedicated settings view for the portal library, with explicit Save/Cancel."""
from pathlib import Path
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QStackedWidget,QScrollArea,QFormLayout,QComboBox,QCheckBox,QSlider,QLineEdit,
    QTextEdit,QFileDialog,QMessageBox,QProgressDialog)
try:
    from . import launcher_model as model
except ImportError:
    import launcher_model as model

GROUPS = [
 ('Display','Picture and window preferences.', [('resolution','Resolution'),('quality','Shadow quality'),('fullscreen','Fullscreen'),('motion_blur','Motion blur')]),
 ('Performance','Frame pacing and optional overlays.', [('frame_policy','Frame policy'),('frame_limit','Frame limit'),('fps_counter','Show FPS counter'),('nvidia','Use NVIDIA GPU'),('mangohud','MangoHud overlay'),('level_events','Record level events (diagnostic)')]),
 ('Portal & audio','Starting figure and portal speaker preferences.', [('figure','Starting figure'),('portal_volume','Portal speaker volume')]),
 ('Tweaks','Optional game behavior changes and diagnostic tools.', [('unlock_nightmare','Nightmare available by default')]),
]


class SettingCombo(QComboBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#b4b4c0' if self.isEnabled() else '#686872'))
        x,y=self.width()-19,self.height()//2
        painter.drawLine(x-4,y-2,x,y+2);painter.drawLine(x,y+2,x+4,y-2)
        painter.end()


class SettingSwitch(QCheckBox):
    def sizeHint(self):
        return QSize(44,26)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():painter.setOpacity(.35)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#98dfef' if self.isChecked() else '#45454d'))
        painter.drawRoundedRect(QRectF(0,2,44,24),12,12)
        painter.setBrush(QColor('#14252b' if self.isChecked() else '#e1e1e8'))
        painter.drawEllipse(QRectF(23 if self.isChecked() else 3,5,18,18))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QColor('#f5f5f7'))
            painter.drawRoundedRect(QRectF(1,1,42,24),12,12)
        painter.end()

    def hitButton(self,pos):
        return self.rect().contains(pos)


class SettingsPage(QWidget):
    def __init__(self, owner):
        super().__init__();self.owner=owner;self.fields={};self.nav=[];self.mod_fields={};self.mod_rows=[];self.game=None;self.baseline={}
        self.setObjectName('settingsPage')
        outer=QHBoxLayout(self);outer.setContentsMargins(36,28,36,24);outer.addStretch()
        content=QWidget();content.setMaximumWidth(1040);outer.addWidget(content,1);outer.addStretch()
        layout=QVBoxLayout(content);layout.setContentsMargins(0,0,0,0);layout.setSpacing(22)
        header=QHBoxLayout();back=QPushButton('‹  Library');back.setObjectName('settingsBack');back.clicked.connect(self.cancel);header.addWidget(back);header.addStretch();self.scope=SettingCombo();self.scope.setMinimumWidth(240);self.scope.currentIndexChanged.connect(self.change_scope);header.addWidget(self.scope);layout.addLayout(header)
        self.title=title=QLabel('General settings');title.setStyleSheet('font-size: 30px; font-weight: 600;');layout.addWidget(title)
        self.notice=QLabel('Your defaults for every adventure.');self.notice.setStyleSheet('color: #92929e; font-size: 14px;');layout.addWidget(self.notice)
        self.games_row=QWidget();self.games_row.setObjectName('settingRow')
        folder_line=QHBoxLayout(self.games_row);folder_line.setContentsMargins(20,16,20,16)
        folder_copy=QVBoxLayout();folder_title=QLabel('Games folder');folder_title.setStyleSheet('font-size: 14px; font-weight: 600;');folder_copy.addWidget(folder_title)
        self.games_path=QLabel();self.games_path.setWordWrap(True);self.games_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.games_path.setStyleSheet('color: #93939e; font-size: 12px;');folder_copy.addWidget(self.games_path);folder_line.addLayout(folder_copy,1)
        self.change_games=QPushButton('Change…');self.change_games.clicked.connect(self.change_games_folder);folder_line.addWidget(self.change_games)
        self.open_games=QPushButton('Open');self.open_games.clicked.connect(self.open_games_folder);folder_line.addWidget(self.open_games)
        layout.addWidget(self.games_row)
        navigation=QHBoxLayout();navigation.setSpacing(6);layout.addLayout(navigation)
        self.pages=QStackedWidget();layout.addWidget(self.pages,1)
        hints={
            'resolution':'Internal rendering resolution.', 'quality':'Detail and definition of game shadows.',
            'fullscreen':'Use the full display when starting a game.', 'motion_blur':'Smooth motion during camera movement.',
            'frame_policy':'Automatic adapts to gameplay and menus.', 'frame_limit':'Available when using a manual frame policy.',
            'fps_counter':'Show frame rate during play.', 'nvidia':'Prefer the NVIDIA Vulkan driver.',
            'mangohud':'Requires MangoHud to be installed separately.', 'figure':'Choose the figure placed at the start of a session.',
            'portal_volume':'Volume of voices from the portal speaker.', 'unlock_nightmare':'Make Nightmare available when creating a save.',
            'level_events':'Record events for troubleshooting.'}
        for name,description,entries in GROUPS:
            page=QWidget();column=QVBoxLayout(page);column.setContentsMargins(0,4,0,0);column.setSpacing(14)
            caption=QLabel(description);caption.setStyleSheet('color: #92929e; font-size: 13px;');column.addWidget(caption)
            scroll=QScrollArea();scroll.setWidgetResizable(True);sheet=QWidget();rows=QVBoxLayout(sheet);rows.setContentsMargins(0,0,4,0);rows.setSpacing(8)
            for key,label in entries:
                original=owner.fields[key]
                if isinstance(original,QComboBox):
                    field=SettingCombo()
                    for i in range(original.count()):field.addItem(original.itemText(i),original.itemData(i))
                    field.setFixedWidth(340);field.setMinimumHeight(40)
                elif isinstance(original,QCheckBox):
                    field=SettingSwitch();field.setFixedSize(44,28)
                elif isinstance(original,QSlider):
                    field=QSlider(Qt.Orientation.Horizontal);field.setRange(original.minimum(),original.maximum())
                else:field=QLineEdit()
                self.fields[key]=field;field.setAccessibleName(label)
                row=QWidget();row.setObjectName('settingRow');line=QHBoxLayout(row);line.setContentsMargins(20,16,20,16);line.setSpacing(24)
                copy=QVBoxLayout();copy.setSpacing(4);heading=QLabel(label);heading.setStyleSheet('font-size: 14px; font-weight: 600;');copy.addWidget(heading)
                hint=QLabel(hints[key]);hint.setWordWrap(True);hint.setStyleSheet('font-size: 12px; color: #93939e;');copy.addWidget(hint);line.addLayout(copy,1)
                if key in ('figure','portal_volume'):
                    controls=QWidget();controls.setFixedWidth(340);group=QHBoxLayout(controls);group.setContentsMargins(0,0,0,0);group.addWidget(field,1)
                    if key=='figure':
                        browse=QPushButton('Browse');browse.clicked.connect(self.browse);group.addWidget(browse)
                    else:
                        value=QLabel();value.setFixedWidth(38);field.valueChanged.connect(lambda n,value=value:value.setText(f'{n}%'));group.addWidget(value)
                    line.addWidget(controls)
                else:line.addWidget(field)
                rows.addWidget(row)
            if name=='Tweaks':
                for key,label,hint in [
                    ('any-portal','Any portal','Physical portal compatibility is not implemented. The virtual portal is available.'),
                    ('element-gates','No Trap Master required for gates','Open elemental gates with a matching-element Skylander. Experimental · US 01.01.'),
                    ('traptanium','No Trap Master required for Traptanium','Break Traptanium with any Skylander. Experimental · US 01.01.'),
                    ('unlock-expansions','Unlock adventure packs','Access all four adventure packs without placing their toys on the portal. Experimental · US 01.01.'),
                    ('replay-expansion-intros','Replay adventure pack introductions','Play the selected pack’s introduction after confirming travel at its Academy statue. Experimental · US 01.01.')]:
                    card=QWidget();card.setObjectName('settingRow');line=QHBoxLayout(card);line.setContentsMargins(20,16,20,16)
                    copy=QVBoxLayout();heading=QLabel(label);heading.setStyleSheet('font-size: 14px; font-weight: 600;');copy.addWidget(heading)
                    detail=QLabel(hint);detail.setWordWrap(True);detail.setStyleSheet('font-size: 12px; color: #93939e;');copy.addWidget(detail);line.addLayout(copy,1)
                    field=SettingSwitch();field.setFixedSize(44,28);field.setAccessibleName(label);line.addWidget(field)
                    self.mod_fields[key]=field;self.mod_rows.append(card);rows.addWidget(card)
            rows.addStretch();scroll.setWidget(sheet);column.addWidget(scroll,1);self.pages.addWidget(page)
            self.add_nav(navigation,name)
        log=QTextEdit();log.setReadOnly(True);log.setDocument(owner.log.document());self.pages.addWidget(log);self.add_nav(navigation,'Session log');navigation.addStretch()
        footer=QHBoxLayout();self.feedback=QLabel();self.feedback.setStyleSheet('color: #92929e; font-size: 12px;');footer.addWidget(self.feedback,1)
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.cancel);footer.addWidget(cancel)
        self.save_button=QPushButton('Save changes');self.save_button.setObjectName('settingsSave');self.save_button.clicked.connect(self.save);footer.addWidget(self.save_button);layout.addLayout(footer)
        self.fields['frame_policy'].currentIndexChanged.connect(self.frame_policy)
        self.setStyleSheet("""
            QWidget#settingsPage { background: #101012; }
            QWidget#settingRow { background: #1c1c20; border: 1px solid #29292f; border-radius: 12px; }
            QPushButton#settingsBack { background: transparent; border: none; color: #aaaab5; padding: 4px 0; text-align: left; }
            QPushButton#settingsNav { background: transparent; color: #9999a5; border: none; padding: 10px 16px; font-weight: 500; border-radius: 10px; }
            QPushButton#settingsNav:hover { background: #222227; color: #f5f5f7; }
            QPushButton#settingsNav:checked { background: #303037; color: #f5f5f7; }
            QPushButton#settingsSave { background: #f5f5f7; color: #171719; padding: 12px 24px; border: none; border-radius: 10px; }
            QComboBox { background: #29292f; border: 1px solid #3b3b44; border-radius: 8px; padding: 4px 12px; }
            QComboBox:disabled { color: #686872; border-color: #29292f; }
            QComboBox::drop-down { border: none; width: 26px; }
        """)
        self.select(0)

    def add_nav(self,layout,name):
        index=len(self.nav);button=QPushButton(name.replace('&','&&'));button.setObjectName('settingsNav');button.setCheckable(True);button.clicked.connect(lambda checked=False:self.select(index));layout.addWidget(button);self.nav.append(button)

    def select(self,index):
        self.pages.setCurrentIndex(index)
        for i,button in enumerate(self.nav):button.setChecked(i==index)

    def change_scope(self,index):
        key=self.scope.itemData(index)
        game=next((g for g in self.owner.library['games'] if g['id']==key),None)
        self.open(game)

    def open(self,game=None):
        self.game=game
        try:
            from .game_library import directory
        except ImportError:
            from game_library import directory
        self.games_row.setVisible(game is None);self.games_path.setText(str(directory(self.owner.root)))
        self.change_games.setEnabled(self.owner.process is None)
        self.scope.blockSignals(True);self.scope.clear();self.scope.addItem('General settings',None)
        for entry in self.owner.library['games']:self.scope.addItem(entry['name'],entry['id'])
        self.scope.setCurrentIndex(self.scope.findData(game['id']) if game else 0);self.scope.blockSignals(False)
        self.title.setText(game['name']+' settings' if game else 'General settings')
        self.notice.setText('Preferences and mods for this game.' if game else 'Default preferences for all games. Per-game settings take priority.')
        values={**self.owner.values(),**(game['settings'] if game else {})}
        self.baseline=dict(values)
        for key,field in self.fields.items():
            self.set_field(key,values[key])
            field.setEnabled(self.owner.process is None)
            if game and game['id']!='trap-team' and key in ('unlock_nightmare','level_events'):
                field.setEnabled(False);field.setToolTip('This tweak is currently implemented for Trap Team only.')
        try:
            from .launcher_mods import selection
        except ImportError:
            from launcher_mods import selection
        selected=selection(self.owner.root,game) if game else {}
        for row in self.mod_rows:row.setVisible(game is not None and game['id']=='trap-team')
        for key,field in self.mod_fields.items():
            field.setChecked(selected.get(key,False));field.setEnabled(self.owner.process is None and key!='any-portal')
            if key!='any-portal':
                recipe=self.owner.root/'profiles/patches'/f'trap-team-us-01.01-{key}.experimental.json'
                if not recipe.is_file():field.setEnabled(False);field.setToolTip('The mod recipe is unavailable in this checkout.')
        self.save_button.setEnabled(self.owner.process is None)
        self.feedback.setText('Stop the current session to change settings.' if self.owner.process else ('Saved per game · Applies to the next session.' if game else 'Changes apply to your next session.'))
        self.frame_policy();self.owner.views.setCurrentWidget(self)

    def set_field(self,key,value):
        field=self.fields[key]
        if isinstance(field,QComboBox):field.setCurrentIndex(field.findData(value))
        elif isinstance(field,QCheckBox):field.setChecked(value)
        elif isinstance(field,QSlider):field.setValue(value)
        else:field.setText(value)

    def frame_policy(self):
        self.fields['frame_limit'].setEnabled(self.owner.process is None and self.fields['frame_policy'].currentData()=='manual')

    def open_games_folder(self):
        try:
            from .launcher_library import open_games_folder
        except ImportError:
            from launcher_library import open_games_folder
        try:open_games_folder(self.owner.root)
        except (OSError,ValueError) as error:QMessageBox.warning(self,'Cannot open Games folder',str(error))

    def ask_move_games(self):
        question=QMessageBox(self);question.setWindowTitle('Change Games folder')
        question.setText('Would you like to move your installed games to this folder?')
        question.setInformativeText('You can also leave them where they are and use the new folder for future installs. Your saves and original game files are kept.')
        move=question.addButton('Move games',QMessageBox.ButtonRole.AcceptRole)
        leave=question.addButton('Leave games where they are',QMessageBox.ButtonRole.ActionRole)
        question.addButton(QMessageBox.StandardButton.Cancel);question.exec()
        if question.clickedButton() is move:return True
        if question.clickedButton() is leave:return False
        return None

    def change_games_folder(self):
        if self.owner.process:return
        try:
            from .game_library import directory
            from .launcher_library_location import LocationWorker
        except ImportError:
            from game_library import directory
            from launcher_library_location import LocationWorker
        destination=QFileDialog.getExistingDirectory(self,'Choose your Games folder',str(directory(self.owner.root)))
        if not destination or str(directory(self.owner.root).resolve())==str(Path(destination).resolve()):return
        move=self.ask_move_games()
        if move is None:return
        dialog=QProgressDialog('Updating your Games folder…','',0,100,self)
        dialog.setCancelButton(None);dialog.setWindowTitle('Games folder');dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0);dialog.setValue(0);dialog.show()
        worker=LocationWorker(self.owner.root,destination,move,self);self.location_worker=worker
        self.owner.library_transfer=True
        worker.finished.connect(lambda:setattr(self.owner,'library_transfer',False))
        self.change_games.setEnabled(False);self.save_button.setEnabled(False)
        def progress(value):
            dialog.setLabelText(value['message']);dialog.setValue(min(99,round(value['fraction']*100)))
        worker.progress.connect(progress)
        def finish(result=None,error=None):
            dialog.close();self.change_games.setEnabled(True);self.save_button.setEnabled(True)
            self.games_path.setText(str(directory(self.owner.root)))
            self.owner.rebuild_rail()
            if error:
                QMessageBox.warning(self,'Could not change Games folder',error);return
            for message in result['errors']:self.owner.log.append('Games-folder move: '+message)
            self.feedback.setText('Games folder updated. Other settings are saved separately.')
            if result['errors']:QMessageBox.warning(self,'Some games were kept in place','Some games could not be moved. They remain listed in your library. See the session log for details.')
        worker.completed.connect(lambda result:finish(result=result));worker.failed.connect(lambda error:finish(error=error))
        worker.finished.connect(worker.deleteLater);worker.start()

    def browse(self):
        if self.owner.process:return
        path,_=QFileDialog.getOpenFileName(self,'Choose starting figure','','Figure dumps (*.sky *.bin *.dump)')
        if path:self.fields['figure'].setText(path)

    def cancel(self):
        self.owner.views.setCurrentWidget(self.owner.canvas)

    def save(self):
        if self.owner.process:return
        values={}
        for key,field in self.fields.items():
            if isinstance(field,QComboBox):values[key]=field.currentData()
            elif isinstance(field,QCheckBox):values[key]=field.isChecked()
            elif isinstance(field,QSlider):values[key]=field.value()
            else:values[key]=field.text()
        try:
            values=model.validate(values)
            if self.game is not None:
                selected=dict(self.game['settings'])
                selected.update({key:value for key,value in values.items() if value!=self.baseline[key]})
                previous=self.game['settings'];previous_mods=self.game.get('mods');self.game['settings']=selected
                if self.game['id']=='trap-team':self.game['mods']={key:field.isChecked() for key,field in self.mod_fields.items() if key!='any-portal'}
                try:
                    try:
                        from . import launcher_library
                    except ImportError:
                        import launcher_library
                    launcher_library.save(self.owner.library_path,self.owner.library)
                except OSError:
                    self.game['settings']=previous
                    if previous_mods is None:self.game.pop('mods',None)
                    else:self.game['mods']=previous_mods
                    raise
            else:
                model.save(self.owner.preferences,values)
                self.owner.apply_values(values);self.owner.update_summary()
        except (OSError,ValueError,TypeError) as error:
            QMessageBox.warning(self,'Could not save settings',str(error));return
        self.baseline=dict(values);self.owner.refresh_game();self.feedback.setText('Game settings saved.' if self.game else 'General settings saved.')
