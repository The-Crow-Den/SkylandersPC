# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep folder transfers off the Qt UI thread."""
from PyQt6.QtCore import QThread, pyqtSignal
try:
    from . import library_location
except ImportError:
    import library_location


class LocationWorker(QThread):
    progress = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, project, destination, move, parent=None):
        super().__init__(parent);self.project=project;self.destination=destination;self.move=move

    def run(self):
        try:self.completed.emit(library_location.change(self.project,self.destination,move=self.move,progress=self.progress.emit))
        except (OSError,ValueError) as error:self.failed.emit(str(error))
