"""d5mem -- read the running game's memory from outside (development tool; the game must not run elevated,
or this script must).  Addresses 0x14xxxxxxx are static VAs of the exe (ASLR is resolved).

    python tools/d5mem.py find "Welcome to the Item"      byte-string search (ascii / utf-8) in all memory
    python tools/d5mem.py findw "Welcome"                  UTF-16 search
    python tools/d5mem.py hex ADDR [N]                     hex dump
"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_VM_READ, PROCESS_QUERY_INFORMATION = 0x10, 0x400
MEM_COMMIT = 0x1000
PAGE_NOACCESS, PAGE_GUARD = 0x01, 0x100


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_uint64),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def game_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq disgaea5.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.strip('"').split('","')
        if parts and parts[0].lower() == "disgaea5.exe":
            return int(parts[1])
    raise RuntimeError("disgaea5.exe is not running")


class Mem:
    def __init__(self):
        self.pid = game_pid()
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.h:
            raise RuntimeError(f"OpenProcess failed ({ctypes.get_last_error()})")
        self.base = self._module_base()

    def _module_base(self):
        psapi = ctypes.WinDLL("psapi")
        mods = (ctypes.c_uint64 * 1024)()
        need = wt.DWORD()
        psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
        return mods[0]

    def rt(self, va):
        """static VA (0x14xxxxxxx) -> runtime address"""
        if 0x140000000 <= va < 0x150000000:
            return self.base + (va - 0x140000000)
        return va

    def st(self, a):
        if self.base <= a < self.base + 0x10000000:
            return a - self.base + 0x140000000
        return a

    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_uint64(self.rt(addr)), buf, n, ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    def regions(self, writable_only=False):
        a = 0x10000
        mbi = MBI()
        while a < 0x7FFFFFFF0000:
            if not k32.VirtualQueryEx(self.h, ctypes.c_uint64(a), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            nxt = mbi.BaseAddress + mbi.RegionSize
            if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                if not writable_only or (mbi.Protect & 0xCC):
                    yield mbi.BaseAddress, mbi.RegionSize
            a = nxt

    def find(self, pat, limit=50, writable_only=False):
        out = []
        for base, size in self.regions(writable_only):
            off = 0
            while off < size:
                n = min(size - off, 64 << 20)
                data = self.read(base + off, n)
                if data:
                    i = data.find(pat)
                    while i >= 0:
                        out.append(base + off + i)
                        if len(out) >= limit:
                            return out
                        i = data.find(pat, i + 1)
                off += n
        return out


def main(argv):
    m = Mem()
    if argv[0] in ("find", "findw"):
        pat = argv[1].encode("utf-16-le" if argv[0] == "findw" else "utf-8")
        for a in m.find(pat):
            ctx = m.read(a - 16, len(pat) + 48) or b""
            print(f"{m.st(a):x}  {ctx!r}")
    elif argv[0] == "hex":
        a = int(argv[1], 16)
        n = int(argv[2], 0) if len(argv) > 2 else 256
        d = m.read(a, n) or b""
        for i in range(0, len(d), 16):
            row = d[i:i + 16]
            print(f"{a + i:x}  {row.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in row)}")


if __name__ == "__main__":
    main(sys.argv[1:])
