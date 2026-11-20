# SPDX-License-Identifier: GPL-3.0-or-later
"""Launcher side of tools/updater.py: a quiet background check and an update pill."""
import threading
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QProgressDialog
try:
    from . import updater
except ImportError:
    import updater


class Worker(QThread):
    done = pyqtSignal(object, str)

    def __init__(self, parent, release):
        super().__init__(parent);self.release = release

    def run(self):
        try:
            updater.update_git();self.done.emit(True, 'git')
        except Exception as error:
            self.done.emit(False, str(error))


class Relay(QObject):
    found = pyqtSignal(object)


def check(relay):
    try:release = updater.latest(timeout=6)
    except Exception:release = None  # offline or rate-limited: say nothing
    try:relay.found.emit(release)
    except RuntimeError:pass  # the window closed meanwhile


class UpdateControl:
    def __init__(self, owner, pill):
        self.owner, self.pill, self.release = owner, pill, None
        pill.hide();pill.clicked.connect(self.offer)
        # A daemon thread, so closing the launcher never waits on (or aborts over) the network.
        self.relay = Relay(owner);self.relay.found.connect(self.found)
        threading.Thread(target=check, args=(self.relay,), daemon=True).start()

    def found(self, release):
        if release:
            self.release = release
            self.pill.setText('Update available · v' + release['version']);self.pill.show()
            self.owner.log.append('Update available: v' + release['version'] + ' ' + release['url'])

    def offer(self):
        release, kind = self.release, updater.install_kind()
        notes = release['notes'].strip() or 'No release notes.'
        box = QMessageBox(self.owner);box.setWindowTitle('Update Skylanders PC')
        box.setText(f'Version {release["version"]} is available (you have {updater.VERSION}).')
        box.setInformativeText(notes[:1200])
        if kind == 'manual':
            box.setInformativeText(notes[:1200] + '\n\nDownload the new version from the release page and replace this one. Your games, saves and settings stay where they are.')
            page = box.addButton('Open release page', QMessageBox.ButtonRole.AcceptRole)
        else:
            page = box.addButton('Update now', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Later', QMessageBox.ButtonRole.RejectRole);box.exec()
        if box.clickedButton() is not page:return
        if kind == 'manual':
            QDesktopServices.openUrl(QUrl(release['url']));return
        if getattr(self.owner, 'process', None):
            QMessageBox.information(self.owner, 'Update Skylanders PC', 'Close the game first, then update.');return
        self.dialog = QProgressDialog('Updating…', None, 0, 0, self.owner)
        self.dialog.setWindowTitle('Updating');self.dialog.setMinimumDuration(0);self.dialog.show()
        worker = Worker(self.owner, release);self.worker = worker
        worker.done.connect(self.finished);worker.start()

    def finished(self, ok, detail):
        self.dialog.close()
        if not ok:
            QMessageBox.warning(self.owner, 'Update failed', detail + '\n\nNothing was changed.');return
        self.pill.hide()
        QMessageBox.information(self.owner, 'Update installed',
                                'The source was updated. Rebuild the native host and renderer (see README), then restart the launcher.')
