# WHEELS3 — the live check

Run after `INSTALL.md` step 3–4 (exe rebuilt, game fully restarted). Eight checks. The first two are the
freeze; the rest are the pages, a hire from each page, and Rebirth.

**Have ready:** a save you can lose (Save1 is fine; **never load Save2**). Keep `hide_game.sh` running if
the launch is the harness's, and note that a crash dialog would be invisible then — check the game log for
`Unhandled exception` / `0xc0000005` if anything stops answering.

1. **Castle → Recruiter (Create Character): accept the confirm that opens *Hire Character*.**
   Expect: the wheel opens (this is the exact step WHEELS2 froze on, twice).

2. **Back out and open it again.** Expect: it opens again, same speed, no stall.

3. **Open it with nothing held.** Expect the **D5 wheel: the vanilla 47** — no "Warrior (D4)", no D1C names.

4. **Back out. Hold Shift and open it.** Expect the **D4 wheel: 45 entries**, first **Warrior (D4)**.

5. **Back out. Hold Shift + 3 and open it.** Expect the **D1C wheel: 13 entries**.

6. **Hire one class from each page** (the thing WHEELS2 could never reach):
   * D4 page (Shift+2): put the cursor on **Warrior (D4)**, confirm, pay the HL.
     Expect: recruited is *Warrior (D4)* — **not** the class next to it, **not** a vanilla class.
   * D1C page (Shift+3): the same with one D1C class (e.g. **Strider**).
   * D5 page (no key): the same with one vanilla class (e.g. **Fighter**).
   Expect each one's name, epithet and help line on the recruited unit and in the roster.

7. **Rebirth menu → hold Shift + 2, then Shift + 3.** Expect the same 45 D4 / 13 D1C classes as the
   Recruiter, and **one Rebirth unit** through: pick a class, confirm the reincarnation, land back on the
   base screen with the unit changed.

8. **Save, quit fully, relaunch, load that save.** Expect: the three hired units and the reborn unit are
   still what you hired, and the wheel opens normally.

## What is expected and is not a bug

* **DD2 / Overlord pages are empty** in this profile; Shift cycles past them and Shift+4/+5 fall through
  to the next non-empty page.
* **Shift must be held while the confirm is accepted** — the page is chosen when the list is built. Let go
  of Shift before the wheel appears and you get the stored page (which is correct behaviour, not a miss).
* **The D5 page shows only the game's own classes**: D4/D1C live on their own pages now.
* Rebirth's route may not be mapped in the harness yet (`NAV-REPORT` §7); if so, do check 7 by hand.

## If something fails

Note the number, quit, and read `INSTALL.md` › Safety. For a freeze: the game log first, then a
`winedbg` backtrace against the ranked list in `Subprojects/Engine-Extensions/D1CFREEZE-REPORT.md` §5 —
but note that the site this build fixes (`0x1408ce670`, `wheels/WHEELS3-DIAGNOSIS.md`) is not on that list.
