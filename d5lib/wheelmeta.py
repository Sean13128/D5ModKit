"""Resolve a class mod's wheel from its metadata.

This is metadata validation only; it does not install or switch a game menu.
"""

WHEELS = ("d5", "d4", "d1c", "dd2", "overlord")


def class_wheel(metadata):
    """Return a canonical wheel name, honoring an explicit ``wheel`` first.

    Imported mods default to their recorded source game. Mods without source
    metadata default to D5. Unknown or malformed values are errors so that a
    typo cannot silently put a class on the wrong page.
    """
    if not isinstance(metadata, dict):
        raise ValueError("mod metadata must be an object")
    if metadata.get("category") != "classes":
        raise ValueError("wheel metadata applies only to class mods")
    if "wheel" in metadata:
        value = metadata["wheel"]
    else:
        source = metadata.get("source_import")
        if source is None:
            value = "d5"
        elif not isinstance(source, dict):
            raise ValueError("source_import must be an object")
        else:
            identity = source.get("identity")
            if identity is not None and not isinstance(identity, dict):
                raise ValueError("source_import.identity must be an object")
            value = (identity or {}).get("source", source.get("source_game"))
            if value is None:
                raise ValueError("source_import does not identify a source game")
    if not isinstance(value, str) or value not in WHEELS:
        raise ValueError(f"unknown class wheel: {value!r}")
    return value


def family_wheels(mod_specs):
    """Return ordered wheel -> sorted custom families from enabled mod/spec pairs.

    Native D5 classes are implicit in the runtime. Repeated definitions of the
    same family must agree on the wheel, regardless of mod priority.
    """
    owners = {}
    for metadata, specs in mod_specs:
        specs = list(specs)
        if not specs:
            continue
        # A class descriptor is authoritative even for legacy mods with no
        # category or mixed-content mods classified as characters.
        if not isinstance(metadata, dict):
            raise ValueError("mod metadata must be an object")
        wheel = class_wheel({**metadata, "category": "classes"})
        for spec in specs:
            if not isinstance(spec, dict) or 'family' not in spec:
                raise ValueError("class descriptor must identify a family")
            raw_family = spec['family']
            if isinstance(raw_family, bool) or not isinstance(raw_family, (int, str)):
                raise ValueError(f"invalid class family: {raw_family!r}")
            try:
                family = int(raw_family)
            except ValueError as exc:
                raise ValueError(f"invalid class family: {raw_family!r}") from exc
            if not 1 <= family <= 65535:
                raise ValueError(f"class family outside runtime u16 range: {family}")
            previous = owners.get(family)
            if previous is not None and previous != wheel:
                raise ValueError(f'class family {family} assigned to both {previous} and {wheel} wheels')
            owners[family] = wheel
    return {wheel: sorted(family for family, owner in owners.items() if owner == wheel)
            for wheel in WHEELS}


def runtime_entries(mod_specs):
    """Compile enabled class descriptors to (family, wheel index) pairs.

    Wheel indices are positions in WHEELS. Native D5 entries remain implicit;
    this table only assigns explicit class descriptors. Conflicting declarations
    fail even if a later mod would otherwise override a descriptor. Each family
    is representable as a runtime unsigned 16-bit ID.
    """
    groups = family_wheels(mod_specs)
    return sorted((family, index)
                  for index, wheel in enumerate(WHEELS)
                  for family in groups[wheel])
