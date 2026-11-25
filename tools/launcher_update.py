# SPDX-License-Identifier: GPL-3.0-or-later
"""Launcher side of tools/updater.py: automatic updates.

Release installs check GitHub at start, download a newer release in the
background (verified against its published SHA-256) and install it when the
launcher closes. The pill shows the progress; once the update is ready,
clicking it restarts the launcher into the new version. A git checkout keeps
the old flow: the pill offers `git pull`.
"""
import threading
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
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
    progress = pyqtSignal(float)
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)


def check(relay, kind):
    try:release = updater.latest(timeout=6)
    except Exception:release = None  # offline or rate-limited: say nothing
    try:relay.found.emit(release)
    except RuntimeError:return  # the window closed meanwhile
    if not release or kind not in ('linux', 'windows'):return
    if updater.staged() == release['version']:
        relay.ready.emit(release);return
    try:
        updater.download(release, kind, progress=relay.progress.emit)
        relay.ready.emit(release)
    except RuntimeError:pass
    except Exception as error:
        try:relay.failed.emit(str(error))
        except RuntimeError:pass


class UpdateControl:
    def __init__(self, owner, pill):
        self.owner, self.pill, self.release, self.ready = owner, pill, None, False
        self.kind = updater.install_kind();self.percent = -1
        pill.hide();pill.clicked.connect(self.clicked)
        self.relay = Relay(owner)
        self.relay.found.connect(self.found);self.relay.progress.connect(self.progress)
        self.relay.ready.connect(self.downloaded);self.relay.failed.connect(self.failed)
        app = QApplication.instance()
        if app is not None:app.aboutToQuit.connect(self.install_on_exit)
        # A daemon thread, so closing the launcher never waits on (or aborts over) the network.
        threading.Thread(target=check, args=(self.relay, self.kind), daemon=True).start()

    def found(self, release):
        if not release:return
        self.release = release
        self.owner.log.append('Update available: v' + release['version'] + ' ' + release['url'])
        self.pill.setText('Update available · v' + release['version'])
        if self.kind in ('linux', 'windows'):
            self.pill.setText('Downloading update · v' + release['version'])
            self.pill.setToolTip('The new version downloads in the background and installs when the launcher closes.')
        self.pill.show()

    def progress(self, fraction):
        percent = int(fraction * 100)
        if percent != self.percent and self.release:
            self.percent = percent
            self.pill.setText(f'Downloading update · {percent}%')

    def downloaded(self, release):
        self.release, self.ready = release, True
        self.pill.setText('Restart to update · v' + release['version'])
        self.pill.setToolTip('Version ' + release['version'] + ' is ready. It installs when the launcher closes, or now with a restart.')
        self.pill.show()
        self.owner.log.append('Update v' + release['version'] + ' downloaded; it installs when the launcher closes.')

    def failed(self, message):
        self.owner.log.append('Automatic update failed: ' + message)
        if self.release:
            self.pill.setText('Update available · v' + self.release['version'])
            self.pill.setToolTip('The automatic download failed. Click to open the release page.')
        self.kind = 'manual'

    def install_on_exit(self):
        if not self.ready or getattr(self, 'started', False):return
        try:updater.apply_later(self.kind, relaunch=getattr(self, 'relaunch', False));self.started = True
        except OSError as error:
            self.owner.log.append('The update could not be installed: ' + str(error))

    def clicked(self):
        if not self.release:return
        if self.ready:
            if getattr(self.owner, 'process', None):
                QMessageBox.information(self.owner, 'Update Skylanders PC', 'The update installs when you close the game and the launcher.');return
            self.relaunch = True;self.owner.close();return
        if self.kind in ('linux', 'windows'):
            QMessageBox.information(self.owner, 'Update Skylanders PC',
                                    'Version ' + self.release['version'] + ' is downloading. It installs by itself when the launcher closes.');return
        self.offer()

    def offer(self):
        release, kind = self.release, self.kind
        notes = release['notes'].strip() or 'No release notes.'
        box = QMessageBox(self.owner);box.setWindowTitle('Update Skylanders PC')
        box.setText(f'Version {release["version"]} is available (you have {updater.VERSION}).')
        box.setInformativeText(notes[:1200])
        if kind != 'git':
            box.setInformativeText(notes[:1200] + '\n\nDownload the new version from the release page and replace this one. Your games, saves and settings stay where they are.')
            page = box.addButton('Open release page', QMessageBox.ButtonRole.AcceptRole)
        else:
            page = box.addButton('Update now', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Later', QMessageBox.ButtonRole.RejectRole);box.exec()
        if box.clickedButton() is not page:return
        if kind != 'git':
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
