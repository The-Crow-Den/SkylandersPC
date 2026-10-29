# SPDX-License-Identifier: GPL-3.0-or-later
"""Responsive JSONL preparation worker shared by installation and Repair."""
import json
import os
from pathlib import Path
import signal
import sys
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

PREPARER = Path(__file__).with_name('game_prepare.py')


class PreparationProcess(QObject):
    progress = pyqtSignal(dict)
    log = pyqtSignal(str)
    finished = pyqtSignal(bool,str)

    def __init__(self, parent=None):
        super().__init__(parent);self.process = None;self.buffer = '';self.error = '';self.ready = False;self.cancelled = False
        self.optional_errors = []

    def start(self, root, choice, optional=()):
        process = QProcess(self);self.process = process
        process.setWorkingDirectory(str(root))
        process.readyReadStandardOutput.connect(self.read_stdout)
        process.readyReadStandardError.connect(lambda:self.log.emit(bytes(process.readAllStandardError()).decode('utf-8',errors='replace')))
        process.errorOccurred.connect(self.process_error);process.finished.connect(self.complete)
        args = ['-u',str(PREPARER),'--root',str(root),'--game',choice]
        for name in optional:args += ['--optional',name]
        process.start(sys.executable,args)

    def read_stdout(self):
        if not self.process:return
        self.buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        if len(self.buffer)>1024*1024:
            self.error = 'The setup log could not be read. Choose Repair to try again.';self.cancel();return
        while '\n' in self.buffer:
            line,self.buffer = self.buffer.split('\n',1)
            if not line.strip():continue
            self.log.emit(line+'\n')
            try:
                value = json.loads(line)
                if (not isinstance(value,dict) or not all(isinstance(value.get(k),str) for k in ('name','state','message')) or
                        type(value.get('fraction')) not in (int,float) or not 0<=value['fraction']<=1):raise ValueError('Invalid progress')
                self.progress.emit(value)
                if value['state']=='failed':
                    self.error = value['message']
                    prefix,separator,message = self.error.partition(': ')
                    if separator and (prefix in ('verify-executable','recipes','renderer','runtime') or prefix.startswith('pack.')):self.error = message
                if value['state']=='optional-failed':self.optional_errors.append(value['message'])
                if value['name']=='ready' and value['state']=='complete':self.ready = True
            except ValueError:self.error = 'The setup log could not be read. Choose Repair to try again.'

    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.error = 'Setup could not start. Choose Repair to try again.'
            self.complete(-1,QProcess.ExitStatus.CrashExit)

    def complete(self,code,status):
        if not self.process:return
        self.read_stdout();process = self.process;self.process = None;process.deleteLater()
        if self.buffer.strip():self.error = 'Setup ended before its progress report was complete.'
        success = code==0 and status==QProcess.ExitStatus.NormalExit and self.ready and not self.error and not self.cancelled
        message = 'Setup cancelled. Your installed game files were kept.' if self.cancelled else self.error or ('Setup complete.' if success else 'Setup did not finish. Choose Repair to try again.')
        if success and self.optional_errors:message += ' Optional artwork was unavailable; your game can still start.'
        self.finished.emit(success,message)

    def cancel(self):
        self.cancelled = True
        if not self.process:return
        process = self.process;pid = int(process.processId());process.terminate()
        def force():
            if self.process is not process:return
            try:os.killpg(pid,signal.SIGKILL)
            except ProcessLookupError:process.kill()
        QTimer.singleShot(5000,force)
