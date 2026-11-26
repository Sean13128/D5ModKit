"""Allocation manifest and collision checker (offline; no game, no exe, no kit state).

One owner per namespace.  A *namespace* is a numeric space or a set of named resources that two
providers can both try to use:

  char_dat_row       char.dat row ids (a row is a class rank, a unique character or a dummy)
  job_class_id       class / rank ids used in saves, menus and JobRank (incl. registry leases)
  unlock_flag        FlagList indices: "this class rank is unlocked"
  mastery_slot       per-unit class-mastery array index (0..52)
  evility_id         Skill.dat row ids
  special_id         magic.dat row ids (skills, specials)
  wish_id            WishDataBase row ids
  anm_id             ANM image / animation-set ids (sprites, portraits, cut-ins)
  voice_id           voice ids (voice set = kind * 100000 + voice id * 10 + personality)
  script_event_id    Script/script.dat event ids (skill choreographies, call_event targets)
  database_member    Database_0.dat member names (a member is replaced or row-merged as a whole)

Every band has exactly one ``owner`` and a ``status``.  ``contested`` is the only status that names
two claimants, and nothing may be allocated inside it until the two sides resolve.  ``unallocated``
means "nobody has recorded an owner here" -- which is *not* free: a claim there is refused, so an
unrecorded band cannot be taken by accident.

Claims (what a mod or a runtime actually uses) are checked against the manifest: the band must exist,
it must belong to the claimer, it may not straddle two bands, and no two holders may claim the same
ids.  Registry class identities (10000..32760) get additional derived checks, because a class id is
not only a job id: it also derives portrait/list-icon ids (10000 + id + 0..9) and own-skill ids
(10000 + id + 0..99), which must not land in a band reserved for Overlord.

Everything here is a pure function of the JSON manifest plus the claims handed in: the same inputs
always give the same projection, so install/uninstall plans can be replayed and diffed.
"""
import json
import os

OWNER_VANILLA = "vanilla"
OWNER_KIT = "kit"
OWNER_OVERLORD = "overlord"
OWNER_CONTESTED = "contested"
OWNER_UNALLOCATED = "unallocated"
OWNERS = (OWNER_VANILLA, OWNER_KIT, OWNER_OVERLORD, OWNER_CONTESTED, OWNER_UNALLOCATED)

STATUS_IN_USE = "in_use"
STATUS_RESERVED = "reserved"
STATUS_CONTESTED = "contested"
STATUS_VANILLA = "vanilla"
STATUS_UNALLOCATED = "unallocated"
STATUSES = (STATUS_IN_USE, STATUS_RESERVED, STATUS_CONTESTED, STATUS_VANILLA, STATUS_UNALLOCATED)

ERROR, WARNING, INFO = "error", "warning", "info"

MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ownership_manifest.json")


class Band:
    __slots__ = ("start", "end", "owner", "status", "label", "evidence", "claimants", "rule")

    def __init__(self, start, end, owner, status, label, evidence="", claimants=(), rule=None):
        self.start, self.end = int(start), int(end)
        self.owner, self.status = owner, status
        self.label, self.evidence = label, evidence
        self.claimants = tuple(claimants)
        self.rule = rule

    @classmethod
    def from_dict(cls, d):
        return cls(d["start"], d["end"], d["owner"], d["status"], d.get("label", ""),
                   d.get("evidence", ""), d.get("claimants") or (), d.get("rule"))

    def covers(self, n):
        return self.start <= n <= self.end

    def overlaps(self, start, end):
        return self.start <= end and start <= self.end

    def as_dict(self):
        d = {"start": self.start, "end": self.end, "owner": self.owner, "status": self.status}
        if self.claimants:
            d["claimants"] = list(self.claimants)
        if self.rule:
            d["rule"] = self.rule
        d["label"] = self.label
        d["evidence"] = self.evidence
        return d

    def __repr__(self):
        return f"Band({self.start}-{self.end}, {self.owner}/{self.status})"


class Namespace:
    def __init__(self, name, kind, description="", bands=(), members=(), rules=None):
        self.name, self.kind = name, kind
        self.description = description
        self.bands = list(bands)
        self.members = list(members)
        self.rules = dict(rules or {})

    @classmethod
    def from_dict(cls, name, d):
        return cls(name, d.get("kind", "range"), d.get("description", ""),
                   [Band.from_dict(b) for b in d.get("bands") or ()],
                   [dict(m) for m in d.get("members") or ()],
                   d.get("rules") or {})

    def band_at(self, n):
        for b in self.bands:
            if b.covers(n):
                return b
        return None

    def bands_between(self, start, end):
        return [b for b in self.bands if b.overlaps(start, end)]

    def member(self, name):
        for m in self.members:
            if m.get("name") == name:
                return m
        return None


class Manifest:
    def __init__(self, data):
        self.version = int(data.get("version", 0))
        self.base = data.get("base", "")
        self.generated = data.get("generated", "")
        self.namespaces = {k: Namespace.from_dict(k, v) for k, v in (data.get("namespaces") or {}).items()}
        self.rules = data.get("rules") or {}
        self.notes = data.get("notes") or []

    def namespace(self, name):
        return self.namespaces.get(name)


def load(path=None):
    with open(path or MANIFEST_PATH, "r", encoding="utf-8") as fh:
        return Manifest(json.load(fh))


# --------------------------------------------------------------------------------------------- findings
class Finding:
    __slots__ = ("severity", "kind", "namespace", "start", "end", "holder", "detail")

    def __init__(self, severity, kind, namespace, start, end, holder, detail):
        self.severity, self.kind = severity, kind
        self.namespace, self.start, self.end = namespace, start, end
        self.holder, self.detail = holder, detail

    @property
    def span(self):
        if self.start is None:
            return self.namespace
        return f"{self.namespace}[{self.start}..{self.end}]"

    def as_dict(self):
        return dict(severity=self.severity, kind=self.kind, namespace=self.namespace,
                    start=self.start, end=self.end, holder=self.holder, detail=self.detail)

    def __str__(self):
        who = f" ({self.holder})" if self.holder else ""
        return f"{self.severity.upper():7s} {self.kind:18s} {self.span}{who}: {self.detail}"

    def __repr__(self):
        return f"Finding({self.as_dict()!r})"


def errors(findings):
    return [f for f in findings if f.severity == ERROR]


# ----------------------------------------------------------------------------------------------- claims
class Claim:
    """One holder's use of ids: a range, or a single member name in a list namespace."""
    __slots__ = ("holder", "namespace", "start", "end", "label", "evidence", "member")

    def __init__(self, holder, namespace, start=None, end=None, label="", evidence="", member=None):
        self.holder, self.namespace = holder, namespace
        if member is not None:
            self.start = self.end = None
            self.label = label or member
            self.member = member
        else:
            self.start, self.end = int(start), int(end if end is not None else start)
            if self.end < self.start:
                raise ValueError(f"claim {namespace} {start}..{end}: end before start")
            self.label = label
            self.member = None
        self.evidence = evidence

    @property
    def owner(self):
        return self.holder.split(":", 1)[0]

    @classmethod
    def from_dict(cls, d):
        return cls(d["holder"], d["namespace"], d.get("start"), d.get("end"), d.get("label", ""),
                   d.get("evidence", ""), d.get("member"))

    def as_dict(self):
        d = {"holder": self.holder, "namespace": self.namespace}
        if self.member is not None:
            d["member"] = self.member
        else:
            d["start"], d["end"] = self.start, self.end
        if self.label:
            d["label"] = self.label
        if self.evidence:
            d["evidence"] = self.evidence
        return d

    def __repr__(self):
        rng = repr(self.member) if self.member is not None else f"{self.start}..{self.end}"
        return f"Claim({self.holder}, {self.namespace}, {rng})"


def load_claims(path):
    """A claims file: a list, or {"claims": [...]}; fixture files for tests and install plans."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data.get("claims") if isinstance(data, dict) else data
    return [Claim.from_dict(r) for r in rows or ()]


# -------------------------------------------------------------------------------------- manifest check
def check_manifest(manifest):
    """Self-consistency of the manifest itself (no claims involved)."""
    out = []
    if manifest.version != 1:
        out.append(Finding(ERROR, "manifest_version", "-", None, None, "", f"unknown version {manifest.version}"))
    if not manifest.namespaces:
        out.append(Finding(ERROR, "manifest_empty", "-", None, None, "", "no namespaces"))
    if not _registry_rule(manifest, "job_class_id"):
        out.append(Finding(ERROR, "manifest_rule", "job_class_id", None, None, "",
                           "registry_lease rule is missing: registry ids would be unchecked"))
    for name, ns in manifest.namespaces.items():
        if ns.kind == "range":
            bands = sorted(ns.bands, key=lambda b: b.start)
            if not bands:
                out.append(Finding(ERROR, "namespace_empty", name, None, None, "", "range namespace has no bands"))
            for a, b in zip(bands, bands[1:]):
                if b.start <= a.end:
                    out.append(Finding(ERROR, "band_overlap", name, b.start, min(a.end, b.end),
                                       f"{a.owner}/{b.owner}",
                                       f"bands {a.start}..{a.end} and {b.start}..{b.end} overlap"))
            for b in bands:
                if b.owner not in OWNERS:
                    out.append(Finding(ERROR, "invalid_owner", name, b.start, b.end, b.owner,
                                       f"owner must be one of {OWNERS}"))
                if b.status not in STATUSES:
                    out.append(Finding(ERROR, "invalid_status", name, b.start, b.end, b.owner,
                                       f"status must be one of {STATUSES}"))
                if b.end < b.start:
                    out.append(Finding(ERROR, "bad_band", name, b.start, b.end, b.owner, "end before start"))
                if not b.label:
                    out.append(Finding(WARNING, "unlabelled_band", name, b.start, b.end, b.owner,
                                       "band has no label"))
                if b.owner == OWNER_CONTESTED:
                    if b.status != STATUS_CONTESTED:
                        out.append(Finding(ERROR, "contested_status", name, b.start, b.end, b.owner,
                                           "a contested owner needs status 'contested'"))
                    if len(b.claimants) != 2:
                        out.append(Finding(ERROR, "contested_claimants", name, b.start, b.end, b.owner,
                                           "a contested band must name exactly two claimants"))
                elif b.claimants:
                    out.append(Finding(ERROR, "stray_claimants", name, b.start, b.end, b.owner,
                                       "only a contested band may name claimants"))
                if b.owner == OWNER_UNALLOCATED and b.status != STATUS_UNALLOCATED:
                    out.append(Finding(WARNING, "unallocated_status", name, b.start, b.end, b.owner,
                                       "unallocated bands should carry status 'unallocated'"))
        elif ns.kind == "list":
            seen = set()
            for m in ns.members:
                name_m = m.get("name")
                if not name_m:
                    out.append(Finding(ERROR, "member_unnamed", name, None, None, "", "a member has no name"))
                    continue
                if name_m in seen:
                    out.append(Finding(ERROR, "member_duplicate", name, None, None, name_m,
                                       "member listed twice"))
                seen.add(name_m)
                if m.get("owner") not in OWNERS:
                    out.append(Finding(ERROR, "invalid_owner", name, None, None, m.get("owner"),
                                       f"member {name_m}: owner must be one of {OWNERS}"))
            if not ns.members:
                out.append(Finding(ERROR, "namespace_empty", name, None, None, "", "list namespace has no members"))
        else:
            out.append(Finding(ERROR, "namespace_kind", name, None, None, "", f"unknown kind {ns.kind!r}"))
    return out


# ---------------------------------------------------------------------------------------- claim checks
def _registry_rule(manifest, namespace):
    ns = manifest.namespace(namespace)
    if ns is not None and ns.rules.get("registry_lease"):
        return ns.rules["registry_lease"]
    return (manifest.rules.get(namespace) or {}).get("registry_lease") or {}


def check_registry_lease(manifest, claim):
    """A registry class identity: its own numeric rules, plus the ids it derives (portraits, skills)."""
    out = []
    rule = _registry_rule(manifest, claim.namespace)
    if not rule:
        return out
    if claim.start < rule["first"] or claim.start > rule["last"]:
        out.append(Finding(ERROR, "registry_range", claim.namespace, claim.start, claim.end, claim.holder,
                           f"registry identity {claim.start} outside {rule['first']}..{rule['last']}"))
    if claim.start % rule["step"]:
        out.append(Finding(ERROR, "registry_step", claim.namespace, claim.start, claim.end, claim.holder,
                           f"registry identity {claim.start} is not a multiple of {rule['step']}"))
    if claim.end - claim.start >= rule.get("max_ranks", 6):
        out.append(Finding(ERROR, "registry_ranks", claim.namespace, claim.start, claim.end, claim.holder,
                           f"a class owns at most {rule.get('max_ranks', 6)} rank ids"))
    if claim.end > claim.start + rule.get("max_ranks", 6) - 1 or claim.start % rule["step"]:
        return out                                  # already reported; derived ids would be noise
    for lo, hi in rule.get("excluded") or ():
        if claim.start <= hi and lo <= claim.end:
            out.append(Finding(ERROR, "reserved_id", claim.namespace, max(claim.start, lo), min(claim.end, hi),
                               claim.holder, f"reserved for Overlord ({lo}..{hi})"))
    for d in rule.get("derived") or ():
        ns = manifest.namespace(d["namespace"])
        if ns is None:
            continue
        lo, hi = claim.start + d["offset"], claim.end + d["offset"] + d["span"]
        for band in ns.bands_between(lo, hi):
            if band.owner == OWNER_OVERLORD or band.owner == OWNER_CONTESTED:
                out.append(Finding(ERROR, "derived_conflict", d["namespace"], lo, hi, claim.holder,
                                   f"{d['label']} for class {claim.start} land in {band.owner} band "
                                   f"{band.start}..{band.end} ({band.label})"))
    return out


def check_unique_lease(manifest, claim, band):
    """A unique on a registry identity: one rank, and none of a class's derived ids.

    Its portraits, list icons and faces are keyed to the low *physical* row it leases (anm band
    `unique_sprite`), not to `10000 + identity`, so the class-derived check would report ids it never
    uses.  Exactly one rank is the whole point: rank 0, digits 1-5 unused.
    """
    out = []
    rule = _registry_rule(manifest, claim.namespace)
    if claim.end != claim.start:
        out.append(Finding(ERROR, "unique_ranks", claim.namespace, claim.start, claim.end, claim.holder,
                           "a unique identity is one rank (rank 0 only)"))
    if claim.start % 10:
        out.append(Finding(ERROR, "registry_step", claim.namespace, claim.start, claim.end, claim.holder,
                           "unique identity is not a multiple of 10"))
    if rule and (claim.start < rule["first"] or claim.start > rule["last"]):
        out.append(Finding(ERROR, "registry_range", claim.namespace, claim.start, claim.end, claim.holder,
                           f"unique identity {claim.start} outside {rule['first']}..{rule['last']}"))
    if band is not None and (claim.start < band.start or claim.end > band.end):
        out.append(Finding(ERROR, "spans_bands", claim.namespace, claim.start, claim.end, claim.holder,
                           "unique identity leaves its reserved band"))
    return out


def check_claims(manifest, claims):
    """Every claim against the manifest, then claims against each other.  Deterministic order."""
    out = []
    for c in sorted(claims, key=lambda c: (c.namespace, c.start if c.start is not None else -1, c.holder)):
        ns = manifest.namespace(c.namespace)
        if ns is None:
            out.append(Finding(ERROR, "unknown_namespace", c.namespace, c.start, c.end, c.holder,
                               "namespace is not in the manifest"))
            continue
        if ns.kind == "list":
            if not c.member:
                out.append(Finding(ERROR, "claim_shape", c.namespace, None, None, c.holder,
                                   "a list namespace is claimed by member name"))
                continue
            m = ns.member(c.member)
            if m is None:
                out.append(Finding(ERROR, "unknown_member", c.namespace, None, None, c.holder,
                                   f"{c.member} is not a listed member (add it to the manifest first)"))
            elif m.get("owner") != c.owner:
                out.append(Finding(ERROR, "not_owned", c.namespace, None, None, c.holder,
                                   f"{c.member} is owned by {m.get('owner')}"))
            continue
        if c.start is None:
            out.append(Finding(ERROR, "claim_shape", c.namespace, None, None, c.holder,
                               "a range namespace is claimed by start/end"))
            continue
        bands = ns.bands_between(c.start, c.end)
        if not bands:
            out.append(Finding(ERROR, "not_owned", c.namespace, c.start, c.end, c.holder,
                               "no band in the manifest covers this range"))
        elif len(bands) > 1:
            out.append(Finding(ERROR, "spans_bands", c.namespace, c.start, c.end, c.holder,
                               "straddles " + ", ".join(f"{b.start}..{b.end} ({b.owner})" for b in bands)))
        else:
            band = bands[0]
            if band.owner == OWNER_CONTESTED:
                out.append(Finding(ERROR, "contested", c.namespace, c.start, c.end, c.holder,
                                   f"contested between {' and '.join(band.claimants)} ({band.label})"))
            elif band.owner != c.owner:
                out.append(Finding(ERROR, "not_owned", c.namespace, c.start, c.end, c.holder,
                                   f"band {band.start}..{band.end} is {band.owner} ({band.label})"))
        if c.namespace == "job_class_id" and c.start >= 10000 and c.owner == OWNER_KIT:
            band = ns.band_at(c.start) if ns is not None else None
            if band is not None and band.rule == "unique_registry_lease":
                out.extend(check_unique_lease(manifest, c, band))
            else:
                out.extend(check_registry_lease(manifest, c))
    out.extend(duplicate_findings(manifest, claims))
    return out


def duplicate_findings(manifest, claims):
    """Two holders on one resource.  Purely about *usage*, not about who a band belongs to.

    Split out so a set of claims that is not checked against the manifest's bands -- every installed
    mod folder, a vanilla table -- can still be refused when two of them take the same ids
    (d5lib/modclaims.py; the 491-495 outfit-row collision).
    """
    out = []
    by_ns = {}
    for c in claims:
        by_ns.setdefault(c.namespace, []).append(c)
    for ns_name in sorted(by_ns):
        ns = manifest.namespace(ns_name)
        kind = ns.kind if ns else "range"
        group = by_ns[ns_name]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if kind == "list":
                    clash = a.member is not None and a.member == b.member
                else:
                    if a.start is None or b.start is None:
                        continue
                    clash = a.start <= b.end and b.start <= a.end
                if not clash:
                    continue
                severity = ERROR if a.holder != b.holder else WARNING
                kind_name = "duplicate_claim" if a.holder != b.holder else "self_overlap"
                out.append(Finding(severity, kind_name, ns_name,
                                   a.start if a.start is not None else None,
                                   a.end if a.end is not None else None,
                                   f"{a.holder} + {b.holder}" if a.holder != b.holder else a.holder,
                                   f"both claim {a.label or a.member or 'the same ids'}"))
    return out


def check_usage(manifest, claims):
    """Cross-holder duplicates in one set of users, without judging who a band belongs to.

    For claims that come from outside the project's own leases -- every installed mod folder, the
    vanilla table -- where "the band is not yours" is not a finding but "two of you take the same id"
    is.  A pack validator adds its own claims to this list so it is refused against the whole
    installed set, not only against its own files.
    """
    return duplicate_findings(manifest, claims)


# -------------------------------------------------------------------------------------------- projection
class Projection:
    """Which holder uses which ids, for a set of enabled providers.

    install/uninstall are pure bookkeeping, so the same plan replayed gives the same snapshot:
    that is what makes an install/uninstall projection repeatable and diffable.
    """

    def __init__(self, manifest, claims=()):
        self.manifest = manifest
        self._by_holder = {}
        for c in claims:
            self.install([c])

    def install(self, claims):
        for c in claims:
            bucket = self._by_holder.setdefault(c.holder, {})
            key = (c.namespace, c.member if c.member is not None else (c.start, c.end))
            bucket[key] = c                       # same mod installed twice = the same claim
        return self

    def uninstall(self, holder):
        self._by_holder.pop(holder, None)
        return self

    def holders(self):
        return sorted(self._by_holder)

    def claims(self, holder=None):
        if holder is not None:
            return sorted(self._by_holder.get(holder, {}).values(), key=lambda c: (c.namespace, c.start or -1))
        return self.all_claims()

    def all_claims(self):
        out = [c for h in self.holders() for c in self._by_holder[h].values()]
        return sorted(out, key=lambda c: (c.namespace, c.start if c.start is not None else -1, c.holder))

    def snapshot(self):
        """A hashable, ordered projection: install -> snapshot -> uninstall -> snapshot must match."""
        return tuple((b.holder, b.namespace, b.member, b.start, b.end) for b in self.all_claims())

    def owner_of(self, namespace, value):
        for c in self.all_claims():
            if c.namespace != namespace:
                continue
            if c.member is not None:
                if c.member == value:
                    return c.holder
            elif c.start <= value <= c.end:
                return c.holder
        return None

    def findings(self):
        return check_claims(self.manifest, self.all_claims())

    def errors(self):
        return errors(self.findings())

    def as_dict(self):
        return {"holders": self.holders(),
                "claims": [c.as_dict() for c in self.all_claims()],
                "errors": [f.as_dict() for f in self.errors()]}


# ----------------------------------------------------------------------------------------------- render
def render_markdown(manifest):
    """The manifest as one readable table per namespace, with its rules underneath."""
    lines = [f"# Allocation manifest (base {manifest.base}, generated {manifest.generated})", "",
             "One owner per band. `contested` = two projects claim it and nothing may be allocated "
             "there; `unallocated` = no owner recorded (not free).", ""]
    for name in manifest.namespaces:
        ns = manifest.namespaces[name]
        lines += [f"## {name}", "", ns.description, ""]
        if ns.kind == "range":
            lines += ["| ids | owner | status | what | evidence |", "|---|---|---|---|---|"]
            for b in sorted(ns.bands, key=lambda b: b.start):
                span = f"{b.start}" if b.start == b.end else f"{b.start}–{b.end}"
                who = b.owner + (f" ({' + '.join(b.claimants)})" if b.claimants else "")
                lines.append(f"| {span} | {who} | {b.status} | {b.label} | {b.evidence} |")
        else:
            lines += ["| member | owner | status | writers | note |", "|---|---|---|---|---|"]
            for m in ns.members:
                lines.append(f"| {m.get('name')} | {m.get('owner')} | {m.get('status', '')} | "
                             f"{', '.join(m.get('writers') or ())} | {m.get('note', '')} |")
        if ns.rules:
            lines += ["", "Rules:", ""]
            for k, v in ns.rules.items():
                lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False)}")
        lines.append("")
    if manifest.rules:
        lines += ["## Cross-namespace rules", ""]
        for k, v in manifest.rules.items():
            if k in manifest.namespaces:
                continue
            lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)
