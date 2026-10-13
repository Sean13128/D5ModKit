"""Telemetry of a skill recording (runtime `record`, d5lib/native/d5ctl.inc.c): per recorded game frame the camera
state block (0x600 bytes from 0x146A3AC00) and every drawn actor (light actors 0x14150ABD0, unit actors 0x1415A5BE0:
actor bytes 0x2a0-0x340 and its draw object's bytes 0x00-0x60).  For calibrating the skill editor's preview against
the game."""
import struct

CAM_VA, CAM_N = 0x146A3AC00, 0x600
ACT_LO, ACT_N, OBJ_N = 0x2A0, 0xA0, 0x60


def read(path):
    """-> {frame: dict(cam=bytes, actors=[dict(table, index, actor=bytes (from 0x2a0), obj=bytes)])}"""
    out = {}
    with open(path, "rb") as f:
        data = f.read()
    p = 0
    while p + 8 <= len(data):
        if data[p:p + 4] != b"TELE":
            break
        tick = struct.unpack_from("<i", data, p + 4)[0]
        p += 8
        cam = data[p:p + CAM_N]
        p += CAM_N
        n = struct.unpack_from("<H", data, p)[0]
        p += 2
        actors = []
        for _ in range(n):
            tb, ix = struct.unpack_from("<BH", data, p)
            p += 3
            actor = data[p:p + ACT_N]
            p += ACT_N
            obj = data[p:p + OBJ_N]
            p += OBJ_N
            actors.append(dict(table=tb, index=ix, actor=actor, obj=obj))
        out[tick] = dict(cam=cam, actors=actors)
    return out


PRB_SLOTS, PRB_SLOT_SIZE, PRB_MGR = 64, 0x358, 0x440
REC_SIZE = 0xd8


def read_probe(path):
    """probe.bin of a recording (runtime `probe FROM TO`) -> {frame: dict(slots=[64 x 0x358 bytes: effect slot i],
    mgr=draw manager bytes 0..0x440, keys=[u64 sort keys, sorted], order=[record index per draw position],
    recs=[n x 0xd8 bytes: queue 6's records, manager +0x30], recs2=[PRB1: +0x90; PRB2: the staged list +0x418])}
    -- the last frame drawn; in PRB2 n is a fixed window (the game clears the counts after drawing)"""
    out = {}
    with open(path, "rb") as f:
        data = f.read()
    p = 0
    while p + 8 <= len(data) and data[p:p + 4] in (b"PRB1", b"PRB2", b"PRB3", b"PRB4"):
        v3 = data[p:p + 4] in (b"PRB3", b"PRB4")
        v4 = data[p:p + 4] == b"PRB4"
        tick = struct.unpack_from("<i", data, p + 4)[0]
        p += 8
        slots = [data[p + i * PRB_SLOT_SIZE:p + (i + 1) * PRB_SLOT_SIZE] for i in range(PRB_SLOTS)]
        p += PRB_SLOTS * PRB_SLOT_SIZE
        mgr = data[p:p + PRB_MGR]
        p += PRB_MGR
        n = struct.unpack_from("<i", data, p)[0]
        p += 4
        keys = list(struct.unpack_from(f"<{n}Q", data, p))
        p += 8 * n
        order = list(struct.unpack_from(f"<{n}I", data, p))
        p += 4 * n
        recs = [data[p + i * REC_SIZE:p + (i + 1) * REC_SIZE] for i in range(n)]
        p += REC_SIZE * n
        recs2 = [data[p + i * REC_SIZE:p + (i + 1) * REC_SIZE] for i in range(n)]      # PRB2: the staged list
        p += REC_SIZE * n
        verts = []
        if v3:              # per record: 128 bytes at its +0x30 pointer, 192 at +0x38 (PRB4: + the 4x4 matrix at +0x70)
            sz = 384 if v4 else 320
            verts = [tuple(data[p + i * sz + a:p + i * sz + b] for a, b in ((0, 128), (128, 320), (320, sz)))
                     for i in range(n)]
            p += sz * n
        out[tick] = dict(slots=slots, mgr=mgr, keys=keys, order=order, recs=recs, recs2=recs2, verts=verts)
    return out


def cam_floats(cam):
    return struct.unpack_from(f"<{CAM_N // 4}f", cam)


def actor_field(a, off, fmt="<h"):
    """a field of an actor at its absolute offset (0x2a0..0x340)"""
    return struct.unpack_from(fmt, a["actor"], off - ACT_LO)[0]
