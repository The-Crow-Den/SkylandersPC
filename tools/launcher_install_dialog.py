# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose a game and optional update; unpack both with visible progress."""
import sys
from pathlib import Path
import uuid
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTextEdit, QMessageBox, QProgressBar, QStackedWidget, QWidget)
try:
    from . import game_library, launcher_library
    from . import launcher_packages as packages
except ImportError:
    import game_library, launcher_library
    import launcher_packages as packages


class InstallDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner; self.game = owner.game
        self.process = None; self.cancelled = False
        self.setWindowTitle('Install '+self.game['name']); self.resize(620,410)
        column = QVBoxLayout(self);column.setSpacing(16)
        self.step_label = QLabel();self.step_label.setStyleSheet('color: #a9a9b1;')
        column.addWidget(self.step_label)
        self.heading = QLabel();self.heading.setStyleSheet('font-size: 24px; font-weight: 700;')
        column.addWidget(self.heading)
        self.pages = QStackedWidget();column.addWidget(self.pages,1)
        self.fields = {};self.browse_buttons = [];self.file_labels = {}
        for key,description,button_text in [
                ('game_pkg','Choose the game file you want to install.\nLook for a file ending in .pkg.','Choose game file…'),
                ('update_pkg','If you have an update for this game, you can add it now.\nYou can also skip this and add it later.','Choose update file…')]:
            page = QWidget();layout = QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
            note = QLabel(description);note.setWordWrap(True);layout.addWidget(note)
            field = QLineEdit(self);field.hide();self.fields[key] = field
            button = QPushButton(button_text);self.browse_buttons.append(button);layout.addWidget(button)
            label = QLabel('No file chosen');label.setWordWrap(True);self.file_labels[key] = label;layout.addWidget(label)
            def browse(checked=False,key=key,field=field):
                title = 'Choose your game file' if key == 'game_pkg' else 'Choose your update file'
                path,_ = QFileDialog.getOpenFileName(self,title,'','Game files (*.pkg)')
                if path:field.setText(path)
            button.clicked.connect(browse)
            field.textChanged.connect(lambda text,key=key:self.file_changed(key,text))
            if key == 'game_pkg':
                self.update_only = QPushButton('I only want to add an update')
                self.update_only.setVisible(bool(self.game.get('installed_paths')))
                self.update_only.clicked.connect(self.add_update_only);layout.addWidget(self.update_only)
            layout.addStretch();self.pages.addWidget(page)
        review = QWidget();review_layout = QVBoxLayout(review);review_layout.setContentsMargins(0,0,0,0)
        self.summary = QLabel();self.summary.setWordWrap(True);review_layout.addWidget(self.summary)
        review_layout.addWidget(QLabel('We’ll unpack the files and put the game in your Games folder.'))
        self.hint = QLabel('Your original files will stay where they are.');self.hint.setWordWrap(True)
        review_layout.addWidget(self.hint);review_layout.addStretch();self.pages.addWidget(review)
        progress_page = QWidget();progress_layout = QVBoxLayout(progress_page);progress_layout.setContentsMargins(0,0,0,0)
        self.phase = QLabel();self.phase.setWordWrap(True);progress_layout.addWidget(self.phase)
        self.progress = QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0)
        self.progress.setTextVisible(False);progress_layout.addWidget(self.progress)
        progress_layout.addStretch();self.pages.addWidget(progress_page)
        self.details = QPushButton('Show details');self.details.setCheckable(True)
        self.details.setMaximumWidth(120)
        self.details.setStyleSheet('border: none; background: transparent; color: #a9a9b1; text-align: left; padding: 4px 0;')
        column.addWidget(self.details)
        self.output = QTextEdit();self.output.setReadOnly(True);self.output.document().setMaximumBlockCount(1500)
        self.output.hide();column.addWidget(self.output);self.details.toggled.connect(self.toggle_details)
        actions = QHBoxLayout();column.addLayout(actions)
        self.open_folder = QPushButton('Open games folder');self.open_folder.clicked.connect(self.show_games_folder);actions.addWidget(self.open_folder)
        self.back = QPushButton('Back');self.back.clicked.connect(self.go_back);actions.addWidget(self.back)
        actions.addStretch()
        self.skip = QPushButton('Skip for now');self.skip.clicked.connect(self.skip_update);actions.addWidget(self.skip)
        self.cancel = QPushButton('Cancel');self.cancel.clicked.connect(self.reject);actions.addWidget(self.cancel)
        self.start = QPushButton('Continue');self.start.setDefault(True);self.start.clicked.connect(self.advance);actions.addWidget(self.start)
        self.only_update = False;self.show_step(0)

    def file_changed(self, key, text):
        self.file_labels[key].setText(Path(text).name if text else 'No file chosen')
        self.file_labels[key].setToolTip(text)
        if hasattr(self,'step') and self.step in (0,1):
            self.start.setEnabled(bool(self.fields['game_pkg' if self.step==0 else 'update_pkg'].text().strip()))

    def show_step(self, step):
        self.step = step;self.pages.setCurrentIndex(step)
        self.step_label.setText(f'Step {step+1} of 3' if step < 3 else '')
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
        self.resize(self.width(),620 if checked else self.minimumSizeHint().height())

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
                launcher_library.sync_installations(self.owner.root,self.owner.library)
                profile = game_library.profile_for(self.owner.root,entry)
                key = profile['id'] if profile else 'title-'+entry['title_id'].lower()
                self.owner.library['selected'] = key
                game = next(g for g in self.owner.library['games'] if g['id']==key)
                game_library.select(self.owner.root,game['installation']);self.owner.persist()
                installed = game['installed_paths']
                self.output.append('Extraction validated. Installed to:\n'+'\n'.join(installed))
                self.owner.rebuild_rail()
                self.phase.setText(game['name']+' is installed. Your game files are in the Games folder.')
                self.hint.setText('You can close this window. The launcher will show whether the game is ready to play.')
                self.done_state(success=True);self.progress.setValue(1)
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

    def read_output(self):
        if self.process:
            output = bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
            self.output.insertPlainText(output);self.output.ensureCursorVisible()

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
        self.heading.setText('Your game is installed' if success else 'Installation stopped')
        self.cancel.setText('Done' if success else 'Close');self.cancel.setEnabled(True);self.start.setEnabled(False)
        self.open_folder.setVisible(success)
        self.progress.setRange(0,1);self.progress.setValue(0)

    def fail(self,message):
        self.phase.setText(message)
        self.output.append('\n'+message+'\nImport folder: '+str(self.staging));self.done_state()

    def reject(self):
        if self.process:
            self.cancelled=True;self.process.kill();self.cancel.setEnabled(False);return
        super().reject()

    def closeEvent(self,event):
        if self.process:self.reject();event.ignore()
        else:event.accept()
