#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the approved HTML/CSS menu into the game or an optional desktop overlay."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
try:
    from .overlay_protocol import Commands,Portraits,private_directory,read_snapshot
except ImportError:
    from overlay_protocol import Commands,Portraits,private_directory,read_snapshot
ROOT=Path(__file__).resolve().parents[1]


def menu_zoom(width,height):
    """Page zoom for a menu filling width x height logical pixels.

    The menu is designed for a 1600 x 1000 page and grows with larger windows
    (1.08 at 1080p, 1.6 at 2560 x 1600). It does not shrink below 1 while the
    window still holds a 1100 x 720 page, so a 1280 x 800 Steam Deck keeps
    full-size text; only smaller windows shrink it, and never below 0.5.
    """
    grow=min(height/1000,width/1600)
    fit=min(1.0,height/720,width/1100)
    return max(0.5,min(3.0,max(grow,fit)))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--demo',type=Path,help='synthetic snapshot only; no runtime commands are executed')
    parser.add_argument('--screenshot',type=Path)
    parser.add_argument('--embedded',action='store_true',help='paint the same menu into the game frame without a desktop window')
    args=parser.parse_args(argv)
    directory=private_directory(args.directory)
    from PyQt6.QtCore import QObject,QTimer,QUrl,Qt,QEvent,QPoint,QPointF,pyqtSignal,pyqtSlot
    from PyQt6.QtGui import QColor,QImage,QMouseEvent,QWheelEvent,QKeyEvent
    from PyQt6.QtWidgets import QApplication,QFileDialog
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineCore import QWebEnginePage,QWebEngineSettings,QWebEngineUrlRequestInterceptor
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app=QApplication(sys.argv[:1]);app.setApplicationName('Trap Team PC menu')
    commands=Commands(directory);portraits=Portraits(ROOT)
    frames=None
    if args.embedded:
        try:from .overlay_frames import Frames
        except ImportError:from overlay_frames import Frames
        frames=Frames(directory)
    class LocalOnly(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self,request):
            url=request.requestUrl()
            if url.scheme() not in ('file','qrc','data','about'):request.block(True)
            elif url.scheme()=='file':
                path=Path(url.toLocalFile()).resolve()
                if not path.is_relative_to(ROOT/'tools/pc_menu'):request.block(True)
    class Page(QWebEnginePage):
        def acceptNavigationRequest(self,url,kind,main_frame):
            return url.scheme()=='file' and Path(url.toLocalFile()).resolve()==ROOT/'tools/pc_menu/index.html'
        def javaScriptConsoleMessage(self,level,message,line,source):
            print(f'PC overlay: {message} ({line})',file=sys.stderr,flush=True)
    class Portal(QObject):
        changed=pyqtSignal(str)
        def __init__(self):super().__init__();self.state='{}';self.loaded=False
        @pyqtSlot()
        def ready(self):
            self.loaded=True;(directory/'ready').write_text(str(os.getpid()));heartbeat()
        @pyqtSlot(result=str)
        def snapshot(self):return self.state
        @pyqtSlot(int,result=str)
        def portrait(self,cell):return portraits.get(cell)
        @pyqtSlot(str)
        def command(self,text):
            if args.demo:
                print('Demo command:',text,flush=True);return
            try:commands.write(text)
            except (OSError,ValueError) as error:print('PC overlay command rejected:',error,file=sys.stderr)
        @pyqtSlot(int)
        def importFigure(self,player):
            if player not in (0,1):return
            if args.embedded:
                if not args.demo:commands.write(f'import-dialog {player}')
                return
            path,_=QFileDialog.getOpenFileName(view,'Import a Skylander or item',str(Path.home()),'Skylander figures (*.sky *.bin)')
            if path and '\n' not in path and not args.demo:commands.write(f'import {player}\n{path}')
    view=QWebEngineView();view.setWindowTitle('Trap Team · PC overlay')
    view.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground);view.setStyleSheet('background:transparent;')
    if args.embedded:view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    page=Page(view);view.setPage(page);page.setBackgroundColor(QColor(0,0,0,0))
    interceptor=LocalOnly(page);page.profile().setUrlRequestInterceptor(interceptor)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,False)
    channel=QWebChannel(page);portal=Portal();channel.registerObject('portal',portal);page.setWebChannel(channel)
    state_path=args.demo or directory/'state.json';last_signature=None;was_visible=False;last_pid=None
    last_event=0;buttons=Qt.MouseButton.NoButton;pointer=QPointF(0,0);last_pixels=None;frame_size=(1280,720)
    def release_pointer():
        nonlocal buttons
        target=view.focusProxy() or view
        for button in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton,Qt.MouseButton.MiddleButton):
            if buttons&button:
                buttons&=~button
                QApplication.sendEvent(target,QMouseEvent(QEvent.Type.MouseButtonRelease,pointer,pointer,button,buttons,Qt.KeyboardModifier.NoModifier))
        QApplication.sendEvent(target,QEvent(QEvent.Type.FocusOut))
    def desktop_events(state):
        nonlocal last_event,buttons,pointer
        target=view.focusProxy() or view
        geometry=state['geometry'];sx=view.width()/geometry[2];sy=view.height()/geometry[3]
        mapping={1:Qt.MouseButton.LeftButton,2:Qt.MouseButton.MiddleButton,3:Qt.MouseButton.RightButton}
        named={'Left':Qt.Key.Key_Left,'Right':Qt.Key.Key_Right,'Up':Qt.Key.Key_Up,'Down':Qt.Key.Key_Down,
               'Return':Qt.Key.Key_Return,'Keypad Enter':Qt.Key.Key_Enter,'Escape':Qt.Key.Key_Escape,
               'Backspace':Qt.Key.Key_Backspace,'Delete':Qt.Key.Key_Delete,'Tab':Qt.Key.Key_Tab,
               'Home':Qt.Key.Key_Home,'End':Qt.Key.Key_End,'PageUp':Qt.Key.Key_PageUp,'PageDown':Qt.Key.Key_PageDown}
        for item in state.get('events',[]):
            serial,kind,*values=item
            if serial<=last_event:continue
            last_event=serial
            if kind=='pad':
                if values[0]>0:page.runJavaScript(f'window.portalNavigate?.({values[0]})')
            elif kind in ('move','button'):
                x,y=values[-2:];pointer=QPointF(x*sx,y*sy)
                button=Qt.MouseButton.NoButton;event_type=QEvent.Type.MouseMove
                if kind=='button':
                    down,number=values[:2];button=mapping.get(number,Qt.MouseButton.NoButton)
                    buttons=(buttons|button) if down else (buttons&~button)
                    event_type=QEvent.Type.MouseButtonPress if down else QEvent.Type.MouseButtonRelease
                QApplication.sendEvent(target,QMouseEvent(event_type,pointer,pointer,button,buttons,Qt.KeyboardModifier.NoModifier))
            elif kind=='wheel':
                QApplication.sendEvent(target,QWheelEvent(pointer,pointer,QPoint(),QPoint(round(values[0]*120),round(values[1]*120)),buttons,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False))
            elif kind=='key':
                down,name,mod=values;modifiers=Qt.KeyboardModifier.NoModifier
                if mod&0x3:modifiers|=Qt.KeyboardModifier.ShiftModifier
                if mod&0xc0:modifiers|=Qt.KeyboardModifier.ControlModifier
                if mod&0x300:modifiers|=Qt.KeyboardModifier.AltModifier
                key=named.get(name,ord(name.upper()) if len(name.upper())==1 else 0)
                if key:QApplication.sendEvent(target,QKeyEvent(QEvent.Type.KeyPress if down else QEvent.Type.KeyRelease,key,modifiers))
            elif kind=='text':
                QApplication.sendEvent(target,QKeyEvent(QEvent.Type.KeyPress,0,Qt.KeyboardModifier.NoModifier,values[0]))
                QApplication.sendEvent(target,QKeyEvent(QEvent.Type.KeyRelease,0,Qt.KeyboardModifier.NoModifier,values[0]))
            elif kind=='blur':release_pointer()
            elif kind=='focus':QApplication.sendEvent(target,QEvent(QEvent.Type.FocusIn))
    def capture():
        nonlocal last_pixels
        if not frames or not portal.loaded or not was_visible:return
        rendered=view.grab().toImage().scaled(*frame_size).convertToFormat(QImage.Format.Format_RGBA8888)
        pixels=rendered.constBits().asstring(rendered.sizeInBytes())
        if pixels!=last_pixels:frames.write(rendered.width(),rendered.height(),pixels);last_pixels=pixels
    def heartbeat():
        if portal.loaded:
            try:(directory/'heartbeat').write_text(str(os.getpid()))
            except OSError:app.quit()
    def poll():
        nonlocal last_signature,was_visible,last_pid,buttons,last_event,last_pixels,frame_size
        if not portal.loaded:return
        try:
            signature=(state_path.stat().st_mtime_ns,state_path.stat().st_size)
            if signature==last_signature:return
            state=read_snapshot(state_path);last_signature=signature
        except (OSError,ValueError,TypeError):return
        last_pid=state.get('pid')
        visible=state['visible']
        if visible:
            # The game reports device pixels; Qt positions in logical pixels (e.g. 125% scaling
            # made the overlay 25% too large and pushed the portal panel off the screen).
            scale=(view.screen() or app.primaryScreen()).devicePixelRatio() or 1.0
            x,y,width,height=(round(value/scale) for value in state['geometry'])
            if args.embedded:
                factor=min(1,3840/state['geometry'][2],2160/state['geometry'][3])
                frame_size=(round(state['geometry'][2]*factor),round(state['geometry'][3]*factor))
                x=y=0;width=round(frame_size[0]/scale);height=round(frame_size[1]/scale)
            view.setGeometry(x,y,width,height);view.setZoomFactor(menu_zoom(width,height))
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            if not was_visible:
                buttons=Qt.MouseButton.NoButton;last_pixels=None;view.show()
                if not args.embedded:view.raise_();view.activateWindow()
                view.setFocus()
                if args.embedded:QApplication.sendEvent(view.focusProxy() or view,QEvent(QEvent.Type.FocusIn))
        elif was_visible:
            if args.embedded:release_pointer()
            view.hide();page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        state['embedded']=args.embedded
        portal.state=json.dumps(state,separators=(',',':'),ensure_ascii=False);portal.changed.emit(portal.state);was_visible=visible
        if args.embedded and visible:desktop_events(state)
    heartbeat_timer=QTimer();heartbeat_timer.timeout.connect(heartbeat);heartbeat_timer.start(1000)
    timer=QTimer();timer.timeout.connect(poll);timer.start(16 if args.embedded else 80)
    capture_timer=QTimer();capture_timer.timeout.connect(capture);capture_timer.start(33)
    def alive():
        if args.demo or not last_pid:return
        try:os.kill(int(last_pid),0)
        except (OSError,ValueError):app.quit()
    alive_timer=QTimer();alive_timer.timeout.connect(alive);alive_timer.start(1000)
    page.load(QUrl.fromLocalFile(str(ROOT/'tools/pc_menu/index.html')))
    if args.screenshot:
        def save():
            if not portal.loaded or not was_visible:QTimer.singleShot(200,save);return
            args.screenshot.parent.mkdir(parents=True,exist_ok=True)
            if not view.grab().save(str(args.screenshot)):print('Overlay screenshot failed',file=sys.stderr)
            else:print('Rendered HTML overlay:',args.screenshot,flush=True)
            app.quit()
        QTimer.singleShot(2500,save)
        QTimer.singleShot(20000,app.quit)
    result=app.exec()
    if frames:frames.close()
    for name in ('ready','heartbeat'):
        try:(directory/name).unlink()
        except FileNotFoundError:pass
    return result

if __name__=='__main__':raise SystemExit(main())
