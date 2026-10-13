"""The editor's side of the GPU preview: StageRenderer keeps the old SceneRenderer interface (who casts, facing,
picking boxes, actor / slot places) on top of d5lib.stage (the simulation) and glrender (the drawing)."""
import numpy as np

import os

from d5lib import battlemap, choreo
from d5lib import stage as stg
from . import glrender


class _Sprites:
    """the part of render.SpriteCache the editor still asks for (animation lists of a sprite)"""

    def __init__(self, assets):
        self.assets = assets

    def file(self, num):
        return self.assets.sprite(num)

    def anim_for(self, num, motion, back=False):
        return self.assets.anim_for(num, motion, back)

    def frame(self, *a, **k):
        return None


class StageRenderer:
    def __init__(self, fs, mods, owner_read=None, members=None):
        self.assets = glrender.Assets(fs, mods, owner_read, members)
        self.gl = glrender.GLRenderer(self.assets)
        self.gl.shadow_sizes = self._shadow_sizes(fs, mods)
        self.spr = _Sprites(self.assets)
        self.caster_sprite, self.target_sprite = None, None
        self.caster_palette, self.target_palette = 0, 0
        self.weapon = None
        self.facing = 0
        self.distance = 1.0
        self.view_yaw = stg.DEFAULT_YAW
        self.event_sheets = {}
        self.class_sprites = {}
        self.highlight = None
        self.highlights = []
        self.particles = None
        self.show_grid = True
        self.sim = None
        self._sim_key = None
        self.data_dir = os.path.join(getattr(fs, "game_dir", "") or "", "Data")
        self.map_id = None               # battle map around the stage (None: a flat floor with a grid)
        self.panel = None                # the caster's panel on it (None: the map's own choice)
        self.bmap = None
        self.area = None                 # d5lib.skillarea.Area of the skill (None: one target at `distance`)
        self.enemies = None              # hit panels (x sideways, y forward from the caster) with an enemy
        self.show_area = True

    @staticmethod
    def _shadow_sizes(fs, mods):
        """{sprite: char.dat size_radius} (the units' shadow sizes; mods' changes included)"""
        try:
            from d5lib import database, dbpatch
            t = database.load_table("char.dat", fs.read(f"{dbpatch.DB_ARCHIVE}/char.dat"))
            for m in mods or ():
                patch = m.load_patch("db", "char.dat.json")
                if patch:
                    dbpatch.apply_patch(t, patch)
            out = {}
            for r in t.rows:
                s, size = r.get("sprite_id"), r.get("size_radius")
                if s and size and s not in out:
                    out[s] = int(size)
            return out
        except Exception:
            return {}

    def set_stage(self, map_id, panel=None):
        """show the skill on a battle map (map id) or on a flat floor (None)"""
        self.map_id, self.panel = map_id, panel
        self.bmap = battlemap.load(map_id, self.data_dir) if map_id else None

    def _origin(self):
        bm = self.bmap
        if bm is None:
            return None, None
        ij = self.panel or ((7, 4) if bm.id == battlemap.DEFAULT_MAP else bm.default_panel())
        return ij, bm.panel_centre(*ij)

    def ground(self, x, y):
        """a panel offset in the skill's frame (x sideways, y forward) -> its centre on the ground (world, script
        units, height relative to the caster's panel); off the map: at the caster's height"""
        w = stg.turn_offset((x, 0.0, y), stg.facing_quarter(int(self.facing or 0)))
        dx, dz = int(round(w[0])), int(round(w[2]))
        h = 0.0
        ij, origin = self._origin()
        if ij is not None and self.bmap.has_panel(ij[0] + dx, ij[1] + dz):
            h = (origin[1] - self.bmap.panel_centre(ij[0] + dx, ij[1] + dz)[1]) * stg.MAP
        return np.array([dx * stg.PANEL, h, dz * stg.PANEL])

    def cursor(self):
        """panels from the caster to the cursor (skills with a range) / the target"""
        return max(1, int(round(float(self.distance or 1.0))))

    def target_panels(self):
        """(x, y) of the area targets in the game's order (relative to the caster, the skill's frame)"""
        if self.area is None:
            return [(0, self.cursor())]
        return self.area.target_panels(self.cursor(), self.enemies)

    def target_distance(self):
        """$64000: panels between the caster and the main target"""
        x, y = self.target_panels()[0]
        return max(1, abs(int(x)) + abs(int(y)))

    def _layout(self):
        """(caster ground point on the map, target places, area panels, reach, cursor)"""
        ij, origin = self._origin()
        if self.area is None:
            # no area known (a choreography by its id): one target `distance` panels ahead, as before
            d = float(self.distance or 1.0)
            dx, dz = stg.FACING_DIRS.get(int(self.facing or 0) % 4, (0.0, 1.0))
            ty = 0.0
            if ij is not None:
                n = max(1, int(round(d)))
                ty = (origin[1] - self.bmap.panel_centre(ij[0] + int(dx) * n, ij[1] + int(dz) * n)[1]) * stg.MAP
            t = np.array([dx * d * stg.PANEL, ty, dz * d * stg.PANEL])
            return origin, [t], [], [], None
        cur = self.cursor()
        targets = [self.ground(x, y) for x, y in self.target_panels()]
        area = [tuple(self.ground(x, y)) + (k,) for x, y, k in self.area.panels(cur)]
        reach = [tuple(self.ground(x, y)) for x, y in self.area.reach()]
        cursor = tuple(self.ground(0, cur)) if self.area.centred else None
        return origin, targets, area, reach, cursor

    def heights(self, radius=16):
        """{(dx, dz): ground height} of the map's panels around the caster's (script units; for moves that land
        on the ground)"""
        ij, origin = self._origin()
        if ij is None:
            return None
        key = (self.bmap.id, ij)
        if getattr(self, "_heights_key", None) != key:
            out = {}
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if self.bmap.has_panel(ij[0] + dx, ij[1] + dz):
                        out[(dx, dz)] = (origin[1] - self.bmap.panel_centre(ij[0] + dx, ij[1] + dz)[1]) * stg.MAP
            self._heights_key, self._heights = key, out
        return self._heights

    def setup(self):
        origin, targets, area, reach, cursor = self._layout()
        self.gl.set_map(self.bmap, origin if origin is not None else (0.0, 0.0, 0.0))
        self.gl.show_area = self.show_area
        return stg.Setup(caster_sprite=self.caster_sprite, caster_palette=self.caster_palette,
                         target_sprite=self.target_sprite, target_palette=self.target_palette,
                         weapon=self.weapon, facing=int(self.facing or 0), distance=float(self.distance or 1.0),
                         caster_y=0.0, target_y=float(targets[0][1]), view_yaw=self.view_yaw,
                         event_sheets=dict(self.event_sheets), class_sprites=dict(self.class_sprites),
                         targets=[tuple(t) for t in targets], area=area, reach=reach, cursor=cursor,
                         heights=self.heights())

    # ---- the editor's renderer interface
    @property
    def hidden_slots(self):
        return self.gl.hidden_slots

    @property
    def pick(self):
        return self.gl.pick

    def bind(self, tl):
        """(re)build the stage simulation of a timeline; the timeline's scene() then comes from it"""
        if tl is None:
            self.sim = None
            return None
        self.sim = stg.StageSim(tl, self.setup(), self.assets.sim_model)
        tl.stage = self.sim
        self.gl.particles = self.particles
        return self.sim

    def actor_base(self, a):
        s = self.setup()
        a = choreo.actor_id(a)
        if choreo.is_target(a):
            places = s.target_places()
            i = 0 if a == choreo.TARGET else a - choreo.AREA_TARGET
            return places[i] if i < len(places) else s.caster_pos()
        return s.caster_pos()

    def actor_pos(self, scene, a):
        if scene is not None and "places" in scene:
            return stg.scene_where(scene, a)
        return self.actor_base(a)

    def slot_pos(self, scene, s):
        w = s.get("world") if isinstance(s, dict) else None
        if w is not None:
            return np.array(w, float)
        return self.actor_pos(scene, s.get("actor", choreo.CASTER)) + np.array(s.get("pos", (0, 0, 0)), float)

    def marker_pos(self, scene, slot, cam, w, h):
        if slot not in scene["slots"]:
            return None
        p, _ = cam.project(self.slot_pos(scene, scene["slots"][slot])[None], w, h)
        return p[0]

    def stage_at(self, scene):
        sim = scene.get("sim") if scene else None
        sim = sim or self.sim
        return sim.at(scene.get("frame", 0)) if sim is not None else None

    def paint(self, gl, w, h, scene, view, dpr=1.0, viewport=None):
        """draw the scene's frame (w, h: logical size; GL viewport in device pixels)"""
        st = self.stage_at(scene)
        if st is None:
            return
        self.gl.show_grid = self.show_grid
        self.gl.weapon = self.weapon
        self.gl.highlights = self.highlights
        vp = None
        if viewport is not None:
            x, y, vw, vh = viewport
            vp = (int(round(x * dpr)), int(round((h - y - vh) * dpr)), int(round(vw * dpr)), int(round(vh * dpr)))
        else:
            vp = (0, 0, int(round(w * dpr)), int(round(h * dpr)))
        self.gl.paint(gl, w, h, st, view, viewport=vp, clear=True)

    def game_view(self, scene, w, h):
        """the game camera at a scene's frame, letterboxed to 16:9 inside w x h"""
        st = self.stage_at(scene)
        if st is None:
            return None
        vw, vh = w, w * 9.0 / 16.0
        if vh > h:
            vh, vw = h, h * 16.0 / 9.0
        return stg.GameView(st, 16.0 / 9.0, viewport=((w - vw) / 2.0, (h - vh) / 2.0, vw, vh))
