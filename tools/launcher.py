#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local Skylanders library launcher. Requires PyQt6; the runtime does not."""
import os
from pathlib import Path
import signal
import sys

try:
    from PyQt6.QtCore import QProcess, Qt, QSize
    from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
        QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPushButton, QSlider, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QScrollArea)
except ImportError:
    raise SystemExit('The optional launcher needs PyQt6. You can still use tools/run_session.py.')

try:
    from . import launcher_model as model
    from .launcher_theme import STYLE, Hero, PortraitStrip, crystal_icon, feature_card, text_label
    from .pc_settings import load_settings, save_settings
    from .resolution import PRESETS
except ImportError:
    import launcher_model as model
    from launcher_theme import STYLE, Hero, PortraitStrip, crystal_icon, feature_card, text_label
    from pc_settings import load_settings, save_settings
    from resolution import PRESETS

ROOT = Path(__file__).resolve().parents[1]


def launcher_icon(root):
    folder = Path(root) / '.local/app-icon'
    return folder / 'launcher.png' if (folder / 'launcher.png').is_file() else folder / 'crystal@2x.png'


class Launcher(QMainWindow):
    def __init__(self, root=ROOT):
        super().__init__()
        self.root = Path(root)
        self.preferences = self.root / '.local/launcher-settings.json'
        self.process = None
        self.stopping = False
        self.output_buffer = ''
        self.setWindowTitle('Trap Team · PC')
        icon=launcher_icon(self.root)
        if icon.is_file():
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1160, 790)
        self.setMinimumSize(960, 700)
        self.setStyleSheet(STYLE)
        central = QWidget(); central.setObjectName('canvas')
        self.setCentralWidget(central)
        shell = QVBoxLayout(central); shell.setContentsMargins(0,0,0,0); shell.setSpacing(0)
        content = QHBoxLayout(); content.setSpacing(0)
        shell.addLayout(content, 1)
        sidebar = QWidget(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(185)
        rail = QVBoxLayout(sidebar); rail.setContentsMargins(12,26,12,20); rail.setSpacing(5)
        brand = text_label('PORTAL MASTER'); brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet('font-size: 11px; font-weight: 800; letter-spacing: 2px; color: #f1d59a; padding: 8px 0 22px;')
        rail.addWidget(brand)
        self.nav_buttons=[]
        for i, (name, color) in enumerate((('Adventure','#8ce5ff'),('Graphics','#87c9ff'),('Portal & controls','#9fe5ab'),('Game mods','#d7afff'),('Session log','#e1bb70'))):
            button=QPushButton(name.replace('&','&&'));button.setObjectName('nav');button.setCheckable(True)
            button.clicked.connect(lambda checked=False,index=i:self.tabs.setCurrentIndex(index))
            rail.addWidget(button);self.nav_buttons.append(button)
        rail.addStretch()
        rail.addWidget(text_label('SKYLANDERS\nTRAP TEAM', 'eyebrow'))
        rail.addWidget(text_label('Your PC adventure', 'muted'))
        content.addWidget(sidebar)
        self.tabs=QStackedWidget()
        self.tabs.currentChanged.connect(self.navigation_changed)
        content.addWidget(self.tabs, 1)
        self.fields={}
        home=QWidget();home_layout=QVBoxLayout(home);home_layout.setContentsMargins(26,22,26,20);home_layout.setSpacing(15)
        home_layout.addWidget(text_label('YOUR ADVENTURE', 'eyebrow'))
        home_layout.addWidget(Hero(self.root), 5)
        cards=QHBoxLayout();cards.setSpacing(12)
        cards.addWidget(feature_card('Make it yours', 'Graphics & frame rate', '#86ccff', lambda:self.tabs.setCurrentIndex(1)))
        cards.addWidget(feature_card('Power the portal', 'Skylanders & controls', '#9fe5ab', lambda:self.tabs.setCurrentIndex(2)))
        cards.addWidget(feature_card('Raise the stakes', 'Nightmare & game mods', '#d2adff', lambda:self.tabs.setCurrentIndex(3)))
        home_layout.addLayout(cards)
        villains=QHBoxLayout();villains.setSpacing(22)
        caption=QVBoxLayout();caption.addWidget(text_label('GOOD TO BE BAD', 'eyebrow'))
        caption.addWidget(text_label('Catch the troublemakers.'))
        more=QPushButton('Meet your virtual portal  →');more.clicked.connect(lambda:self.tabs.setCurrentIndex(2));caption.addWidget(more)
        villains.addLayout(caption, 4);villains.addWidget(PortraitStrip(self.root), 6)
        home_layout.addLayout(villains, 2)
        self.home_summary=text_label('', 'muted');home_layout.addWidget(self.home_summary)
        self.tabs.addWidget(home)

        display=self.page('Graphics', 'A little more magic. A little more detail.', 'Tune your picture and frame rate. Applied choices are shared with the in-game PC menu.')
        self.combo(display,'Internal resolution','resolution',[(f'{k}  ·  {w} × {h}',k) for k,(w,h) in PRESETS.items()])
        self.combo(display,'Shadow detail','quality',[('Original','balanced'),('High','high'),('Low','performance')])
        self.combo(display,'Frame policy','frame_policy',[('Automatic · 60 gameplay / 30 menus & portal','auto'),('Manual frame limit','manual')])
        self.combo(display,'Frame limit','frame_limit',[('30 FPS',30),('60 FPS · experimental timing',60),('Uncapped · diagnostic',0)])
        self.check(display,'Fullscreen','fullscreen')
        self.check(display,'Show frame rate','fps_counter')
        self.check(display,'Show trophy popups','trophy_popups')
        self.check(display,'Motion blur','motion_blur')
        self.check(display,'Use NVIDIA GPU','nvidia')
        self.check(display,'MangoHud overlay · optional installation','mangohud')
        display.addRow(text_label('Automatic follows gameplay, loading, cutscenes and portal arrival. Shift+F1 takes manual control for this session.','muted'))

        portal=self.page('Portal & controls','Bring your collection to life.','Choose a starting Skylander. Manage figures and individual villain traps in the game’s right-hand portal drawer.')
        self.fields['figure']=QLineEdit();self.fields['figure'].setPlaceholderText('Choose a Skylander figure dump…')
        # A swapper's starting bottom half is chosen on the Portal page, not typed here.
        self.fields['figure_bottom']=QLineEdit();self.fields['figure_bottom'].setVisible(False)
        row=QHBoxLayout();row.addWidget(self.fields['figure'],1)
        browse=QPushButton('Browse…');browse.clicked.connect(self.browse);row.addWidget(browse)
        portal.addRow('Starting Skylander',row)
        volume=QSlider(Qt.Orientation.Horizontal);volume.setRange(0,100);self.fields['portal_volume']=volume
        self.volume_label=QLabel();volume.valueChanged.connect(lambda n:self.volume_label.setText(f'{n}%'))
        row=QHBoxLayout();row.addWidget(volume,1);row.addWidget(self.volume_label);portal.addRow('Portal speaker',row)
        self.devices=text_label('');portal.addRow('Controllers',self.devices)
        refresh=QPushButton('Refresh controllers');refresh.clicked.connect(self.refresh_devices);portal.addRow(refresh)
        portal.addRow(text_label('F6 / Insert / L3+R3   ·   PC settings & virtual portal\nF2   ·   Choose a Skylander\nF10   ·   Minimize game for recording\n\nNew villain traps start empty, ready for in-game capture. Virtual Traptanium is available; physical portal support is still in development.','muted'))
        portal.addRow(PortraitStrip(self.root))

        mods=self.page('Game mods','Your adventure. Your rules.','PC features that respect your existing progress.')
        self.check(mods,'Make Nightmare available immediately','unlock_nightmare')
        mods.addRow(text_label('Choose Nightmare when creating a save. Existing games keep their difficulty.','muted'))
        self.check(mods,'Record level events · diagnostic only','level_events')
        mods.addRow(text_label('Original game files are preserved. Level-event diagnostics do not control FPS yet.','muted'))
        self.log=QTextEdit();self.log.setReadOnly(True);self.log.document().setMaximumBlockCount(400)
        self.tabs.addWidget(self.log)
        self.navigation_changed(0)

        footer=QWidget();footer.setObjectName('footer');actions=QHBoxLayout(footer);actions.setContentsMargins(24,15,24,15);actions.setSpacing(16)
        self.status=text_label('Checking your adventure…','muted');actions.addWidget(self.status,1)
        self.stop=QPushButton('Stop game');self.stop.setEnabled(False);self.stop.clicked.connect(self.stop_game);actions.addWidget(self.stop)
        self.play=QPushButton('PLAY TRAP TEAM   ▶');self.play.setObjectName('play');self.play.setMinimumWidth(248);self.play.clicked.connect(self.launch);actions.addWidget(self.play)
        shell.addWidget(footer)
        value = dict(model.DEFAULTS)
        value['nvidia'] = Path('/usr/share/vulkan/icd.d/nvidia_icd.json').is_file()
        try:
            if self.preferences.exists():
                value.update(model.load(self.preferences))
            # In-game applied graphics choices win over a stale launcher copy.
            value.update(load_settings(self.root / 'out/pc-settings.json'))
        except (OSError, ValueError, TypeError) as error:
            self.log.append(f'Saved settings could not be loaded: {error}')
        self.apply_values(value)
        self.refresh_devices()
        self.refresh_readiness()
        self.update_summary()
        for key in ("resolution", "frame_limit", "frame_policy"):
            self.fields[key].currentIndexChanged.connect(self.update_summary)

    def apply_values(self, value):
        for key, selected in value.items():
            # In-game-only choices (e.g. controller layout) have no launcher field.
            field = self.fields.get(key)
            if field is None:
                continue
            if isinstance(field, QComboBox):
                field.setCurrentIndex(field.findData(selected))
            elif isinstance(field, QCheckBox):
                field.setChecked(selected)
            elif isinstance(field, QSlider):
                field.setValue(selected)
            else:
                field.setText(selected)

    def navigation_changed(self, index):
        for i,button in enumerate(self.nav_buttons):
            button.setChecked(i==index)

    def update_summary(self):
        if not hasattr(self,'home_summary'): return
        resolution=self.fields['resolution'].currentData()
        fps=self.fields['frame_limit'].currentData()
        automatic=self.fields['frame_policy'].currentData()=='auto'
        self.fields['frame_limit'].setEnabled(not automatic)
        if automatic: fps='Auto 30/60'
        self.home_summary.setText(f'{resolution}  /  {fps or "Uncapped"} FPS     •     Virtual Traptanium     •     F6 opens PC settings in game')

    def page(self, title, heading, description):
        page=QWidget();column=QVBoxLayout(page);column.setContentsMargins(30,24,30,24);column.setSpacing(14)
        column.addWidget(text_label(title.upper(),'eyebrow'))
        column.addWidget(text_label(heading,'pageTitle'))
        column.addWidget(text_label(description,'muted'))
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        sheet=QWidget();sheet.setObjectName('sheet');form=QFormLayout(sheet)
        form.setContentsMargins(24,22,24,22);form.setSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(sheet);column.addWidget(scroll,1)
        self.tabs.addWidget(page)
        return form

    def combo(self, form, label, key, choices):
        field = QComboBox()
        for text, value in choices:
            field.addItem(text, value)
        self.fields[key] = field
        form.addRow(label, field)

    def check(self, form, label, key):
        field = QCheckBox(label)
        self.fields[key] = field
        form.addRow(field)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose Skylander', self.fields['figure'].text(), 'Figure dumps (*.sky *.bin *.dump);;All files (*)')
        if path:
            self.fields['figure'].setText(path)

    def values(self):
        value = {}
        for key, field in self.fields.items():
            if isinstance(field, QComboBox): value[key] = field.currentData()
            elif isinstance(field, QCheckBox): value[key] = field.isChecked()
            elif isinstance(field, QSlider): value[key] = field.value()
            else: value[key] = field.text()
        return model.validate(value)

    def refresh_devices(self):
        self.devices.setText('\n'.join(model.controllers()) or 'No joystick devices detected. Connect a controller to test it in game.')

    def refresh_readiness(self):
        missing = model.missing_files(self.root, getattr(self, 'game', None))
        self.status.setText('Setup incomplete · see Session log' if missing else 'Ready for adventure')
        if missing: self.log.append('Missing local files: ' + ', '.join(missing))
        self.play.setEnabled(not missing)

    def launch(self):
        if self.process is not None:
            return
        try:
            value = self.values()
            if value['figure'] and not Path(value['figure']).is_file():
                raise ValueError('The selected figure file is missing.')
            if value['figure_bottom'] and not Path(value['figure_bottom']).is_file():
                value['figure_bottom'] = ''
            model.save(self.preferences, value)
            pc_path = self.root / 'out/pc-settings.json'
            pc_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                pc_value = load_settings(pc_path)
            except (OSError, ValueError, TypeError):
                pc_value = {}
            pc_value.update({key: value[key] for key in model.PC_KEYS})
            save_settings(pc_path, pc_value)
            argv = model.command(self.root, sys.executable, value, mods=getattr(self, 'session_mods', None), game=getattr(self, 'game', None))
        except (OSError, ValueError, TypeError) as error:
            QMessageBox.warning(self, 'Cannot start Trap Team', str(error))
            return
        self.output_buffer = ''
        self.stopping = False
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(self.root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.process_error)
        self.tabs.setEnabled(False)
        self.play.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText('Preparing Trap Team…')
        self.log.append('Starting a session with no time limit.')
        process.started.connect(lambda: self.status.setText('Preparing game files…') if not self.stopping else None)
        process.start(argv[0], argv[1:])

    def read_output(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
            self.output_buffer = (self.output_buffer + text)[-32768:]
            self.last_output = text
            self.log.moveCursor(self.log.textCursor().MoveOperation.End)
            self.log.insertPlainText(text)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finished(-1, QProcess.ExitStatus.CrashExit)

    def finished(self, code, status):
        if self.process is None:
            return
        self.read_output()
        self.process.deleteLater()
        self.process = None
        self.tabs.setEnabled(True)
        self.stop.setEnabled(False)
        try:
            self.apply_values(load_settings(self.root / 'out/pc-settings.json'))
        except (OSError, ValueError, TypeError) as error:
            self.log.append(f'Applied PC settings could not be loaded: {error}')
        self.refresh_readiness()
        self.update_summary()
        if self.stopping:
            self.status.setText('Game stopped at your request.')
        elif code == 0 and status == QProcess.ExitStatus.NormalExit:
            self.status.setText('Session ended normally.')
        else:
            self.status.setText(f'Session failed (exit {code}). See Session log for details.')
            self.tabs.setCurrentWidget(self.log)

    def stop_game(self):
        if self.process and not self.stopping:
            self.stopping = True
            self.stop.setEnabled(False)
            self.status.setText('Stopping the session…')
            self.interrupt_runner()

    def interrupt_runner(self):
        if not self.process or not self.stopping:return
        pid=int(self.process.processId())
        if pid<=0:
            self.process.started.connect(self.interrupt_runner)
            return
        try:
            # The runner owns cleanup of its separately grouped game process.
            os.kill(pid,signal.SIGINT)
        except ProcessLookupError:
            pass

    def closeEvent(self, event):
        if self.process is not None:
            self.status.setText('Stop the game before closing the launcher.')
            event.ignore()
            return
        try:
            model.save(self.preferences, self.values())
        except (OSError, ValueError, TypeError):
            pass
        event.accept()


try:
    from .launcher_shell import renovated
except ImportError:
    from launcher_shell import renovated

Launcher = renovated(Launcher)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Skylanders PC')
    # Its own identity, so desktops show the launcher icon rather than the game's.
    app.setDesktopFileName('org.skylanders.Launcher')
    icon=launcher_icon(ROOT)
    if icon.is_file():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon)))
    window = Launcher(ROOT)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
