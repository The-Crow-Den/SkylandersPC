# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose a game and optional update; unpack both with visible progress."""
import sys
from pathlib import Path
import uuid
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTextEdit, QMessageBox, QProgressBar)
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
        self.setWindowTitle('Install '+self.game['name']); self.resize(700,380)
        column = QVBoxLayout(self);column.setSpacing(16)
        heading = QLabel('Install your game');heading.setStyleSheet('font-size: 24px; font-weight: 700;')
        column.addWidget(heading)
        note = QLabel('Choose the game’s PKG file and, if you have one, its update PKG.\n'
                      'The launcher unpacks and installs both. Your original PKG files are kept.')
        note.setWordWrap(True);column.addWidget(note)
        form = QFormLayout();column.addLayout(form);self.fields = {};self.browse_buttons = []
        # Begin with a fresh choice: old package paths can cause accidental reinstallation.
        for key,title,hint in [('game_pkg','1. Game PKG','Choose the base game .pkg file…'),
                                ('update_pkg','2. Update PKG (optional)','Choose its matching update, or leave empty…')]:
            row = QHBoxLayout();field = QLineEdit();field.setPlaceholderText(hint)
            self.fields[key] = field;row.addWidget(field)
            button = QPushButton('Choose file…');self.browse_buttons.append(button);row.addWidget(button)
            def browse(checked=False,key=key,field=field):
                title = 'Choose the game PKG' if key == 'game_pkg' else 'Choose the update PKG'
                path,_ = QFileDialog.getOpenFileName(self,title,'','PS4 packages (*.pkg)')
                if path:field.setText(path)
            button.clicked.connect(browse);form.addRow(title,row)
        location = QLabel('Install location: Games')
        location.setToolTip(str(game_library.directory(owner.root)))
        location.setWordWrap(True)
        column.addWidget(location)
        self.hint = QLabel('Already installed the game? Choose only its update PKG to add an update.')
        self.hint.setWordWrap(True);column.addWidget(self.hint)
        self.phase = QLabel('Choose your files, then click Install game.');self.phase.setWordWrap(True);column.addWidget(self.phase)
        self.progress = QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0)
        self.progress.setTextVisible(False);self.progress.hide();column.addWidget(self.progress)
        self.details = QPushButton('Show details');self.details.setCheckable(True)
        self.details.setMaximumWidth(120)
        self.details.setStyleSheet('border: none; background: transparent; color: #a9a9b1; text-align: left; padding: 4px 0;')
        column.addWidget(self.details)
        self.output = QTextEdit();self.output.setReadOnly(True);self.output.document().setMaximumBlockCount(1500)
        self.output.hide();column.addWidget(self.output)
        self.details.toggled.connect(self.toggle_details)
        actions = QHBoxLayout();column.addLayout(actions)
        self.open_folder = QPushButton('Open games folder');self.open_folder.clicked.connect(self.show_games_folder);actions.addWidget(self.open_folder)
        actions.addStretch()
        self.cancel = QPushButton('Close');self.cancel.clicked.connect(self.reject);actions.addWidget(self.cancel)
        self.start = QPushButton('Install game');self.start.setDefault(True);self.start.clicked.connect(self.begin);actions.addWidget(self.start)

    def toggle_details(self, checked):
        self.output.setVisible(checked);self.details.setText('Hide details' if checked else 'Show details')
        self.resize(self.width(),620 if checked else self.minimumSizeHint().height())

    def show_games_folder(self):
        try:launcher_library.open_games_folder(self.owner.root)
        except (OSError,ValueError) as error:QMessageBox.warning(self,'Cannot open Games folder',str(error))

    def begin(self):
        jobs = []
        for key,kind in [('game_pkg','base'),('update_pkg','update')]:
            path = self.fields[key].text().strip()
            if path:
                if not Path(path).is_file() or Path(path).suffix.lower() != '.pkg':
                    QMessageBox.warning(self,'Choose a PKG file','Choose an existing .pkg file for the '+('game' if kind=='base' else 'update')+'.');return
                jobs.append((kind,str(Path(path).resolve())))
        if not jobs:
            QMessageBox.warning(self,'Choose your game','Choose the game PKG. You can also choose an optional update PKG.');return
        try:
            installed = game_library.entries(self.owner.root)
            packages.check_packages(self.fields['game_pkg'].text().strip() or None,
                                    self.fields['update_pkg'].text().strip() or None,installed)
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,'Check your packages',str(error));return
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
                self.done_state();self.progress.setValue(1)
            except (OSError,ValueError) as error:self.fail('Could not finish installation: '+str(error))
            return
        kind,path = self.jobs.pop(0);target = self.staging / kind
        self.current_kind = kind
        label = 'game' if kind=='base' else 'update'
        self.phase.setText(f'Installing {label} ({self.completed_jobs+1} of {self.total_jobs})… This may take a few minutes.')
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
            self.fail('Installation cancelled. Your original PKG files and existing games were kept.');return
        if code!=0 or status!=QProcess.ExitStatus.NormalExit:
            self.output.append(f'Extractor failed (exit {code}). No installation was published.')
            self.fail('Could not unpack the '+('game' if self.current_kind=='base' else 'update')+'. Check that the PKG file is complete and try again.');return
        self.completed_jobs += 1;self.next_job()

    def done_state(self):
        self.cancel.setText('Close');self.cancel.setEnabled(True);self.start.setEnabled(False)
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
