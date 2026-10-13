# Disgaea 5 Complete (PC) — Database tables (`Data/Database/Database_0.dat`)

`Database_0.dat` is an obfuscated NISPACK (see FORMATS.md) holding **90 member tables**.
Member names are truncated to 31 chars in the archive (e.g. `Enemy_Parameters_TableDataBase`,
`ItemWorld_ProbabilityDataBase.d`, `MakaiEdit_TownEditCategoryDataB`); the schemas use the exact archive names.

<!-- ENGINE -->
## Library: `d5lib/database.py`

```python
from d5lib.database import (load_database, load_database_dir, load_table, get_schema,
                            table_to_csv, table_from_csv, database_to_csv, ref_choices, resolve_ref)

db = load_database(r"D:\Games\Disgaea 5 Complete\Data\Database\Database_0.dat")   # Database (dict: member -> Table)
t  = db["char.dat"]            # or db.table("char")  (tolerant lookup)
r  = t.rows[0]                 # Row
r["name_EN"], r.get("HP"), r.to_dict()
r["name_EN"] = "Killia"        # strings: UTF-8, StringTooLong raised if > slot-1 bytes (r.set(name, v, truncate=True) cuts)
t.add_row(copy_from=0)         # append copy (index=... to insert); keyword args set fields
t.delete_row(5)
data = t.to_bytes()            # byte-identical for unmodified tables (all 90 verified)
db.save(r"...\\Database_0.dat")  # rebuild whole archive (write to a copy / mod folder, never over the original)
database_to_csv(db, "csv_out")  # one CSV per table (+ table__section.csv for sub sections)
table_from_csv(t, "char.csv")   # re-import edited CSV (rows matched by '#' index column)
```

* `Table`: `.name .schema .header (Row) .rows [Row] .sections {name: Table} .fields`, `find(value, field=key)`,
  `index_of()`, `new_row()`, `add_row(copy_from=None, index=None, **values)`, `delete_row(i)`, `to_bytes()`.
* `Row`: backed by the raw record bytes (`row.raw`) so unknown bytes survive edits; pool strings live in `row.strs`.
  `row[name]`, `row[name] = v`, `get/set`, `keys()`, `to_dict()`, `copy()`.
* The header `count` field (role `count`) is updated automatically; pool `strlen` fields are recomputed.
* `ref_choices(db, "magic.dat")` -> `[(key, label)]` for GUI dropdowns; `resolve_ref(db, field, value)` -> Row.

### Schema files `d5lib/schemas/<stem>.json`

```json
{"file":"char.dat", "layout":"fixed", "header":{"size":4,"fields":[{"name":"count","offset":0,"type":"u32","role":"count"}]},
 "record_size":908, "key":"id", "display":"name_EN", "desc":"...",
 "fields":[{"name":"...","offset":0,"type":"u16","ref":"JobRank.dat","enum":{"0":"..."},"desc":"...","confidence":"high"}]}
```

* types: `u8 i8 u16 i16 u32 i32 u64 i64 f32 str(size) bytes(size) strptr`; `lang` = JP/EN/FR/CHN/KOR for text slots.
* `ref`: `"table.dat"` = value equals the target table's `key`; `"table.dat#index"` = row index;
  `"table.dat:field"` = matches that field; external: `"anm"` (anmNNNNN), `"map"` (mapNNNNN), `"bgm"`, ...
* every record byte is covered by exactly one field (`unk_XXX`/`pad_XXX` = not understood / padding); `confidence` high/medium/low.
* `Schema.check_coverage()` reports gaps/overlaps.

### Layouts

| layout | tables | description |
|---|---|---|
| `fixed` | 69 | `u32 count` + count × fixed records |
| `pool` | 18 | `u32 count` + fixed records containing `strptr` (u32 offsets, relative to file offset 4) + string pool. Pool = for each row, each strptr field in order: `\0` + UTF-8 + `\0` (pointer → first text byte). Often preceded by a u32 **character** count field (role `strlen`). |
| `custom:name_lists` | name.dat | `u32 counts[30]`, `u32 offsets[sum]`, NUL-separated string pool; pseudo-rows (list, pool_order, text) |
| `custom:attackmap` | AttackMap.dat | `u16 count, u16 cell_count`, 8-byte shape records, 3-byte cell records (section `cells`), 3 junk trailer bytes |
| `custom:matrix` | comb.dat | `u32 used`, `u16 ids[256]`, `u8 matrix[256][256]`; pseudo-row = id + 256 values |

Pool tables: Skill.dat, StringListDataBase.dat, TownEditMessageDataBase.dat, WishDataBase.dat, WorldMapHelpDataBase.dat,
FlagListDataBase.dat, FlagList_DebugDataBase.dat, FlagList_DLCDataBase.dat, DLC_DeliveryDataBase.dat,
DLC_Delivery_HelpDataBase.dat, DLC_ShopDataBase.dat, MakaiEdit_TownEditCategoryDataB, MakaiEdit_ExteriorPartsDataBase,
MakaiSkillDataBase.dat, Makai_InvaderaDataBase.dat, Makai_Invader_UniqueDataBase.da, MapObjectTableDataBase.dat,
ItemWorld_Room_CharDataDataBase.

Round-trip test: `python _research/db/test_roundtrip.py` (see result at the end of this document).
<!-- /ENGINE -->
