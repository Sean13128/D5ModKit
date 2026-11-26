"""WRITEWATCH1: read the runtime's software write-watch records ("[wwatch] ..." lines in d5auto.log).

The `watch` command (d5lib/native/d5wwatch.inc.c) protects the page(s) of a range and logs each write that changes it:
    [wwatch] change n=1 frame=.. tid=.. rip=14xxxxxxx addr=.. off=.. ins=<16 bytes> old=<hex> new=<hex>
    [wwatch] regs n=1 rax=.. ... rflags=..
    [wwatch] stack n=1 14xxxxxxx 14xxxxxxx ...        (unwound with the exe's .pdata; module+offset outside the exe)
    [wwatch] raw n=1 rsp=.. q0 q1 ... q63             (the top stack qwords)
plus `near` records (a fault within 64 bytes below / inside the range, logged at the fault), `spinchange` (spin mode),
`armed`, `off` and `selftest` lines.  records(text) groups them by n.
"""
from __future__ import annotations

import re

LINE = re.compile(r"\[wwatch\] (\w+)(.*)$")
KV = re.compile(r"(\w+)=(\S+)")


def parse_line(line: str):
    """one '[wwatch]' line -> (kind, dict) or None; stack/raw lines keep their word lists"""
    m = LINE.search(line)
    if not m:
        return None
    kind, rest = m.group(1), m.group(2)
    d = dict(KV.findall(rest))
    if kind in ("stack", "raw"):
        d["words"] = [w for w in rest.split() if "=" not in w]
    return kind, d


def records(text: str) -> list[dict]:
    """the change / near / spinchange records with their regs, stack and raw lines, in log order"""
    out: dict[str, dict] = {}
    for line in text.splitlines():
        p = parse_line(line)
        if not p:
            continue
        kind, d = p
        n = d.get("n")
        if kind in ("change", "near", "spinchange"):
            out[n] = {"kind": kind, **{k: v for k, v in d.items() if k != "n"}}
        elif kind in ("regs", "stack", "raw") and n in out:
            if kind == "regs":
                out[n]["regs"] = {k: int(v, 16) for k, v in d.items() if k != "n"}
            elif kind == "stack":
                out[n]["stack"] = d["words"]
            else:
                out[n]["rsp"] = int(d["rsp"], 16)
                out[n]["raw"] = [int(w, 16) for w in d["words"]]
    return list(out.values())
