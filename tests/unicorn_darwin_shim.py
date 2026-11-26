"""Emulate libunicorn's `mrs Xt, ctr_el0` fallback on Darwin/ARM64.

Why this exists (see Subprojects/Engine-Extensions/SIGILL-REPORT.md)
-------------------------------------------------------------------
unicorn 2.1.4 derives the host cache line size from
``sysctlbyname("hw.cachelinesize")``.  When that call fails (a sandboxed agent
that denies ``sysctl-read``, for example) it falls back to reading CTR_EL0 with
an inline ``mrs Xt, ctr_el0`` (src/qemu/util/cacheinfo.c, arch_cache_info).
Darwin traps user-space CTR_EL0 reads, so the fallback raises SIGILL and the
whole process dies -- inside ``uc_mem_map`` on the first ``Uc()`` mapping, i.e.
before any test code runs.

Darwin's own tooling (Chromium, QEMU) handles this by trapping the SIGILL,
skipping the faulting instruction and synthesising a CTR value.  This module
does the same from Python so the tests work with the shared, unmodified venv.

The ucontext layout is discovered at run time (Darwin's ``ucontext_t`` holds a
*pointer* to ``mcontext64`` and the offset moved between SDKs), so the handler
locates the saved PC by scanning the signal context for a slot that points at
the faulting ``mrs`` instruction inside the libunicorn image.

Enabled automatically for `darwin`/`arm64` via tests/conftest.py; harmless
elsewhere (``install()`` is a no-op).
"""
from __future__ import annotations

import ctypes
import os
import platform
import sys

_SIGILL = 4          # Darwin: SIGILL == 4 (not 6 as on Linux)
_SA_SIGINFO = 0x0040
_MRS_CTR_EL0 = 0xD53B0020   # mrs Xt, ctr_el0
_MRS_CTR_EL0_MASK = 0xFFFFFFE0
# CTR_EL0 with IminLine = DminLine = 5 -> 4 << 5 = 128-byte cache lines, the
# real value for Apple silicon.  Only the low nibbles are used by unicorn.
_CTR_VALUE = 0x00050005
_SCAN_SLOTS = 256           # 2 KB of signal context is plenty to find the PC
_MAX_EMULATIONS = 5000      # loop guard: one fault per Uc() is expected


class _Sigaction(ctypes.Structure):
    # Darwin: union { handler, sigaction } ; sigset_t ; int
    _fields_ = [("handler", ctypes.c_void_p),
                ("mask", ctypes.c_uint32),
                ("flags", ctypes.c_int)]


class _DlInfo(ctypes.Structure):
    _fields_ = [("dli_fname", ctypes.c_char_p),
                ("dli_fbase", ctypes.c_void_p),
                ("dli_sname", ctypes.c_char_p),
                ("dli_saddr", ctypes.c_void_p)]


_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

_state = {
    "installed": False,
    "pc_offset": None,      # byte offset of __pc inside the ucontext
    "emulated": 0,
}


def _read_u64(addr):
    return ctypes.c_uint64.from_address(addr).value


def _write_u64(addr, value):
    ctypes.c_uint64.from_address(addr).value = value


def _read_u32(addr):
    return ctypes.c_uint32.from_address(addr).value


def _libunicorn_range():
    """[base, base + size) of the loaded libunicorn image, or None."""
    try:
        import unicorn
        libdir = os.path.join(os.path.dirname(unicorn.__file__), "lib")
        for name in sorted(os.listdir(libdir)):
            if "unicorn" not in name:
                continue
            lib = ctypes.CDLL(os.path.join(libdir, name))
            libc = ctypes.CDLL(None)
            libc.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DlInfo)]
            info = _DlInfo()
            if not libc.dladdr(ctypes.cast(lib.uc_version, ctypes.c_void_p),
                               ctypes.byref(info)) or not info.dli_fbase:
                continue
            base = int(info.dli_fbase)
            return base, base + 0x2000000   # generous upper bound
    except Exception:
        pass
    return None


def _debug(message):
    """Append a line to $UNICORN_CTR_SHIM_DEBUG (pytest captures fd 2)."""
    path = os.environ.get("UNICORN_CTR_SHIM_DEBUG")
    if not path:
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (message + "\n").encode())
        finally:
            os.close(fd)
    except Exception:
        pass


def _find_pc_offset(uap):
    """Byte offset of the saved PC in the signal context, or None."""
    bounds = _libunicorn_range()
    if bounds is None:
        return None
    lo, hi = bounds
    for slot in range(_SCAN_SLOTS):
        try:
            candidate = _read_u64(uap + slot * 8)
        except Exception:
            continue
        if not (lo <= candidate < hi) or candidate & 3:
            continue
        try:
            word = _read_u32(candidate)
        except Exception:
            continue
        if (word & _MRS_CTR_EL0_MASK) == _MRS_CTR_EL0:
            return slot * 8
    return None


def _on_sigill(sig, info, uap):        # runs in signal context: keep it tiny
    try:
        addr = int(uap or 0)
        if not addr:
            return
        off = _state["pc_offset"]
        if off is None:
            off = _find_pc_offset(addr)
            if off is None:
                _restore_default()     # cannot handle it: fail loudly, don't loop
                return
            _state["pc_offset"] = off
        pc = _read_u64(addr + off)
        word = _read_u32(pc)
        if (word & _MRS_CTR_EL0_MASK) != _MRS_CTR_EL0:
            _debug("unhandled SIGILL pc=%#x word=%#x" % (pc, word))
            _restore_default()
            return
        # Loop guard.  We advance the PC by 4 and the kernel resumes there, so
        # a healthy run never re-faults at the same instruction from the same
        # frame; every Uc() legitimately does (same stack, same instruction),
        # hence a budget rather than a repeat count.
        if _state["emulated"] >= _MAX_EMULATIONS:
            _debug("emulation budget exhausted at %#x" % pc)
            _restore_default()          # else the fault would repeat forever
            return
        rt = word & 0x1F
        _write_u64(addr + off - 256 + rt * 8, _CTR_VALUE)   # x[rt]
        _write_u64(addr + off, pc + 4)                      # skip the mrs
        _state["emulated"] += 1
        _debug("emulated CTR_EL0 at %#x" % pc)
    except BaseException:
        pass                            # never raise out of a signal handler


_CB = _CALLBACK(_on_sigill)             # module-level: keeps the trampoline alive


def _restore_default():
    """Put SIG_DFL back for SIGILL so an unhandled fault kills the process."""
    _state["installed"] = False
    try:
        libc = ctypes.CDLL(None)
        sa = _Sigaction()
        sa.handler = 0                  # SIG_DFL
        sa.mask = 0
        sa.flags = 0
        libc.sigaction(_SIGILL, ctypes.byref(sa), None)
    except Exception:
        pass


def install(force=False):
    """Install the CTR_EL0 shim.  Returns True if a handler is in place.

    pytest turns on faulthandler, which installs its own SIGILL handler and
    would replace ours; pass ``force=True`` (or call install() from
    ``pytest_sessionstart``) to re-take the signal after that happens.
    """
    if _state["installed"] and not force:
        return True
    if not (sys.platform == "darwin" and platform.machine() == "arm64"):
        return False
    libc = ctypes.CDLL(None)
    sa = _Sigaction()
    sa.handler = ctypes.cast(_CB, ctypes.c_void_p).value
    sa.mask = 0
    sa.flags = _SA_SIGINFO
    _state["installed"] = libc.sigaction(_SIGILL, ctypes.byref(sa), None) == 0
    return _state["installed"]


def emulated():
    """How many CTR_EL0 traps have been emulated (0 on a healthy host)."""
    return _state["emulated"]


def auto():
    """Start-up entry for a ``.pth`` line in a site-packages dir (SIGILL2, 2026-11-08): install the shim in EVERY
    interpreter of that environment, so a proof script run without ``PYTHONPATH=tests`` cannot die with a
    'Python quit unexpectedly' dialog.  ``UNICORN_CTR_SHIM=off`` in the environment keeps the shim out (the
    negative-control test uses it).  Never raises: a diagnostic shim must not break interpreter start-up."""
    try:
        if os.environ.get("UNICORN_CTR_SHIM", "on").lower() in ("off", "0", "no"):
            return False
        return install()
    except Exception:
        return False


_EXIT_CB = None


def exit_on_fault(code=132):
    """Install a SIGILL handler that ends the process with ``_exit(code)`` instead of letting the default action
    kill it: same exit status a shell reports for SIGILL (128 + 4), but no crash report and no macOS dialog.
    For tests that must show the trap is still reachable without alarming the user."""
    global _EXIT_CB
    if not (sys.platform == "darwin" and platform.machine() == "arm64"):
        return False
    libc = ctypes.CDLL(None)

    def _bail(sig, info, uap):
        os._exit(code)

    _EXIT_CB = _CALLBACK(_bail)
    sa = _Sigaction()
    sa.handler = ctypes.cast(_EXIT_CB, ctypes.c_void_p).value
    sa.mask = 0
    sa.flags = _SA_SIGINFO
    return libc.sigaction(_SIGILL, ctypes.byref(sa), None) == 0
