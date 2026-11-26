"""Regression test for the Unicorn CTR_EL0 SIGILL on Darwin/ARM64.

unicorn 2.1.4 falls back to ``mrs Xt, ctr_el0`` when its
``sysctlbyname("hw.cachelinesize")`` probe fails, and Darwin raises SIGILL for
user-space CTR_EL0 reads.  Any sandboxed runner that denies sysctl-read (the
state most agent lanes run in) therefore kills the process inside
``Uc().mem_map()`` before a test body runs, with exit status 132.

These tests reproduce that deterministically with ``sandbox-exec`` and prove
that tests/unicorn_darwin_shim.py fixes it, without touching the shared venv.
"""
import os
import platform
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = "/usr/bin/sandbox-exec"
DENY_SYSCTL = ('(version 1)(allow default)'
               '(deny sysctl-read (sysctl-name "hw.cachelinesize"))')

# The child ends through exit_on_fault, so the trap is still shown (exit 132) but the process is not
# killed by the signal: no crash report, no 'Python quit unexpectedly' dialog for Sean (SIGILL2, 2026-11-08).
UNSHIMMED_PROBE = """
import sys
sys.path.insert(0, %r)
import unicorn_darwin_shim
assert unicorn_darwin_shim.exit_on_fault(132)
import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0x140000000, 0x1000000)
print("mapped")
""" % HERE

MINIMAL_PROBE = """
import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0x140000000, 0x1000000)
print("mapped")
"""

SHIMMED_PROBE = """
import sys
sys.path.insert(0, %r)
import unicorn_darwin_shim
assert unicorn_darwin_shim.install()
import unicorn
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0x140000000, 0x1000000)
print("mapped emulated=%%d" %% unicorn_darwin_shim.emulated())
""" % HERE

needs_sandbox_exec = pytest.mark.skipif(
    not (sys.platform == "darwin" and platform.machine() == "arm64"
         and os.path.exists(SANDBOX)),
    reason="needs macOS/arm64 with sandbox-exec to deny the sysctl probe",
)


def _run(code, sandboxed, shim_env="on"):
    argv = [sys.executable, "-c", code]
    if sandboxed:
        argv = [SANDBOX, "-p", DENY_SYSCTL] + argv
    env = dict(os.environ, UNICORN_CTR_SHIM=shim_env)   # "off": a site-wide .pth shim (auto()) must stand aside
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, env=env)


@needs_sandbox_exec
def test_sysctl_denial_reproduces_the_sigill():
    """The bug is real and still reachable: exit 132 == SIGILL (reported by exit_on_fault, not by a crash)."""
    proc = _run(UNSHIMMED_PROBE, sandboxed=True, shim_env="off")
    if proc.returncode == 0:
        pytest.skip("this host does not reach the CTR_EL0 fallback")
    assert proc.returncode == 132, "expected exit 132 from exit_on_fault, got %r" % (proc.returncode,)
    assert "mapped" not in proc.stdout


def test_auto_respects_the_off_switch(monkeypatch):
    import unicorn_darwin_shim
    monkeypatch.setenv("UNICORN_CTR_SHIM", "off")
    assert unicorn_darwin_shim.auto() is False
    monkeypatch.setenv("UNICORN_CTR_SHIM", "on")
    assert unicorn_darwin_shim.auto() is (sys.platform == "darwin" and platform.machine() == "arm64")


@needs_sandbox_exec
def test_shim_survives_the_sysctl_denial():
    proc = _run(SHIMMED_PROBE, sandboxed=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "mapped" in proc.stdout


def _sysctl_readable_here():
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        value = ctypes.c_uint32()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        return libc.sysctlbyname(b"hw.cachelinesize", ctypes.byref(value),
                                 ctypes.byref(size), None, 0) == 0
    except Exception:
        return False


@needs_sandbox_exec
def test_shim_is_harmless_on_a_healthy_host():
    """On a host where the sysctl works, the shim must never engage."""
    if not _sysctl_readable_here():
        pytest.skip("this runner already denies the sysctl probe")
    proc = _run(MINIMAL_PROBE, sandboxed=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    import unicorn_darwin_shim
    assert unicorn_darwin_shim.emulated() == 0
