"""Read local Unity RPG idle sprite clocks without importing game code or effects."""

import hashlib
import json
import math
import re
import struct
from pathlib import Path


def streamed_frames(words, curve_count):
    if len(words) > 1024 * 1024 or not 0 <= curve_count <= 65536:
        raise ValueError("Streamed clip exceeds bounds")
    raw = struct.pack("<" + str(len(words)) + "I", *words)
    offset, previous, frames = 0, -math.inf, []
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise ValueError("Truncated stream header")
        time, count = struct.unpack_from("<fI", raw, offset)
        offset += 8
        if (
            math.isnan(time)
            or time < previous
            or count > 65536
            or offset + count * 20 > len(raw)
        ):
            raise ValueError("Invalid stream bounds")
        keys = {}
        for _ in range(count):
            index, *coefficients = struct.unpack_from("<I4f", raw, offset)
            offset += 20
            if index >= curve_count:
                # Some Unity versions have one zero pre-roll initializer outside the bank.
                if time < -1e30 and all(v == 0 for v in coefficients):
                    continue
                raise ValueError("Active streamed curve outside bank")
            if index in keys or not all(math.isfinite(v) for v in coefficients):
                raise ValueError("Invalid streamed curve")
            keys[index] = coefficients
        if math.isinf(time) and (time < 0 or keys or offset != len(raw)):
            raise ValueError("Invalid terminal stream sentinel")
        frames.append((time, keys))
        previous = time
    return frames


def sprite_timelines(clip):
    bindings = clip["m_ClipBindingConstant"]["genericBindings"]
    if any(
        b["typeID"] == 4 and not b["isPPtrCurve"] and b["attribute"] not in (1, 2, 3, 4)
        for b in bindings
    ):
        raise ValueError("Unknown transform binding width")
    widths = [
        4
        if b["typeID"] == 4 and not b["isPPtrCurve"] and b["attribute"] == 2
        else 3
        if b["typeID"] == 4 and not b["isPPtrCurve"]
        else 1
        for b in bindings
    ]
    muscle = clip["m_MuscleClip"]
    bank = muscle["m_Clip"]["data"]
    stream, dense, constants = (
        bank["m_StreamedClip"],
        bank["m_DenseClip"],
        bank["m_ConstantClip"]["data"],
    )
    expected = sum(widths) - dense["m_CurveCount"] - len(constants)
    declared = stream["curveCount"]
    pointer_count = sum(bool(b["isPPtrCurve"]) for b in bindings)
    if expected not in (declared, declared + pointer_count):
        raise ValueError("Unexplained Unity curve bank discrepancy")
    # Newer files omit PPtr bindings from the declared streamed count. The complete
    # binding/dense/constant banks establish the actual count; never use max-index guesses.
    frames = streamed_frames(stream["data"], expected)
    pointers = clip["m_ClipBindingConstant"]["pptrCurveMapping"]
    offset, timelines = 0, []
    for binding, width in zip(bindings, widths):
        if binding["isPPtrCurve"]:
            if offset < expected:
                values = [
                    (max(muscle["m_StartTime"], t), keys[offset][-1])
                    for t, keys in frames
                    if offset in keys and t <= muscle["m_StopTime"]
                ]
            elif offset >= expected + dense["m_CurveCount"]:
                index = offset - expected - dense["m_CurveCount"]
                if index >= len(constants):
                    raise ValueError("Constant pointer outside bank")
                values = [(muscle["m_StartTime"], constants[index])]
            else:
                raise ValueError("Dense sprite curves are unsupported")
            switches = []
            for time, value in values:
                if (
                    not math.isfinite(value)
                    or value != int(value)
                    or not 0 <= value < len(pointers)
                ):
                    raise ValueError("Invalid sprite pointer index")
                pointer = pointers[int(value)]
                item = {
                    "time": time,
                    "file_id": pointer["m_FileID"],
                    "path_id": str(pointer["m_PathID"]),
                }
                if switches and switches[-1]["time"] == time:
                    switches[-1] = item
                elif not switches or (
                    switches[-1]["file_id"],
                    switches[-1]["path_id"],
                ) != (item["file_id"], item["path_id"]):
                    switches.append(item)
            timelines.append(
                {"curve_index": offset, "binding": binding, "switches": switches}
            )
        offset += width
    return timelines


def export_unit(uid, roots, destination):
    """Export named own-atlas sprites and exact idle clocks for one local RPG unit.

    Optional UnityPy is imported only here. The returned paths are relative to
    destination, making the result portable. Original clip dictionaries/hashes
    and unresolved optional effect references remain explicit evidence.
    """
    import UnityPy

    uid = int(uid)
    if uid <= 0:
        raise ValueError("Unit ID must be positive")
    roots = [Path(p) for p in roots]
    root = next(
        (
            p
            for p in roots
            if (p / f"prefabs/characters/{uid}").is_file()
            and all(
                (p / f"atlas/chara/battle/wait_{v}/{v}{uid}").is_file()
                for v in ("front", "back")
            )
        ),
        None,
    )
    if root is None:
        raise FileNotFoundError(f"No complete RPG idle source for unit {uid}")
    destination = Path(destination)
    folder = destination / str(uid)
    folder.mkdir(parents=True, exist_ok=False)
    sources, serialized = [], {}
    cache = {}

    def bundle(path):
        if path in cache:
            return cache[path]
        raw = path.read_bytes()
        env = UnityPy.load(raw)
        info = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "serialized_files": {},
            "dependencies": [],
        }
        for archive in env.files.values():
            for name, sf in getattr(archive, "files", {}).items():
                if hasattr(sf, "externals"):
                    info["serialized_files"][name] = {
                        "sprites": {
                            str(o.path_id): o.parse_as_dict()["m_Name"]
                            for o in sf.objects.values()
                            if o.type.name == "Sprite"
                        },
                        "externals": [x.path.rsplit("/", 1)[-1] for x in sf.externals],
                    }
        for obj in env.objects:
            if obj.type.name == "AssetBundle":
                info["dependencies"] = obj.parse_as_dict().get("m_Dependencies", [])
        if path.read_bytes() != raw:
            raise ValueError("RPG source changed while being read")
        sources.append(info)
        serialized.update(info["serialized_files"])
        cache[path] = (env, info)
        return env, info

    env, prefab = bundle(root / f"prefabs/characters/{uid}")
    owner = next(iter(prefab["serialized_files"]))
    dependencies = set(prefab["dependencies"]) | {
        f"atlas/chara/battle/wait_{v}/{v}{uid}" for v in ("front", "back")
    }
    for dependency in sorted(dependencies):
        path = (root / dependency).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Unity dependency escapes the RPG source root")
        if path.is_file():
            bundle(path)
    result = {"uid": uid, "sources": sources, "facings": {}}
    body = {"name": f"RPG unit {uid}", "facings": {}}
    for view in ("front", "back"):
        atlas, _ = bundle(root / f"atlas/chara/battle/wait_{view}/{view}{uid}")
        sprites = {}
        for obj in atlas.objects:
            if obj.type.name != "Sprite":
                continue
            data = obj.parse_as_dict()
            name = data["m_Name"]
            if not re.fullmatch("[A-Za-z0-9_]+", name):
                raise ValueError("Unsafe Unity sprite name")
            image = obj.parse_as_object().image.convert("RGBA")
            png = folder / f"{view}_{name}.png"
            image.save(png)
            sprites[name] = {
                "png": str(png.relative_to(destination)),
                "size": list(image.size),
                "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            }
        clips = [
            o.parse_as_dict()
            for o in env.objects
            if o.type.name == "AnimationClip"
            and o.parse_as_dict()["m_Name"] == f"{view}_wait"
        ]
        if len(clips) != 1:
            raise ValueError(f"Expected one {view}_wait clip for {uid}")
        clip = clips[0]
        metadata = folder / f"{view}_wait_clip.json"
        metadata.write_text(json.dumps(clip, indent=2), encoding="utf-8")
        timelines = sprite_timelines(clip)
        externals = serialized[owner]["externals"]
        for timeline in timelines:
            for switch in timeline["switches"]:
                fid = switch["file_id"]
                target = (
                    owner
                    if fid == 0
                    else externals[fid - 1]
                    if 1 <= fid <= len(externals)
                    else None
                )
                switch["sprite_name"] = (
                    serialized.get(target, {}).get("sprites", {}).get(switch["path_id"])
                )
                switch["resolved"] = switch["sprite_name"] is not None
        candidates = []
        for timeline in timelines:
            available = [
                sprites[n]
                for n in {s["sprite_name"] for s in timeline["switches"]}
                if n in sprites
            ]
            area = (
                sum(s["size"][0] * s["size"][1] for s in available) / len(available)
                if available
                else 0
            )
            candidates.append((area, len(available), timeline))
        area, count, selected = max(candidates, key=lambda item: item[:2])
        if not count or any(
            s["sprite_name"] not in sprites for s in selected["switches"]
        ):
            raise ValueError(f"Incomplete main body timeline for {uid}/{view}")
        muscle = clip["m_MuscleClip"]
        start, stop = muscle["m_StartTime"], muscle["m_StopTime"]
        if not muscle["m_LoopTime"]:
            raise ValueError("RPG idle clip must loop")
        body["facings"][view] = {
            "duration_ticks60": round((stop - start) * 60),
            "switches": [
                {
                    "ticks60": round((s["time"] - start) * 60),
                    "seconds": s["time"],
                    "sprite_name": s["sprite_name"],
                    "png": sprites[s["sprite_name"]]["png"],
                }
                for s in selected["switches"]
            ],
        }
        result["facings"][view] = {
            "sprites": sprites,
            "timelines": timelines,
            "metadata": str(metadata.relative_to(destination)),
            "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
            "selected_body_curve": selected["curve_index"],
            "body_mean_area": area,
        }
    return body, result
