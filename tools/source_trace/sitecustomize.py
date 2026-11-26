import os, sys
_d = os.environ.get("TRACE_DIR")
if _d:
    _f = open(os.path.join(_d, f"{os.getpid()}.log"), "a", buffering=1)
    def _h(ev, a):
        try:
            if ev == "open":
                p = a[0]; m = a[1] or "r"
                if isinstance(p, int): return
                _f.write(f"open\t{m}\t{os.fsdecode(p)}\n")
            elif ev in ("os.listdir", "os.scandir"):
                if a[0] is not None and not isinstance(a[0], int): _f.write(f"list\t-\t{os.fsdecode(a[0])}\n")
            elif ev == "subprocess.Popen":
                _f.write(f"exec\t-\t{a[0]} {a[1]}\n")
            elif ev == "os.stat" if False else False: pass
        except Exception: pass
    sys.addaudithook(_h)
