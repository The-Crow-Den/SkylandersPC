#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the approved HTML/CSS menu directly as an optional desktop overlay."""
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


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--demo',type=Path,help='synthetic snapshot only; no runtime commands are executed')
    parser.add_argument('--screenshot',type=Path)
    args=parser.parse_args(argv)
    directory=private_directory(args.directory)
    from PyQt6.QtCore import QObject,QTimer,QUrl,Qt,pyqtSignal,pyqtSlot
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication,QFileDialog
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineCore import QWebEnginePage,QWebEngineSettings,QWebEngineUrlRequestInterceptor
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app=QApplication(sys.argv[:1]);app.setApplicationName('Trap Team PC menu')
    commands=Commands(directory);portraits=Portraits(ROOT)
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
            path,_=QFileDialog.getOpenFileName(view,'Import a Skylander or item',str(Path.home()),'Skylander figures (*.sky *.bin)')
            if path and '\n' not in path and not args.demo:commands.write(f'import {player}\n{path}')
    view=QWebEngineView();view.setWindowTitle('Trap Team · PC overlay')
    view.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground);view.setStyleSheet('background:transparent;')
    page=Page(view);view.setPage(page);page.setBackgroundColor(QColor(0,0,0,0))
    interceptor=LocalOnly(page);page.profile().setUrlRequestInterceptor(interceptor)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,False)
    channel=QWebChannel(page);portal=Portal();channel.registerObject('portal',portal);page.setWebChannel(channel)
    state_path=args.demo or directory/'state.json';last_signature=None;was_visible=False;last_pid=None
    def heartbeat():
        if portal.loaded:
            try:(directory/'heartbeat').write_text(str(os.getpid()))
            except OSError:app.quit()
    def poll():
        nonlocal last_signature,was_visible,last_pid
        if not portal.loaded:return
        try:
            signature=(state_path.stat().st_mtime_ns,state_path.stat().st_size)
            if signature==last_signature:return
            state=read_snapshot(state_path);last_signature=signature
        except (OSError,ValueError,TypeError):return
        last_pid=state.get('pid')
        visible=state['visible']
        if visible:
            x,y,width,height=state['geometry'];view.setGeometry(x,y,width,height);view.setZoomFactor(max(0.75,min(height/1080,3.0)))
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            if not was_visible:view.show();view.raise_();view.activateWindow();view.setFocus()
        elif was_visible:
            view.hide();page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        portal.state=json.dumps(state,separators=(',',':'),ensure_ascii=False);portal.changed.emit(portal.state);was_visible=visible
    heartbeat_timer=QTimer();heartbeat_timer.timeout.connect(heartbeat);heartbeat_timer.start(1000)
    timer=QTimer();timer.timeout.connect(poll);timer.start(80)
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
    for name in ('ready','heartbeat'):
        try:(directory/name).unlink()
        except FileNotFoundError:pass
    return result

if __name__=='__main__':raise SystemExit(main())
