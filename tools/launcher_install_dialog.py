# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose a game and optional update; unpack both with visible progress."""
import sys
from pathlib import Path
import uuid
from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QLineEdit, QPushButton, QFileDialog, QTextEdit, QMessageBox, QProgressBar, QStackedWidget, QWidget)
try:
    from . import game_library, launcher_library
    from . import launcher_packages as packages
except ImportError:
    import game_library, launcher_library
    import launcher_packages as packages


STYLE = """
QDialog#installWizard { background: #171719; }
QWidget#installPanel { background: #171719; }
QLabel#brandName { font-size: 16px; font-weight: 700; }
QLabel#stepCount { color: #a9a9b1; font-size: 12px; }
QLabel#wizardHeading { font-size: 29px; font-weight: 800; }
QLabel#description { color: #c2c2ca; font-size: 14px; }
QFrame#fileCard, QFrame#reviewCard { background: #222225; border: 1px solid #343438; border-radius: 12px; }
QLabel#fileName { color: #a9a9b1; font-size: 13px; }
QLabel#reviewSummary { font-size: 14px; }
QFrame#installFooter { background: transparent; border: none; border-top: 1px solid #343438; }
QPushButton#libraryPlay:disabled { background: #41515d; color: #8b9ca9; border: none; }
QPushButton#quiet { background: transparent; border-color: transparent; color: #a9a9b1; }
QPushButton#quiet:hover { background: #303034; color: #f5f5f7; }
QPushButton#browse { font-size: 14px; padding: 11px 20px; }
QProgressBar { background: #303034; border: none; border-radius: 5px; height: 8px; }
QProgressBar::chunk { background: #f5f5f7; border-radius: 5px; }
"""


def file_icon():
    """Small native-drawn folder symbol, without adding an image dependency."""
    pixmap = QPixmap(56,56);pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#303034'));painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0,0,56,56,16,16)
    painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#f5f5f7'),1.8))
    painter.drawRoundedRect(14,19,28,23,3,3)
    painter.drawLine(18,15,26,15);painter.drawLine(26,15,30,19);painter.drawLine(18,15,14,19)
    painter.drawLine(23,30,33,30);painter.drawLine(28,25,28,35);painter.end()
    return pixmap


class InstallDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner; self.game = owner.game
        self.process = None; self.cancelled = False
        self.setObjectName('installWizard');self.setStyleSheet(owner.styleSheet()+STYLE)
        self.setWindowTitle('Install '+self.game['name']);self.resize(1000,600);self.setMinimumWidth(940)
        outer = QHBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        try:
            from .launcher_shell import SkyCanvas, supplied_artwork
            from .launcher_theme import crystal_icon
        except ImportError:
            from launcher_shell import SkyCanvas, supplied_artwork
            from launcher_theme import crystal_icon
        themed = supplied_artwork(owner.root,self.game)
        artwork = SkyCanvas(show_portal=False);artwork.setFixedWidth(280);artwork.game = themed
        art_layout = QGridLayout(artwork);art_layout.setContentsMargins(24,28,24,28)
        app_name = QLabel('SKYLANDERS PC');app_name.setObjectName('eyebrow');art_layout.addWidget(app_name,0,0,Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
        brand = QLabel();brand.setObjectName('installGameLogo');brand.setAlignment(Qt.AlignmentFlag.AlignCenter);brand.setFixedHeight(170)
        logo = QPixmap(themed.get('logo',''))
        brand.setPixmap(logo.scaled(230,150,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
                        if not logo.isNull() else crystal_icon(size=110).pixmap(110,110))
        art_layout.addWidget(brand,0,0,Qt.AlignmentFlag.AlignCenter);artwork.anchor = brand
        game_name = QLabel(self.game['name']);game_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        game_name.setStyleSheet('font-size: 16px; font-weight: 600;');art_layout.addWidget(game_name,0,0,Qt.AlignmentFlag.AlignBottom|Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(artwork)
        panel = QWidget();panel.setObjectName('installPanel');outer.addWidget(panel,1)
        column = QVBoxLayout(panel);column.setContentsMargins(32,26,32,24);column.setSpacing(18)
        header = QHBoxLayout();header.setSpacing(14)
        identity = QVBoxLayout();identity.setSpacing(3)
        title = QLabel('Install game');title.setObjectName('brandName');identity.addWidget(title)
        caption = QLabel('Add to your library');caption.setObjectName('muted');identity.addWidget(caption)
        header.addLayout(identity);header.addStretch()
        self.step_label = QLabel();self.step_label.setObjectName('stepCount');header.addWidget(self.step_label)
        column.addLayout(header)
        steps = QHBoxLayout();steps.setSpacing(10);self.step_badges = []
        for index,name in enumerate(('Game','Update','Install')):
            badge = QLabel();badge.setAlignment(Qt.AlignmentFlag.AlignCenter);badge.setFixedHeight(35)
            self.step_badges.append((badge,name));steps.addWidget(badge,1)
        column.addLayout(steps)
        self.heading = QLabel();self.heading.setObjectName('wizardHeading');column.addWidget(self.heading)
        self.pages = QStackedWidget();self.pages.setMinimumHeight(245);column.addWidget(self.pages,1)
        self.fields = {};self.browse_buttons = [];self.file_labels = {}
        for key,description,button_text in [
                ('game_pkg','Choose the game file you want to install.\nLook for a file ending in .pkg.','Choose game file…'),
                ('update_pkg','If you have an update for this game, you can add it now.\nYou can also skip this and add it later.','Choose update file…')]:
            page = QWidget();layout = QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
            note = QLabel(description);note.setObjectName('description');note.setWordWrap(True);layout.addWidget(note)
            layout.setSpacing(16)
            field = QLineEdit(self);field.hide();self.fields[key] = field
            card = QFrame();card.setObjectName('fileCard');card.setMinimumHeight(155)
            card_layout = QHBoxLayout(card);card_layout.setContentsMargins(24,22,24,22);card_layout.setSpacing(20)
            icon = QLabel();icon.setPixmap(file_icon());icon.setFixedSize(56,56);card_layout.addWidget(icon)
            file_content = QVBoxLayout();file_content.setSpacing(10);card_layout.addLayout(file_content,1)
            file_content.addStretch()
            button = QPushButton(button_text);button.setObjectName('browse')
            self.browse_buttons.append(button);file_content.addWidget(button,0,Qt.AlignmentFlag.AlignLeft)
            label = QLabel('No file chosen');label.setObjectName('fileName');label.setWordWrap(True)
            self.file_labels[key] = label;file_content.addWidget(label);file_content.addStretch()
            layout.addWidget(card)
            def browse(checked=False,key=key,field=field):
                title = 'Choose your game file' if key == 'game_pkg' else 'Choose your update file'
                path,_ = QFileDialog.getOpenFileName(self,title,'','Game files (*.pkg)')
                if path:field.setText(path)
            button.clicked.connect(browse)
            field.textChanged.connect(lambda text,key=key:self.file_changed(key,text))
            if key == 'game_pkg':
                self.update_only = QPushButton('I only want to add an update');self.update_only.setObjectName('quiet')
                self.update_only.setVisible(bool(self.game.get('installed_paths')))
                self.update_only.clicked.connect(self.add_update_only);layout.addWidget(self.update_only)
            layout.addStretch();self.pages.addWidget(page)
        review = QWidget();review_layout = QVBoxLayout(review);review_layout.setContentsMargins(0,0,0,0)
        review_layout.setSpacing(18)
        review_card = QFrame();review_card.setObjectName('reviewCard')
        card_layout = QHBoxLayout(review_card);card_layout.setContentsMargins(24,24,24,24);card_layout.setSpacing(20)
        icon = QLabel();icon.setPixmap(file_icon());card_layout.addWidget(icon)
        self.summary = QLabel();self.summary.setObjectName('reviewSummary');self.summary.setWordWrap(True);card_layout.addWidget(self.summary,1)
        review_layout.addWidget(review_card)
        location = QLabel('We’ll put everything in your Games folder.');location.setObjectName('description');location.setWordWrap(True);review_layout.addWidget(location)
        self.hint = QLabel('Your original files will stay where they are.');self.hint.setWordWrap(True);self.hint.setObjectName('muted')
        review_layout.addWidget(self.hint);review_layout.addStretch();self.pages.addWidget(review)
        progress_page = QWidget();progress_layout = QVBoxLayout(progress_page);progress_layout.setContentsMargins(0,0,0,0)
        self.phase = QLabel();self.phase.setObjectName('description');self.phase.setWordWrap(True);progress_layout.addWidget(self.phase)
        self.progress = QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0)
        self.progress.setTextVisible(False);progress_layout.addWidget(self.progress)
        progress_layout.addStretch();self.pages.addWidget(progress_page)
        self.details = QPushButton('Show details');self.details.setCheckable(True)
        self.details.setMaximumWidth(120)
        self.details.setStyleSheet('border: none; background: transparent; color: #a9a9b1; text-align: left; padding: 4px 0;')
        column.addWidget(self.details)
        self.output = QTextEdit();self.output.setReadOnly(True);self.output.document().setMaximumBlockCount(1500)
        self.output.hide();column.addWidget(self.output);self.details.toggled.connect(self.toggle_details)
        footer = QFrame();footer.setObjectName('installFooter')
        actions = QHBoxLayout(footer);actions.setContentsMargins(0,18,0,0);actions.setSpacing(8);column.addWidget(footer)
        self.open_folder = QPushButton('Open games folder');self.open_folder.setObjectName('libraryPlay');self.open_folder.clicked.connect(self.show_games_folder);actions.addWidget(self.open_folder)
        self.back = QPushButton('Back');self.back.setObjectName('quiet');self.back.clicked.connect(self.go_back);actions.addWidget(self.back)
        actions.addStretch()
        self.skip = QPushButton('Skip for now');self.skip.setObjectName('quiet');self.skip.clicked.connect(self.skip_update);actions.addWidget(self.skip)
        self.cancel = QPushButton('Cancel');self.cancel.setObjectName('quiet');self.cancel.clicked.connect(self.reject);actions.addWidget(self.cancel)
        self.start = QPushButton('Continue');self.start.setObjectName('libraryPlay');self.start.setMinimumSize(140,50);self.start.setDefault(True);self.start.clicked.connect(self.advance);actions.addWidget(self.start)
        self.only_update = False;self.show_step(0)

    def file_changed(self, key, text):
        self.file_labels[key].setText(Path(text).name if text else 'No file chosen')
        self.file_labels[key].setToolTip(text)
        if hasattr(self,'step') and self.step in (0,1):
            self.start.setEnabled(bool(self.fields['game_pkg' if self.step==0 else 'update_pkg'].text().strip()))

    def show_step(self, step):
        self.step = step;self.pages.setCurrentIndex(step)
        self.step_label.setText(f'Step {step+1} of 3' if step < 3 else '')
        for index,(badge,name) in enumerate(self.step_badges):
            complete = index < min(step,2)
            active = index == step or step == 3 and index == 2
            color = '#f5f5f7' if active or complete else '#777780'
            background = 'transparent'
            border = '#f5f5f7' if active else '#343438'
            badge.setText(('✓' if complete else str(index+1))+'   '+name)
            badge.setStyleSheet(f'color: {color}; background: {background}; border: none; border-bottom: 2px solid {border}; font-size: 12px; font-weight: 600;')
        self.heading.setText(('Choose your game','Do you have an update?','Ready to install?','Installing your game')[step])
        self.back.setVisible(step in (1,2));self.skip.setVisible(step==1 and not self.only_update)
        self.open_folder.setVisible(False);self.details.setVisible(step==3)
        self.start.setVisible(step<3);self.start.setText('Install game' if step==2 else 'Continue')
        self.start.setEnabled(step==2 or (step<2 and bool(self.fields['game_pkg' if step==0 else 'update_pkg'].text().strip())))
        if step==2:
            game = self.fields['game_pkg'].text().strip()
            update = self.fields['update_pkg'].text().strip()
            self.summary.setText('Game: '+(Path(game).name if game else 'Already installed')+
                                 '\nUpdate: '+(Path(update).name if update else 'Not adding an update'))

    def add_update_only(self):
        self.only_update = True;self.fields['game_pkg'].clear();self.show_step(1)

    def go_back(self):
        if self.step==1:self.only_update = False
        self.show_step(max(0,self.step-1))

    def skip_update(self):
        self.fields['update_pkg'].clear();self.show_step(2)

    def advance(self):
        if self.step==0:
            path = Path(self.fields['game_pkg'].text().strip())
            try:
                if not path.is_file() or path.suffix.lower()!='.pkg':
                    raise ValueError('Choose your game file first. It should end in .pkg.')
                if packages.package_info(path).get('CATEGORY')!='gd':
                    raise ValueError('This looks like an update. Choose the game file first, then add the update in the next step.')
            except (OSError,ValueError) as error:
                QMessageBox.warning(self,'Check your game file',str(error));return
            self.show_step(1)
        elif self.step==1:
            if not self.checked_jobs():return
            self.show_step(2)
        elif self.step==2:self.begin()

    def toggle_details(self, checked):
        self.output.setVisible(checked);self.details.setText('Hide details' if checked else 'Show details')
        self.resize(self.width(),800 if checked else max(600,self.minimumSizeHint().height()))

    def show_games_folder(self):
        try:launcher_library.open_games_folder(self.owner.root)
        except (OSError,ValueError) as error:QMessageBox.warning(self,'Cannot open Games folder',str(error))

    def checked_jobs(self):
        jobs = []
        for key,kind in [('game_pkg','base'),('update_pkg','update')]:
            path = self.fields[key].text().strip()
            if path:
                if not Path(path).is_file() or Path(path).suffix.lower() != '.pkg':
                    QMessageBox.warning(self,'Choose your file','Choose a file ending in .pkg for the '+('game' if kind=='base' else 'update')+'.');return
                jobs.append((kind,str(Path(path).resolve())))
        if not jobs:
            QMessageBox.warning(self,'Choose your game','Choose your game file first. You can add an update afterwards.');return
        try:
            installed = game_library.entries(self.owner.root)
            packages.check_packages(self.fields['game_pkg'].text().strip() or None,
                                    self.fields['update_pkg'].text().strip() or None,installed)
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,'Check your files',str(error));return
        return jobs

    def begin(self):
        jobs = self.checked_jobs()
        if not jobs:return
        self.show_step(3)
        self.game['operation']={'state':'Installing','message':'Unpacking your game…'}
        self.owner.refresh_game()
        self.source_packages = [Path(path).name for _,path in jobs]
        self.game.update({key:self.fields[key].text().strip() for key in ('game_pkg','update_pkg')})
        self.owner.persist();self.extractor = packages.BUILTIN_EXTRACTOR
        self.jobs = jobs;self.total_jobs = len(jobs);self.completed_jobs = 0
        self.staging = self.owner.root / '.local/pkg-imports' / uuid.uuid4().hex
        try:self.staging.mkdir(parents=True)
        except OSError as error:
            QMessageBox.warning(self,'Cannot start installation',str(error));return
        self.start.setEnabled(False)
        for field in [*self.fields.values(),*self.browse_buttons]:field.setEnabled(False)
        self.cancel.setText('Cancel installation');self.progress.show();self.progress.setRange(0,0)
        self.next_job()

    def next_job(self):
        if not self.jobs:
            self.phase.setText('Finishing installation…')
            try:
                entry = packages.publish(self.staging,game_library.directory(self.owner.root),self.source_packages)
                hidden=game_library.removed(self.owner.root)
                restored={game_library.selector(entry['title_id'],version) for version in (entry['base_version'],entry['app_version'])}
                hidden=[key for key in hidden if key not in restored]
                game_library.write_json(self.owner.root/'.local/removed-games.json',hidden)
                launcher_library.sync_installations(self.owner.root,self.owner.library)
                profile = game_library.profile_for(self.owner.root,entry)
                key = profile['id'] if profile else 'title-'+entry['title_id'].lower()
                self.owner.library['selected'] = key
                game = next(g for g in self.owner.library['games'] if g['id']==key)
                self.game.pop('operation',None);self.game=game
                game_library.select(self.owner.root,game['installation']);self.owner.persist()
                installed = game['installed_paths']
                self.output.append('Extraction validated. Installed to:\n'+'\n'.join(installed))
                self.owner.rebuild_rail()
                self.phase.setText(game['name']+' is installed. Your game files are in the Games folder.')
                self.hint.setText('You can close this window. The launcher will show whether the game is ready to play.')
                self.done_state(success=True);self.progress.setValue(1)
                if game_library.supported(self.owner.root,entry):
                    self.start_preparation(entry)
                else:
                    self.phase.setText(game['name']+' is installed. This game is not supported yet.')
            except (OSError,ValueError) as error:self.fail('Could not finish installation: '+str(error))
            return
        kind,path = self.jobs.pop(0);target = self.staging / kind
        self.current_kind = kind
        label = 'game' if kind=='base' else 'update'
        self.phase.setText(f'Installing {label} ({self.completed_jobs+1} of {self.total_jobs})… We’ll take care of the files. This may take a few minutes.')
        self.output.append('Extracting '+label+' package…\nOutput: '+str(target))
        process = QProcess(self);self.process = process
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished);process.errorOccurred.connect(self.error)
        process.start(sys.executable,['-u',str(self.extractor),path,str(target)])

    def start_preparation(self, entry, optional=()):
        try:
            from .launcher_prepare import PreparationProcess
        except ImportError:
            from launcher_prepare import PreparationProcess
        self.game['operation']={'state':'Preparing','message':'Checking your game files…'}
        self.owner.refresh_game()
        self.show_step(3);self.heading.setText('Getting your game ready')
        self.phase.setText('Checking your game files…');self.cancel.setText('Cancel setup')
        self.open_folder.hide();self.progress.setRange(0,100);self.progress.setValue(0)
        worker = PreparationProcess(self);self.preparation = worker
        worker.log.connect(self.append_log)
        self.owner.log.append('Full setup log: '+str(self.staging/'setup.log'))
        def update(value):
            self.game['operation']={'state':'Preparing','message':value['message'],'fraction':value['fraction']}
            self.owner.refresh_game()
            if value['state'] not in ('optional','available'):
                self.phase.setText(value['message']);self.progress.setValue(round(value['fraction']*100))
        worker.progress.connect(update)
        worker.finished.connect(self.preparation_finished)
        worker.start(self.owner.root,game_library.selector(entry['title_id'],entry['app_version']),optional)

    def preparation_finished(self, success, message):
        self.done_state(success=success)
        self.open_folder.show()
        self.heading.setText('Your game is ready' if success else 'Game installed · setup needs attention')
        self.phase.setText(message if success else 'Your game files are installed. '+message)
        self.progress.setValue(1 if success else 0)
        self.owner.refresh_readiness();self.owner.refresh_game()

    def append_log(self, text):
        self.output.insertPlainText(text);self.owner.log.insertPlainText(text)
        if hasattr(self,'staging'):
            try:
                self.staging.mkdir(parents=True,exist_ok=True)
                with (self.staging/'setup.log').open('a') as stream:stream.write(text)
            except OSError:pass

    def read_output(self):
        if self.process:
            output = bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
            self.append_log(output);self.output.ensureCursorVisible()

    def error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.process.deleteLater();self.process=None;self.fail('The installer could not start. Close this window and try again.')

    def finished(self,code,status):
        if not self.process:return
        self.read_output();self.process.deleteLater();self.process=None
        if self.cancelled:
            self.fail('Installation cancelled. Your original files and existing games were kept.');return
        if code!=0 or status!=QProcess.ExitStatus.NormalExit:
            self.output.append(f'Extractor failed (exit {code}). No installation was published.')
            self.fail('Could not unpack the '+('game' if self.current_kind=='base' else 'update')+'. Check that the PKG file is complete and try again.');return
        self.completed_jobs += 1;self.next_job()

    def done_state(self, success=False):
        self.game.pop('operation',None)
        self.owner.refresh_game()
        self.heading.setText('Your game is installed' if success else 'Installation stopped')
        self.cancel.setText('Done' if success else 'Close');self.cancel.setEnabled(True);self.start.setEnabled(False)
        self.open_folder.setVisible(success)
        if success:self.step_badges[2][0].setText('✓   Install')
        self.progress.setRange(0,1);self.progress.setValue(0)

    def fail(self,message):
        self.phase.setText(message if 'cancelled' in message.lower() else 'Installation could not finish. Check your files and available space, then try again. Your existing games were kept.')
        self.append_log('\n'+message+'\nImport folder: '+str(self.staging));self.done_state()

    def reject(self):
        if getattr(self,'preparation',None) and self.preparation.process:
            self.preparation.cancel();self.cancel.setEnabled(False);return
        if self.process:
            self.cancelled=True;self.process.kill();self.cancel.setEnabled(False);return
        super().reject()

    def closeEvent(self,event):
        if self.process or (getattr(self,'preparation',None) and self.preparation.process):self.reject();event.ignore()
        else:event.accept()


class RepairDialog(InstallDialog):
    """Reuse the accepted installer presentation for setup and optional extras."""
    def __init__(self, owner, optional=()):
        super().__init__(owner)
        self.setWindowTitle('Repair '+self.game['name'])
        self.show_step(3);self.heading.setText('Checking your game')
        self.staging = owner.root/'.local/game-preparation'
        def begin():
            try:self.start_preparation(game_library.resolve_entry(owner.root,game=self.game),optional)
            except (OSError,ValueError) as error:self.preparation_finished(False,str(error))
        QTimer.singleShot(0,begin)
