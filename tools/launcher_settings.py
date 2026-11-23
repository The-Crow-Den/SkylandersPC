# SPDX-License-Identifier: GPL-3.0-or-later
"""Dedicated settings view for the portal library, with explicit Save/Cancel."""
from pathlib import Path
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QStackedWidget,QScrollArea,QFormLayout,QComboBox,QCheckBox,QSlider,QLineEdit,
    QTextEdit,QFileDialog,QMessageBox,QProgressDialog,QSpinBox,QDoubleSpinBox)
try:
    from . import launcher_model as model
except ImportError:
    import launcher_model as model

GROUPS = [
 ('Display','Picture and window preferences.', [('language','Game language'),('resolution','Resolution'),('aspect','Aspect ratio'),('quality','Shadow quality'),('fullscreen','Fullscreen'),('motion_blur','Motion blur'),('anti_aliasing','Anti-aliasing')]),
 ('Performance','Frame pacing and optional overlays.', [('fps_counter','Show FPS counter'),('trophy_popups','Show trophy popups'),('gpu','Graphics card'),('mangohud','MangoHud overlay'),('level_events','Record level events (diagnostic)')]),
 ('Portal & audio','Starting figure and portal speaker preferences.', [('portal_device','Portal'),('figure','Starting figure'),('portal_volume','Portal speaker volume')]),
 ('Storage','Disk space used by games, shaders and caches.', [('save_shaders','Save compiled shaders'),('cache_limit_gb','Cache size limit')]),
 ('Tweaks','Optional game behavior changes and diagnostic tools.', [('skip_intro','Skip startup logos'),('unlock_nightmare','Nightmare available by default')]),
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
        super().__init__();self.owner=owner;self.fields={};self.nav=[];self.mod_fields={};self.mod_setting_fields={};self.mod_rows=[];self.game=None;self.baseline={}
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
            'language':'Text and voices, when the game has them. Movies follow it in English, Spanish, French and Portuguese.',
            'resolution':'Internal rendering resolution.',
            'aspect':'Wider screens show more of the world to the sides; menus and HUD keep their shape. Movies stay 16:9.', 'quality':'Detail and definition of game shadows.',
            'fullscreen':'Use the full display when starting a game.', 'motion_blur':'Smooth motion during camera movement.', 'anti_aliasing':'Smooth jagged edges (FXAA-style, almost free).',
            'fps_counter':'Show frame rate during play.', 'trophy_popups':'Show a popup in the corner when a trophy unlocks.', 'gpu':'Automatic uses NVIDIA when its driver works, otherwise the built-in GPU.',
            'mangohud':'Requires MangoHud to be installed separately.', 'figure':'Choose the figure placed at the start of a session.',
            'portal_volume':'Volume of voices from the portal speaker.', 'portal_device':'Automatic uses a plugged-in PS3/PS4/Wii/Wii U portal and otherwise the virtual portal with figure files. Physical portals are experimental.', 'unlock_nightmare':'Make Nightmare available when creating a save.',
            'skip_intro':'Go straight past the Activision, Toys for Bob and Beenox logos. US update only.',
            'level_events':'Record events for troubleshooting.',
            'cache_limit_gb':'Largest size for each rebuildable cache (mod output, movie audio). Past it, the least recently used files are deleted at game start.',
            'save_shaders':'Keep shaders after compiling them, so areas you have visited load smoothly next time. Off: nothing is saved and every visit compiles again.'}
        for name,description,entries in GROUPS:
            entries = [e for e in entries if e[0] not in model.LINUX_ONLY or e[0] in model.platform_settings()]
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
            if name=='Storage':
                self.storage_rows=QVBoxLayout();self.storage_rows.setSpacing(8);rows.addLayout(self.storage_rows)
                self.free_label=QLabel();self.free_label.setStyleSheet('color: #92929e; font-size: 13px;');rows.addWidget(self.free_label)
            if name=='Portal & audio':
                card=QWidget();card.setObjectName('settingRow');line=QHBoxLayout(card);line.setContentsMargins(20,12,20,12);line.setSpacing(12)
                self.portal_status=QLabel();self.portal_status.setWordWrap(True);self.portal_status.setStyleSheet('font-size: 12px; color: #93939e;');line.addWidget(self.portal_status,1)
                self.portal_access=QPushButton('Set up portal access');self.portal_access.clicked.connect(self.setup_portal_access);line.addWidget(self.portal_access)
                rescan=QPushButton('Refresh');rescan.clicked.connect(lambda:self.refresh_portals());line.addWidget(rescan)
                rows.addWidget(card)
            rows.addStretch();scroll.setWidget(sheet);column.addWidget(scroll,1);self.pages.addWidget(page)
            self.add_nav(navigation,name)
        page=QWidget();column=QVBoxLayout(page);column.setContentsMargins(0,4,0,0);column.setSpacing(14)
        top=QHBoxLayout();self.mods_caption=QLabel();self.mods_caption.setWordWrap(True);self.mods_caption.setStyleSheet('color: #92929e; font-size: 13px;');top.addWidget(self.mods_caption,1)
        folder=QPushButton('Open mods folder');folder.clicked.connect(self.open_mods_folder);top.addWidget(folder);column.addLayout(top)
        scroll=QScrollArea();scroll.setWidgetResizable(True);sheet=QWidget();self.mods_list=QVBoxLayout(sheet);self.mods_list.setContentsMargins(0,0,4,0);self.mods_list.setSpacing(8)
        scroll.setWidget(sheet);column.addWidget(scroll,1);self.pages.addWidget(page);self.add_nav(navigation,'Mods')
        log=QTextEdit();log.setReadOnly(True);log.setDocument(owner.log.document());self.pages.addWidget(log);self.add_nav(navigation,'Session log');navigation.addStretch()
        footer=QHBoxLayout();self.feedback=QLabel();self.feedback.setStyleSheet('color: #92929e; font-size: 12px;');footer.addWidget(self.feedback,1)
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.cancel);footer.addWidget(cancel)
        self.save_button=QPushButton('Save changes');self.save_button.setObjectName('settingsSave');self.save_button.clicked.connect(self.save);footer.addWidget(self.save_button);layout.addLayout(footer)
        self.setStyleSheet("""
            QWidget#settingsPage { background: #101012; }
            QWidget#settingRow { background: #1c1c20; border: 1px solid #29292f; border-radius: 12px; }
            QPushButton#settingsBack { background: transparent; border: none; color: #aaaab5; padding: 4px 0; text-align: left; }
            QPushButton#settingsNav { background: transparent; color: #9999a5; border: none; padding: 10px 16px; font-weight: 500; border-radius: 10px; }
            QPushButton#settingsNav:hover { background: #222227; color: #f5f5f7; }
            QPushButton#settingsNav:checked { background: #303037; color: #f5f5f7; }
            QPushButton#settingsSave { background: #f5f5f7; color: #171719; padding: 12px 24px; border: none; border-radius: 10px; }
            QLabel#modTag { color: #a9a9b4; background: #26262c; border: 1px solid #34343c; border-radius: 6px; padding: 1px 7px; font-size: 11px; font-weight: 600; }
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
        self.refresh_storage();self.refresh_portals(keep=False)
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
        self.fill_mods(game,selected)
        self.save_button.setEnabled(self.owner.process is None)
        self.feedback.setText('Stop the current session to change settings.' if self.owner.process else ('Saved per game · Applies to the next session.' if game else 'Changes apply to your next session.'))
        self.owner.views.setCurrentWidget(self)

    def fill_mods(self,game,selected):
        """One row per mod.json found, with its switch and settings for this game."""
        try:
            from .launcher_mods import catalogue
        except ImportError:
            from launcher_mods import catalogue
        while self.mods_list.count():
            item=self.mods_list.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.mod_fields={};self.mod_setting_fields={}
        if game is None:
            self.mods_caption.setText('Mods are chosen per game. Pick a game in the menu above. Add your own mods to the mods folder.')
            self.mods_list.addStretch();return
        rows,error=catalogue(self.owner.root,game)
        self.mods_caption.setText(error or 'Mods change the game for the next session. Each one is checked against your installed version first.')
        saved=game.get('mod_settings',{})
        status_text={'ready':'Works with your version','other-build':'Not made for your version',
                     'not-installed':'Install the game to use mods','unavailable':'Recipe missing from this copy'}
        editable=self.owner.process is None
        for mod in rows:
            card=QWidget();card.setObjectName('settingRow');outer=QVBoxLayout(card);outer.setContentsMargins(20,16,20,16);outer.setSpacing(10)
            line=QHBoxLayout();line.setSpacing(24);outer.addLayout(line)
            copy=QVBoxLayout();copy.setSpacing(4)
            title=QHBoxLayout();title.setSpacing(8)
            heading=QLabel(mod['name']);heading.setStyleSheet('font-size: 14px; font-weight: 600;');title.addWidget(heading)
            ready=mod['status']=='ready'
            origin=QLabel('Built in' if mod['builtin'] else 'Your mod');origin.setObjectName('modTag');title.addWidget(origin)
            title.addStretch();copy.addLayout(title)
            if mod['description']:
                detail=QLabel(mod['description']);detail.setWordWrap(True);detail.setStyleSheet('font-size: 12px; color: #93939e;');copy.addWidget(detail)
            card.setToolTip(f"Version {mod['version']} · {mod['author']}\nMade for: "+', '.join(mod['targets']))
            if not ready:
                # Only problems need a line; a working mod says nothing extra.
                problem=QLabel('⚠  '+status_text[mod['status']]);problem.setWordWrap(True)
                problem.setStyleSheet('font-size: 12px; color: #e1bb70;');copy.addWidget(problem)
            line.addLayout(copy,1)
            if mod['controlled']:
                note=QLabel(mod['controlled']);note.setWordWrap(True);note.setFixedWidth(240);note.setStyleSheet('font-size: 12px; color: #93939e;');line.addWidget(note)
            else:
                field=SettingSwitch();field.setFixedSize(44,28);field.setAccessibleName(mod['name'])
                field.setChecked(selected.get(mod['id'],False));field.setEnabled(editable and ready)
                if not ready:field.setToolTip(status_text[mod['status']])
                line.addWidget(field);self.mod_fields[mod['id']]=field
                for name,spec in mod['settings'].items():
                    value=saved.get(mod['id'],{}).get(name,spec['default'])
                    row=QHBoxLayout();label=QLabel(name.replace('-',' ').capitalize());label.setStyleSheet('font-size: 12px;');row.addWidget(label,1)
                    if spec['type']=='bool':
                        widget=SettingSwitch();widget.setFixedSize(44,28);widget.setChecked(value is True)
                    elif spec['type']=='choice':
                        widget=SettingCombo();widget.setFixedWidth(240);widget.setMinimumHeight(34)
                        for choice in spec['choices']:widget.addItem(choice.replace('-',' ').capitalize(),choice)
                        widget.setCurrentIndex(max(0,widget.findData(value)))
                    else:
                        integer=all(type(spec[key]) is int for key in ('min','max','default'))
                        widget=QSpinBox() if integer else QDoubleSpinBox();widget.setRange(spec['min'],spec['max']);widget.setValue(value);widget.setFixedWidth(240)
                    widget.setAccessibleName(f"{mod['name']}: {label.text()}");widget.setEnabled(editable and ready)
                    row.addWidget(widget);outer.addLayout(row);self.mod_setting_fields[(mod['id'],name)]=widget
            self.mods_list.addWidget(card)
        if not rows:
            empty=QLabel('No mods found.');empty.setStyleSheet('color: #92929e;');self.mods_list.addWidget(empty)
        self.mods_list.addStretch()

    def mod_choices(self):
        mods={key:field.isChecked() for key,field in self.mod_fields.items()}
        settings={}
        for (ident,name),widget in self.mod_setting_fields.items():
            if isinstance(widget,QComboBox):value=widget.currentData()
            elif isinstance(widget,QCheckBox):value=widget.isChecked()
            else:value=widget.value()
            settings.setdefault(ident,{})[name]=value
        return mods,settings

    def open_mods_folder(self):
        folder=self.owner.root/'mods'
        try:
            folder.mkdir(exist_ok=True)
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except OSError as error:QMessageBox.warning(self,'Cannot open mods folder',str(error))

    def refresh_portals(self,keep=True):
        """Rescan portals and copy the launcher's list into this page's chooser."""
        try:
            from . import portal_devices
        except ImportError:
            import portal_devices
        mine=self.fields['portal_device'];chosen=mine.currentData() if keep else None
        self.owner.refresh_portals(chosen or self.owner.fields['portal_device'].currentData())
        original=self.owner.fields['portal_device'];mine.blockSignals(True);mine.clear()
        for i in range(original.count()):mine.addItem(original.itemText(i),original.itemData(i))
        mine.setCurrentIndex(max(0,mine.findData(chosen or original.currentData())));mine.blockSignals(False)
        portals=portal_devices.list_portals()
        blocked=[p for p in portals if not p['accessible']]
        xbox=[p for p in portals if p['family']!='hid']
        if blocked:text='A portal is plugged in, but this account cannot open it yet. Set up access once (asks for your password), then unplug and replug the portal.'
        elif [p for p in portals if p['family']=='hid']:text='Portal ready. Place figures on it; the game reads them directly. Figure writes stay off unless allowed.'
        elif xbox:text='Xbox portals are detected but not supported yet. Use a PS3/PS4/Wii/Wii U portal or the virtual portal.'
        else:text='No physical portal found. Plug one in and press Refresh, or use the virtual portal.'
        self.portal_status.setText(text)
        self.portal_access.setVisible(bool(blocked) and portal_devices.install_rule_command() is not None)

    def setup_portal_access(self):
        try:
            from . import portal_devices
        except ImportError:
            import portal_devices
        import subprocess
        command=portal_devices.install_rule_command()
        if not command:
            QMessageBox.information(self,'Portal access',portal_devices.access_help());return
        try:result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        except (OSError,subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self,'Portal access',str(error));return
        if result.returncode!=0:
            QMessageBox.warning(self,'Portal access','Access was not set up.\n\n'+(result.stderr.strip() or portal_devices.access_help()));return
        QMessageBox.information(self,'Portal access','Done. Unplug the portal, plug it back in, then press Refresh.')
        self.refresh_portals()

    def refresh_storage(self):
        try:
            from . import storage
        except ImportError:
            import storage
        while self.storage_rows.count():
            item=self.storage_rows.takeAt(0)
            if item.widget():item.widget().deleteLater()
        try:rows,free=storage.usage(self.owner.root)
        except OSError as error:
            self.free_label.setText('Could not measure disk space: '+str(error));return
        for row in rows:
            card=QWidget();card.setObjectName('settingRow');line=QHBoxLayout(card);line.setContentsMargins(20,12,20,12);line.setSpacing(16)
            copy=QVBoxLayout();copy.setSpacing(2)
            heading=QLabel(row['label']);heading.setStyleSheet('font-size: 14px; font-weight: 600;');copy.addWidget(heading)
            if row['note']:
                note=QLabel(row['note']);note.setWordWrap(True);note.setStyleSheet('font-size: 12px; color: #93939e;');copy.addWidget(note)
            line.addLayout(copy,1)
            amount=QLabel(storage.human(row['bytes']));amount.setStyleSheet('font-size: 14px; color: #d6d6de;');line.addWidget(amount)
            if row['clearable']:
                button=QPushButton('Clear');button.setEnabled(self.owner.process is None and row['bytes']>0)
                button.setToolTip('Stop the game first.' if self.owner.process else '')
                button.clicked.connect(lambda checked=False,row=row:self.clear_storage(row));line.addWidget(button)
            self.storage_rows.addWidget(card)
        self.free_label.setText('Free space on this drive: '+storage.human(free) if free is not None else '')

    def clear_storage(self,row):
        try:
            from . import storage
        except ImportError:
            import storage
        if self.owner.process is not None:return
        answer=QMessageBox.question(self,'Clear '+row['label'].lower(),
            f"Delete {storage.human(row['bytes'])} of {row['label'].lower()}?\n\n{row['note']}")
        if answer!=QMessageBox.StandardButton.Yes:return
        try:freed=storage.clear(self.owner.root,row['key'])
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,'Could not clear',str(error));return
        self.feedback.setText('Freed '+storage.human(freed)+'.');self.refresh_storage()

    def set_field(self,key,value):
        field=self.fields[key]
        if isinstance(field,QComboBox):field.setCurrentIndex(field.findData(value))
        elif isinstance(field,QCheckBox):field.setChecked(value)
        elif isinstance(field,QSlider):field.setValue(value)
        else:field.setText(value)

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
        try:from .launcher_files import choose_folder
        except ImportError:from launcher_files import choose_folder
        destination=choose_folder(self,'Choose your Games folder',str(directory(self.owner.root)))
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
        try:from .launcher_files import choose_file
        except ImportError:from launcher_files import choose_file
        path=choose_file(self,'Choose starting figure',('.sky','.bin','.dump'))
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
        # Settings this page does not show keep their current values: the swapper
        # bottom half (chosen on the Portal page) and options hidden on this
        # platform (NVIDIA and MangoHud on Windows). Without them, validation
        # refused every save as "Unknown or missing launcher settings".
        for key,default in model.DEFAULTS.items():
            values.setdefault(key,self.baseline.get(key,default))
        try:
            values=model.validate(values)
            if self.game is not None:
                selected=dict(self.game['settings'])
                selected.update({key:value for key,value in values.items() if value!=self.baseline[key]})
                previous=self.game['settings'];previous_mods=self.game.get('mods');previous_mod_settings=self.game.get('mod_settings')
                self.game['settings']=selected
                mods,mod_settings=self.mod_choices()
                self.game['mods']={**self.game.get('mods',{}),**mods}
                if mod_settings:self.game['mod_settings']={**self.game.get('mod_settings',{}),**mod_settings}
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
                    if previous_mod_settings is None:self.game.pop('mod_settings',None)
                    else:self.game['mod_settings']=previous_mod_settings
                    raise
            else:
                model.save(self.owner.preferences,values)
                self.owner.apply_values(values);self.owner.update_summary()
        except (OSError,ValueError,TypeError) as error:
            QMessageBox.warning(self,'Could not save settings',str(error));return
        self.baseline=dict(values);self.owner.refresh_game();self.feedback.setText('Game settings saved.' if self.game else 'General settings saved.')
