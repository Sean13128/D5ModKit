# Disgaea 1 (PC / Complete): where a special attack's reach lives

Format facts found by D1SCRIPT1 (decomp + running the game's own builder offline). Values are read
from your own copy of the game; none are stored here.

## Skill row (magic table, HD row)

| offset | field |
|---|---|
| +0x04 | power (raw; see "Power" below) |
| +0x06 | SP cost |
| +0xAB | range; used only by cursor-placed shapes |
| +0xAC | **pattern** number; 0 = spell rule (area comes from the spell level) |
| +0xAD / +0xAE | height up / down, same units as D5's height_up / height_down |

## Pattern = a panel list the program builds in code

No data file holds the shapes. At start-up the exe builds 82 lists of target panels
(PC `dis1_st.exe` FUN_004430d0; D1 Complete Switch main FUN_7100012ea4); a row's pattern `p` uses
entry `p-1`. `tools/d1_attack_patterns.py` runs that builder under Unicorn and checks the result
against `d5lib/importers/d1-attack-patterns.json` (our derived shapes + the exe SHA-256); PC and
Switch give the same 82 shapes.

Cell format equals D5's AttackMap: x sideways, y forward; kind 1 = hit, 2 = caster ends here,
3 = cursor panel. Most shapes are placed from the caster (= D5 range 0); 13 are cursor shapes and
use the range byte. Users in the decomp: PC FUN_0044a3b0 / FUN_004cd5c0, D1C FUN_710001d338 /
FUN_71000afde0.

The importer (`d5lib/srcskills.py`, `d5lib/importers/specials2.py`) maps each pattern to the
identical D5 shape; a D1 landing cell D5's shape lacks is dropped and labelled.

## Power does not convert by formula

D1 (PC FUN_0046fdc0 special, FUN_0046f670 normal): a special's attack value is
`(ATK + power * soft(level+100)/100) / 20` against `ATK / 30` for a normal hit, so every special
carries a built-in 1.5x. D5 (compute_target 0x1401BE860, effect_list 0x1401BFAE0, effect_value
0x1401D7A20): special / normal = `(100 + effect1_value) / 100`. A model built from these was tested
on the 29 physical moves both games share and rejected (`tools/d1_power_model.py`: mean error 54-180
points against 24 for taking the stand-in's power). D1 special power therefore stays the D5
stand-in's, labelled.

## Attack motions

The 40x attack motions in imported D1 bodies are D5 donor motions carrying D1 pictures; D1's own
body banks hold no 40x animation.
