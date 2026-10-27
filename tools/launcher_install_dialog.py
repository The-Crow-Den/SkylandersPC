# SPDX-License-Identifier: GPL-3.0-or-later
"""Responsive, sequential PKG extraction using the supplied standalone tool."""
import os
from pathlib import Path
import uuid
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTextEdit, QMessageBox)
try:
    from . import launcher_packages as packages
except ImportError:
    import launcher_packages as packages


class InstallDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner; self.game = owner.game; self.process = None; self.cancelled = False
        self.setWindowTitle('Install · '+self.game['name']); self.resize(720,540)
        column = QVBoxLayout(self)
        note = QLabel('Extract a game PKG and an optional matching update. Original packages are kept.\n'
                      'Extraction does not prepare the native runtime or verify gameplay.')
        note.setWordWrap(True); column.addWidget(note)
        form = QFormLayout(); column.addLayout(form); self.fields = {}
        for key,title,initial in [('extractor','Package extractor',owner.library.get('extractor',str(packages.DEFAULT_EXTRACTOR))),
                                  ('game_pkg','Game PKG',self.game['game_pkg']),
                                  ('update_pkg','Update PKG (optional)',self.game['update_pkg'])]:
            row = QHBoxLayout(); field=QLineEdit(initial); self.fields[key]=field; row.addWidget(field)
            button=QPushButton('Browse…'); row.addWidget(button)
            def browse(checked=False,key=key,field=field):
                path,_=QFileDialog.getOpenFileName(self,'Select '+key,'','All files (*)' if key=='extractor' else 'PS4 packages (*.pkg)')
                if path: field.setText(path)
            button.clicked.connect(browse); form.addRow(title,row)
        self.output=QTextEdit();self.output.setReadOnly(True);self.output.document().setMaximumBlockCount(1500);column.addWidget(self.output)
        actions=QHBoxLayout();column.addLayout(actions)
        self.start=QPushButton('Extract & install');self.start.clicked.connect(self.begin);actions.addWidget(self.start)
        self.cancel=QPushButton('Close');self.cancel.clicked.connect(self.reject);actions.addWidget(self.cancel)

    def begin(self):
        extractor=Path(self.fields['extractor'].text().strip())
        if not extractor.is_file() or not os.access(extractor,os.X_OK):
            QMessageBox.warning(self,'Extractor unavailable','Choose an executable ps4-pkg-tool.');return
        jobs=[]
        for key,kind in [('game_pkg','base'),('update_pkg','update')]:
            path=self.fields[key].text().strip()
            if kind=='base' or path:
                if not Path(path).is_file() or Path(path).suffix.lower()!='.pkg':
                    QMessageBox.warning(self,'Invalid package','Choose an existing .pkg file for '+kind);return
                jobs.append((kind,str(Path(path).resolve())))
        self.game.update({key:self.fields[key].text().strip() for key in ('game_pkg','update_pkg')})
        self.owner.library['extractor']=str(extractor.resolve());self.owner.persist()
        self.extractor=str(extractor.resolve());self.jobs=jobs
        self.staging=self.owner.root / '.local/pkg-imports' / uuid.uuid4().hex
        try: self.staging.mkdir(parents=True)
        except OSError as error:
            QMessageBox.warning(self,'Install failed',str(error));return
        self.start.setEnabled(False)
        for field in self.fields.values(): field.setEnabled(False)
        self.cancel.setText('Cancel extraction');self.next_job()

    def next_job(self):
        if not self.jobs:
            try:
                destination=self.owner.root / ('Game' if self.game['id']=='trap-team' else '.local/library-games/'+self.game['id'])
                installed=packages.publish(self.staging,destination,self.game['id']=='trap-team')
                self.game['installed_paths']=installed;self.owner.persist()
                self.output.append('Extraction validated. Installed to:\n'+'\n'.join(installed)+'\nNative runtime preparation may still be required.')
                self.owner.refresh_readiness();self.owner.refresh_game()
                self.done_state()
            except (OSError,ValueError) as error: self.fail(str(error))
            return
        kind,path=self.jobs.pop(0);target=self.staging / kind
        try: target.mkdir()
        except OSError as error:
            self.fail(str(error)); return
        self.output.append('Extracting '+kind+' package…\nOutput: '+str(target))
        process=QProcess(self);self.process=process
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.error)
        process.start(self.extractor,[path,str(target)])

    def read_output(self):
        if self.process:
            self.output.insertPlainText(bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace'))
            self.output.ensureCursorVisible()

    def error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.process.deleteLater();self.process=None;self.fail('Package extractor failed to start.')

    def finished(self,code,status):
        if not self.process: return
        self.read_output();self.process.deleteLater();self.process=None
        if self.cancelled:
            self.fail('Extraction cancelled. Partial output was retained for inspection.');return
        if code!=0 or status!=QProcess.ExitStatus.NormalExit:
            self.fail(f'Extractor failed (exit {code}). No installation was published.');return
        self.next_job()

    def done_state(self):
        self.cancel.setText('Close');self.cancel.setEnabled(True);self.start.setEnabled(False)

    def fail(self,message):
        self.output.append('\n'+message+'\nImport folder: '+str(self.staging));self.done_state()

    def reject(self):
        if self.process:
            self.cancelled=True;self.process.kill();self.cancel.setEnabled(False)
            return
        super().reject()

    def closeEvent(self,event):
        if self.process:
            self.reject();event.ignore()
        else: event.accept()
