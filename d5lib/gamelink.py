"""The kit's link to the running game: the runtime DLL's command pipe (d5lib/native/d5ctl.inc.c, [debug] remote=1 in
d5auto.ini -- the kit setting "game_link" turns it on at install).  Used by the skill editor's Game view to record a
skill frame by frame from the real game (`record`).

    link = GameLink(); link.record(12010041, folder, frames=400); ... link.status() ... link.stop()

The pipe takes one client at a time: every call opens it, sends one line and closes it again.
"""
import json
import os
import time

PIPE = r"\\.\pipe\d5auto_ctl"
SKILL_EVENT = 12000000          # a skill's wrapper event: SKILL_EVENT + magic.dat id


class LinkError(RuntimeError):
    pass


def available():
    """the game runs with the link switched on"""
    try:
        GameLink(timeout=0.3).send("ping")
        return True
    except LinkError:
        return False


class GameLink:
    def __init__(self, timeout=3.0):
        self.timeout = timeout

    def send(self, line):
        deadline = time.time() + self.timeout
        while True:
            try:
                h = open(PIPE, "r+b", buffering=0)
                break
            except OSError:
                if time.time() > deadline:
                    raise LinkError("The game isn't running with the kit's game link (start the game installed by the "
                                    "kit, with 'Let the kit record skills from the game' switched on)")
                time.sleep(0.1)
        try:
            h.write((line.strip() + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = h.read(1 << 16)
                if not chunk:
                    raise LinkError("the game closed the link")
                buf += chunk
        finally:
            h.close()
        text = buf.decode("utf-8", "replace").strip()
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}

    # ---------------------------------------------------------------- recording
    def record(self, event, folder, frames, every=1, scale=2):
        """arm a recording: when script `event` starts, save its first `frames` game frames as folder/fNNNNN.bmp"""
        os.makedirs(folder, exist_ok=True)
        r = self.send(f"record {int(event)} {int(every)} {int(scale)} {int(frames)} {os.path.abspath(folder)}")
        if "error" in r:
            raise LinkError(r["error"])
        if not r.get("ok"):
            raise LinkError("this version of the game runtime can't record skills: Install again with the kit")
        return r

    def probe(self, first=-1, last=-1):
        """recorded frames first..last also get a probe record (folder/probe.bin: effect slots, sorted draw queue 6;
        d5lib.telemetry.read_probe); -1 = off"""
        r = self.send("probe off" if first < 0 else f"probe {int(first)} {int(last)}")
        if not r.get("ok"):
            raise LinkError("this version of the game runtime can't probe: Install again with the kit")
        return r

    def status(self):
        """{'armed', 'on', 'frames', 'tick'}"""
        return self.send("record status")

    def stop(self):
        return self.send("record stop")
