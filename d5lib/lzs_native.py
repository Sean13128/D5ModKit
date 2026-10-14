"""Native LZS codec (d5lib/native_tools/lzs.c -> platform library in d5lib/bin), ~100x faster than the Python one.

The DLL ships prebuilt in d5lib/bin; when it is missing (or older than its source) and Zig is installed
(pip install ziglang) it is compiled on first use.  available() is False when neither works -- callers then use
the pure-Python codec (d5lib.lzs / d5lib.lzs_compress), which produces the same kind of stream.
"""
import ctypes
import os
import struct
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "native_tools", "lzs.c")
LIB_NAME = "libd5lzs.dylib" if sys.platform == "darwin" else ("d5lzs.dll" if os.name == "nt" else "libd5lzs.so")
DLL = os.path.join(HERE, "bin", LIB_NAME)
_lib = None
_tried = False
_lock = threading.Lock()


def _build():
    os.makedirs(os.path.dirname(DLL), exist_ok=True)
    temporary = DLL + ".building"
    if os.name == "nt":
        cmd = [sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2", "-s"]
    else:
        compiler = shutil.which("clang") or shutil.which("cc")
        cmd = [compiler] if compiler else [sys.executable, "-m", "ziglang", "cc"]
        cmd += ["-dynamiclib" if sys.platform == "darwin" else "-shared", "-O2"]
        if sys.platform != "darwin":
            cmd += ["-fPIC"]
    cmd += ["-o", temporary, SOURCE]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and os.path.exists(temporary):
            os.replace(temporary, DLL)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    for junk in (os.path.splitext(DLL)[0] + ".pdb", os.path.join(os.path.dirname(DLL), "lzs.lib")):
        if os.path.exists(junk):
            os.remove(junk)
    return r.returncode == 0 and os.path.exists(DLL)


def _load():
    global _lib, _tried
    with _lock:
        if _tried:
            return _lib
        _tried = True
        try:
            stale = os.path.exists(SOURCE) and (not os.path.exists(DLL) or os.path.getmtime(DLL) < os.path.getmtime(SOURCE))
            if stale:
                try:
                    _build()
                except Exception:
                    pass
            if not os.path.exists(DLL):
                return None
            lib = ctypes.CDLL(DLL)
            lib.lzs_compress_body.restype = ctypes.c_int64
            lib.lzs_compress_body.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                                              ctypes.c_int]
            lib.lzs_decompress_body.restype = ctypes.c_int64
            lib.lzs_decompress_body.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                                                ctypes.c_int]
            lib.lzs_choose_marker.restype = ctypes.c_int
            lib.lzs_choose_marker.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
            if hasattr(lib, "yk_lz_decompress"):            # (a DLL older than its source has no YKCMP)
                lib.yk_lz_decompress.restype = ctypes.c_int64
                lib.yk_lz_decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p,
                                                 ctypes.c_size_t]
            _lib = lib
        except OSError:
            _lib = None
        return _lib


def available():
    return _load() is not None


def compress(data: bytes, tag: bytes = b"pac") -> bytes:
    """complete .lzs file (16-byte header + stream), like lzs_compress.compress"""
    lib = _load()
    data = bytes(data)
    n = len(data)
    marker = lib.lzs_choose_marker(data, n) if n else 0
    cap = n * 2 + 64
    buf = ctypes.create_string_buffer(cap)
    m = lib.lzs_compress_body(data, n, buf, cap, marker)
    if m < 0:
        raise RuntimeError(f"native LZS compression failed ({m})")
    ext = bytes(tag[:4]).rstrip(b"\0")[:3].ljust(4, b"\0")
    return ext + struct.pack("<III", n, m + 12, marker) + buf.raw[:m]


def yk_lz(src: bytes, pos: int, size: int):
    """Yukes LZ (d5lib.ykcmp) natively -> bytes, or None (no DLL, or a stream the Python decoder must judge)"""
    lib = _load()
    if lib is None or not hasattr(lib, "yk_lz_decompress"):
        return None
    src = bytes(src)
    buf = ctypes.create_string_buffer(max(1, size))
    m = lib.yk_lz_decompress(src, len(src), pos, buf, size)
    return buf.raw[:size] if m == size else None


def decompress(data: bytes) -> bytes:
    lib = _load()
    ext, usize, csize, marker = struct.unpack_from("<4sIII", data, 0)
    body = bytes(data[16:])
    buf = ctypes.create_string_buffer(max(1, usize))
    m = lib.lzs_decompress_body(body, len(body), buf, usize, marker & 0xFF)
    if m != usize:
        raise ValueError(f"LZS size mismatch {m} != {usize}")
    return buf.raw[:usize]
