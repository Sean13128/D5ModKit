"""The kit keeps running when something goes wrong in it.

PyQt6 ends the program at once (qFatal) when Python code that Qt calls -- a click, a timer, an event filter, a paint
event -- raises an error and no sys.excepthook of our own is set.  The kit runs under pythonw, which shows nothing,
so the whole kit just vanished (1.5: closing a dialog with a searchable drop-down did that).  install() sets one:
the error is written to state/crash_log.txt and shown in the kit's log, and the kit goes on.

A crash inside Qt or another library itself can't be caught.  Then faulthandler writes where Python was to
state/faulthandler.log, and Qt's own fatal messages go to the crash log, so the next one can be found."""
import faulthandler
import os
import sys
import time
import traceback

MAX_LOG = 512 * 1024
_st = {"log": None, "sink": None, "seen": {}, "fh": None, "qt": False}


def _trim(path):
    """keep a log file small: past MAX_LOG only its newer half stays"""
    try:
        if os.path.getsize(path) > MAX_LOG:
            with open(path, "rb") as f:
                f.seek(-MAX_LOG // 2, os.SEEK_END)
                tail = f.read()
            with open(path, "wb") as f:
                f.write(tail)
    except OSError:
        pass


def _version():
    try:
        from d5lib.version import VERSION
        return VERSION
    except Exception:
        return "?"


def _write(text):
    if _st["log"]:
        try:
            with open(_st["log"], "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
    err = sys.__stderr__                              # (None under pythonw)
    if err is not None:
        try:
            err.write(text)
            err.flush()
        except Exception:
            pass


def excepthook(t, v, tb):
    text = "".join(traceback.format_exception(t, v, tb))
    n = _st["seen"][text] = _st["seen"].get(text, 0) + 1
    if n > 3:                                         # the same error over and over (a timer): written 3 times
        return
    _write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  D5 Mod Kit {_version()}  (the kit kept running)\n{text}\n")
    if n == 1 and _st["sink"] is not None:
        last = (traceback.format_exception_only(t, v) or ["error"])[-1].strip()
        try:                                          # (later: the error may come while a widget is being deleted)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: _tell(last))
        except Exception:
            pass


def _tell(last):
    sink = _st["sink"]
    if sink is None:
        return
    try:
        sink(f"⚠ Something went wrong but the kit kept running: {last}\n"
             f"   Details are in state/crash_log.txt (please send that file if it keeps happening).")
    except Exception:
        pass


def _qt_message(mode, ctx, msg):
    from PyQt6.QtCore import QtMsgType
    if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
        _write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  Qt {mode.name}: {msg}\n")
    elif sys.__stderr__ is not None:
        try:
            sys.__stderr__.write(msg + "\n")
        except Exception:
            pass


def install(kit_dir):
    """call first thing (before QApplication)"""
    state = os.path.join(kit_dir, "state")
    try:
        os.makedirs(state, exist_ok=True)
    except OSError:
        return
    _st["log"] = os.path.join(state, "crash_log.txt")
    _trim(_st["log"])
    sys.excepthook = excepthook
    fh = os.path.join(state, "faulthandler.log")
    _trim(fh)
    try:
        f = open(fh, "a", encoding="utf-8")
        f.write(f"--- started {time.strftime('%Y-%m-%d %H:%M:%S')}  pid {os.getpid()}  D5 Mod Kit {_version()}\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        _st["fh"] = f                                 # (faulthandler needs the file open)
    except (OSError, RuntimeError, ValueError):
        pass
    try:
        from PyQt6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message)
        _st["qt"] = True
    except Exception:
        pass


def set_sink(fn):
    """fn(text): where the kit shows that something went wrong (its log)"""
    _st["sink"] = fn


def at_quit():
    """the kit closes: nothing of it is called any more while Qt and Python shut down"""
    _st["sink"] = None
    if _st["qt"]:
        try:
            from PyQt6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(None)
        except Exception:
            pass
        _st["qt"] = False
