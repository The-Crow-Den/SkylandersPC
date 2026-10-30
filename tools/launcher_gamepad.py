# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller navigation for the launcher (Steam Deck Game Mode and desktop pads).

Input comes from the system SDL3 through ctypes, so no new Python dependency is needed;
without SDL3 the launcher simply stays mouse and keyboard only. The pure parts (button
mapping, stick hysteresis, repeat timing, spatial choice) have no Qt and are unit tested.
"""
import ctypes
import ctypes.util
import os
import struct

# SDL3 values (SDL_gamepad.h / SDL_events.h).
INIT_GAMEPAD = 0x2000
EVENT_AXIS, EVENT_DOWN, EVENT_UP, EVENT_ADDED, EVENT_REMOVED = 0x650, 0x651, 0x652, 0x653, 0x654
BUTTONS = {0: 'accept', 1: 'back', 2: 'x', 3: 'menu', 4: 'start', 6: 'start', 9: 'prev_page', 10: 'next_page',
           11: 'up', 12: 'down', 13: 'left', 14: 'right'}
DIRECTIONS = ('up', 'down', 'left', 'right')
PRESS, RELEASE = 20000, 12000          # stick hysteresis, same as the in-game PC menu
FIRST_REPEAT, REPEAT = 0.40, 0.11      # seconds


def button_action(button):
    """The launcher action for an SDL gamepad button, or None."""
    return BUTTONS.get(button)


class Stick:
    """Turns left-stick axis values into one held direction with hysteresis."""
    def __init__(self):
        self.held = [0, 0]  # x, y: -1, 0 or 1

    def update(self, axis, value):
        """Returns ('press', direction), ('release', direction) or None."""
        if axis not in (0, 1): return None
        current = self.held[axis]; new = current
        if not current and abs(value) > PRESS: new = 1 if value > 0 else -1
        elif current and abs(value) < RELEASE: new = 0
        if new == current: return None
        self.held[axis] = new
        name = lambda d: ('left', 'right')[d > 0] if axis == 0 else ('up', 'down')[d > 0]
        return ('press', name(new)) if new else ('release', name(current))


class Repeater:
    """Held-direction auto-repeat: fires on press, after FIRST_REPEAT, then every REPEAT."""
    def __init__(self):
        self.direction = None; self.due = 0.0

    def press(self, direction, now):
        self.direction = direction; self.due = now + FIRST_REPEAT
        return direction

    def release(self, direction):
        if self.direction == direction: self.direction = None

    def tick(self, now):
        if self.direction and now >= self.due:
            self.due = now + REPEAT
            return self.direction
        return None


def nearest(origin, candidates, direction):
    """Index of the best rectangle (x, y, w, h) from origin in direction, or None.

    Matches tools/pc_menu/menu.js: distance forward plus 2.5x the sideways gap between spans.
    Left/right skips controls far more vertical than horizontal, so a corner button does not
    steal a sideways press; up/down allows it, as settings rows put their switch far right."""
    ox, oy, ow, oh = origin; cx, cy = ox + ow / 2, oy + oh / 2
    gap = lambda a0, a1, b0, b1: max(0, max(a0, b0) - min(a1, b1))
    vertical = direction in ('up', 'down')
    best, score = None, float('inf')
    for index, (x, y, w, h) in enumerate(candidates):
        dx, dy = x + w / 2 - cx, y + h / 2 - cy
        forward = {'up': -dy, 'down': dy, 'left': -dx, 'right': dx}[direction]
        if forward < 4: continue
        if not vertical and abs(dy) > forward * 1.5 + 20: continue
        cross = gap(ox, ox + ow, x, x + w) if vertical else gap(oy, oy + oh, y, y + h)
        candidate = forward + cross * 2.5
        if candidate < score: best, score = index, candidate
    return best


def game_mode(environ=os.environ):
    """True inside Steam's Game Mode (gamescope), where the launcher is the only window."""
    return environ.get('SteamGamepadUI') == '1' or 'gamescope' in environ.get('XDG_CURRENT_DESKTOP', '').lower()


class SdlGamepads:
    """Minimal SDL3 gamepad event reader. poll() returns [('down'|'up'|'axis', a, b)]."""
    def __init__(self, library=None):
        name = library or ctypes.util.find_library('SDL3') or 'libSDL3.so.0'
        self.sdl = ctypes.CDLL(name)
        self.sdl.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self.sdl.SDL_Init.argtypes = [ctypes.c_uint32]; self.sdl.SDL_Init.restype = ctypes.c_bool
        self.sdl.SDL_PollEvent.argtypes = [ctypes.c_void_p]; self.sdl.SDL_PollEvent.restype = ctypes.c_bool
        self.sdl.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]; self.sdl.SDL_OpenGamepad.restype = ctypes.c_void_p
        self.sdl.SDL_GetError.restype = ctypes.c_char_p
        # The launcher has no SDL window, so SDL must deliver pad events without one.
        self.sdl.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1')
        if not self.sdl.SDL_Init(INIT_GAMEPAD):
            raise OSError('SDL gamepad init failed: ' + (self.sdl.SDL_GetError() or b'').decode(errors='replace'))
        self.event = ctypes.create_string_buffer(128); self.pads = {}

    def poll(self):
        out = []
        while self.sdl.SDL_PollEvent(self.event):
            raw = self.event.raw; kind, = struct.unpack_from('<I', raw, 0); which, = struct.unpack_from('<I', raw, 16)
            if kind == EVENT_ADDED:
                pad = self.sdl.SDL_OpenGamepad(which)
                if pad: self.pads[which] = pad
            elif kind == EVENT_REMOVED: self.pads.pop(which, None)
            elif kind in (EVENT_DOWN, EVENT_UP): out.append(('down' if kind == EVENT_DOWN else 'up', raw[20], 0))
            elif kind == EVENT_AXIS: out.append(('axis', raw[20], struct.unpack_from('<h', raw, 24)[0]))
        return out


try:
    from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
    from PyQt6.QtGui import QColor, QKeyEvent, QPainter, QPen
    from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication,
        QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QPushButton, QScrollArea,
        QTextEdit, QVBoxLayout, QWidget)
except ImportError:  # The pure helpers above stay importable for tests.
    QObject = object


if QObject is not object:
    class FocusRing(QWidget):
        def __init__(self, window):
            super().__init__(window); self.setObjectName('gamepadFocusRing')
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.hide()

        def paintEvent(self, event):
            p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor('#98dfef'), 3)); p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 10, 10); p.end()

    class OnScreenKeyboard(QDialog):
        """Controller text entry. X deletes, Y adds a space, Start or Done confirms."""
        ROWS = ('1234567890', 'qwertyuiop', "asdfghjkl'", 'zxcvbnm,.-', '/_:@~')

        def __init__(self, field):
            super().__init__(field.window()); self.field = field; self.shift = False
            self.setWindowTitle(field.accessibleName() or field.placeholderText() or 'Enter text')
            column = QVBoxLayout(self); column.setContentsMargins(20, 20, 20, 20); column.setSpacing(12)
            self.preview = QLineEdit(field.text()); self.preview.setEchoMode(field.echoMode())
            self.preview.setPlaceholderText(field.placeholderText()); self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if field.maxLength() < 32767: self.preview.setMaxLength(field.maxLength())
            column.addWidget(self.preview)
            grid = QGridLayout(); grid.setSpacing(6); column.addLayout(grid); self.keys = []
            for row, letters in enumerate(self.ROWS):
                for col, letter in enumerate(letters):
                    key = QPushButton(letter); key.setMinimumSize(64, 50); key.clicked.connect(lambda c=False, k=key: self.type(k.text()))
                    grid.addWidget(key, row, col); self.keys.append(key)
            actions = QHBoxLayout(); column.addLayout(actions)
            for text, callback in [('Shift', self.toggle_shift), ('Space', lambda: self.type(' ')),
                                   ('⌫ Delete', self.backspace), ('Clear', self.preview.clear), ('Cancel', self.reject), ('Done', self.accept)]:
                button = QPushButton(text); button.setMinimumHeight(50); button.clicked.connect(callback); actions.addWidget(button)
            hint = QLabel('A type · X delete · Y space · B cancel · Start done'); hint.setStyleSheet('color: #92929e;'); column.addWidget(hint)
            self.keys[10].setFocus()

        def type(self, text): self.preview.insert(text)
        def backspace(self): self.preview.backspace()

        def toggle_shift(self):
            self.shift = not self.shift
            for key in self.keys: key.setText(key.text().upper() if self.shift else key.text().lower())

        def gamepad_action(self, action):
            if action == 'x': self.backspace(); return True
            if action == 'menu': self.type(' '); return True
            if action == 'start': self.accept(); return True
            return False

        def accept(self):
            self.field.setText(self.preview.text()); super().accept()

    class GamepadNavigator(QObject):
        """Moves Qt focus with a controller and draws a ring around the focused control.

        Windows may define gamepad_back(), gamepad_page(delta) and gamepad_action(name), each
        returning True when handled; everything else uses generic widget behaviour."""
        def __init__(self, main, source=None):
            super().__init__(main); self.main = main; self.active = False
            self.source = source; self.stick = Stick(); self.repeat = Repeater(); self.rings = {}
            self.clock = QTimer(self); self.clock.setInterval(16); self.clock.timeout.connect(self.tick)
            if self.source is not None: self.clock.start()

        @classmethod
        def attach(cls, main):
            try: source = SdlGamepads()
            except OSError as error:
                getattr(main, 'log', None) and main.log.append(f'Controller navigation unavailable: {error}'); source = None
            return cls(main, source)

        def now(self):
            from time import monotonic
            return monotonic()

        def tick(self):
            for kind, a, b in self.source.poll():
                if kind == 'axis':
                    change = self.stick.update(a, b)
                    if change and change[0] == 'press': self.press(change[1])
                    elif change: self.repeat.release(change[1])
                    continue
                action = button_action(a)
                if action is None: continue
                if kind == 'down': self.press(action)
                elif action in DIRECTIONS: self.repeat.release(action)
            direction = self.repeat.tick(self.now())
            if direction: self.later(direction)
            # The mouse takes over again: drop the ring until the next pad press. Polled here
            # rather than by an application event filter, which can crash PyQt at exit.
            if self.active and QApplication.mouseButtons() != Qt.MouseButton.NoButton: self.active = False
            self.place_ring()

        def press(self, action):
            if action in DIRECTIONS: self.repeat.press(action, self.now())
            self.later(action)

        def later(self, action):
            # Actions may open modal dialogs or menus with their own event loop; running them
            # outside tick() keeps the polling timer alive inside those loops.
            QTimer.singleShot(0, lambda: self.perform(action))

        def target(self):
            # A running game owns the controller; the launcher only listens while it is the focus.
            if getattr(self.main, 'process', None) is not None: return None
            app = QApplication.instance()
            window = next((w for w in (app.activePopupWidget(), app.activeModalWidget(), app.activeWindow())
                           if w is not None and w.isVisible()), None)
            # After a dialog closes some platforms leave no active window although the app still
            # has the focus; Game Mode always shows the launcher. Fall back to the main window.
            if window is None and (game_mode() or app.applicationState() == Qt.ApplicationState.ApplicationActive) \
                    and self.main.isVisible() and not self.main.isMinimized(): window = self.main
            return window

        def perform(self, action):
            window = self.target()
            if window is None: return
            if not self.active: self.active = True
            if not window.isActiveWindow() and window.windowType() != Qt.WindowType.Popup: window.activateWindow()
            focus = window.focusWidget()  # its own focus child, also right while activation settles
            if focus is not None and (focus.window() is not window or not focus.isVisible()): focus = None
            if isinstance(window, QMenu) or window.windowType() == Qt.WindowType.Popup:  # menus and open combo lists
                return self.key(focus or window, {'up': Qt.Key.Key_Up, 'down': Qt.Key.Key_Down, 'left': Qt.Key.Key_Left, 'right': Qt.Key.Key_Right,
                    'accept': Qt.Key.Key_Return, 'back': Qt.Key.Key_Escape}.get(action))
            hook = getattr(window, 'gamepad_action', None)
            if hook and hook(action): return
            if action in DIRECTIONS: return self.move(window, focus, action)
            if action == 'accept': return self.activate(window, focus)
            if action == 'back':
                hook = getattr(window, 'gamepad_back', None)
                if hook and hook(): return
                if isinstance(window, QDialog): return self.key(window, Qt.Key.Key_Escape)
            if action in ('prev_page', 'next_page'):
                hook = getattr(window, 'gamepad_page', None)
                if hook: hook(-1 if action == 'prev_page' else 1)

        def key(self, widget, key):
            if widget is None or key is None: return
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(widget, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))

        def candidates(self, window):
            found = []
            for widget in window.findChildren(QWidget):
                if widget is window or widget.window() is not window or isinstance(widget, FocusRing): continue
                if not (widget.focusPolicy() & Qt.FocusPolicy.TabFocus) or not widget.isEnabled() or not widget.isVisible(): continue
                if widget.focusProxy() is not None or widget.width() < 4 or widget.height() < 4: continue
                # Children of a combo (its line edit) or a spin box are reached through the parent.
                if isinstance(widget.parent(), (QComboBox, QAbstractSpinBox)): continue
                if isinstance(widget, QTextEdit) and widget.isReadOnly() and not widget.toPlainText(): continue
                if isinstance(widget, QScrollArea): continue  # its rows are the targets
                found.append(widget)
            return found

        def rect(self, widget, window):
            top = widget.mapTo(window, QPoint(0, 0)); return (top.x(), top.y(), widget.width(), widget.height())

        def move(self, window, focus, direction):
            if focus is not None:
                vertical = direction in ('up', 'down')
                if isinstance(focus, QAbstractItemView) and vertical and focus.model() is not None:
                    row, count = focus.currentIndex().row(), focus.model().rowCount(focus.rootIndex())
                    if (direction == 'down' and row < count - 1) or (direction == 'up' and row > 0):
                        return self.key(focus, Qt.Key.Key_Down if direction == 'down' else Qt.Key.Key_Up)
                if isinstance(focus, QAbstractSlider) and not vertical:
                    return focus.triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd if direction == 'right' else QAbstractSlider.SliderAction.SliderPageStepSub)
                if isinstance(focus, QAbstractSpinBox) and not vertical:
                    return focus.stepBy(1 if direction == 'right' else -1)
                if isinstance(focus, QTextEdit) and vertical:
                    bar = focus.verticalScrollBar()
                    if (direction == 'down' and bar.value() < bar.maximum()) or (direction == 'up' and bar.value() > 0):
                        return bar.triggerAction(QAbstractSlider.SliderAction.SliderPageStepAdd if direction == 'down' else QAbstractSlider.SliderAction.SliderPageStepSub)
            options = self.candidates(window)
            if not options: return
            if focus is None or focus not in options:
                choice = min(options, key=lambda w: (self.rect(w, window)[1] // 40, self.rect(w, window)[0]))
            else:
                index = nearest(self.rect(focus, window), [self.rect(w, window) for w in options], direction)
                if index is None: return
                choice = options[index]
            self.focus(choice)

        def focus(self, widget):
            widget.setFocus(Qt.FocusReason.TabFocusReason)
            parent = widget.parent()
            while parent is not None:
                if isinstance(parent, QScrollArea) and not isinstance(widget, QAbstractItemView): parent.ensureWidgetVisible(widget, 20, 20)
                parent = parent.parent()
            if isinstance(widget, QAbstractItemView) and not widget.currentIndex().isValid() and widget.model() and widget.model().rowCount(widget.rootIndex()):
                widget.setCurrentIndex(widget.model().index(0, 0, widget.rootIndex()))
            self.place_ring()

        def activate(self, window, focus):
            if focus is None: return self.move(window, None, 'down')
            if isinstance(focus, QAbstractButton): return focus.animateClick()
            if isinstance(focus, QComboBox): return focus.showPopup()
            if isinstance(focus, QLineEdit) and not focus.isReadOnly():
                return OnScreenKeyboard(focus).exec()
            if isinstance(focus, QAbstractItemView):
                index = focus.currentIndex()
                if index.isValid():
                    if isinstance(focus, QListWidget): focus.itemDoubleClicked.emit(focus.item(index.row()))
                    focus.activated.emit(index)
                return
            self.key(focus, Qt.Key.Key_Space)

        def place_ring(self):
            window = self.target()
            focus = window.focusWidget() if window is not None else None
            for window, ring in list(self.rings.items()):
                try:
                    if focus is None or focus.window() is not window or not self.active: ring.hide()
                except RuntimeError: self.rings.pop(window, None)
            if focus is None or not self.active or isinstance(focus, QMenu): return
            window = focus.window()
            if window.windowType() == Qt.WindowType.Popup: return
            ring = self.rings.get(window)
            if ring is None: ring = self.rings[window] = FocusRing(window)
            x, y, w, h = self.rect(focus, window)
            area = QRect(x - 4, y - 4, w + 8, h + 8)
            if ring.geometry() != area: ring.setGeometry(area)
            if not ring.isVisible(): ring.show()
            ring.raise_()
