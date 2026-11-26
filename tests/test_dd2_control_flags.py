"""R10: the control code D5 reads lives in the low byte of an animation root's key flags.

Measured on the TEST18B image: `0x1402f5002 movsx ecx, byte ptr [rdx+2]`, then 2 = loop back,
3 = conditional, 4 = wait, 5 = hold; the loop marker is found by the back-scan
`0x1402f5150 cmp byte ptr [rdx+2], 1`; code 0 takes no control action at all.
"""
import json
import os

import pytest

from d5lib import anm, classcheck, dd2source

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def block_with(flags_per_root):
    """A synthetic anm file: one animation per root, each root's keys given by flags_per_root."""
    block = anm.AnmBlock(1)
    for flags in flags_per_root:
        first = len(block.keys)
        for t, f in zip((0, 71, 143), flags):
            block.keys.append(anm.Key(t, f, 0, 0, 0, 0))
        node = len(block.nodes)
        block.nodes.append(anm.Node(0, 0, 0, 0, 0, 0, first, len(flags), -1, -1))
        block.animations.append(anm.Animation(1001 + node, node))
    return anm.AnmFile([block], [], [])


def test_control_code_moves_from_the_high_byte_to_the_low_byte():
    f = block_with([[0x0500]])
    assert dd2source.normalize_control_flags(f) == 1
    assert [k.flags for k in f.blocks[0].keys] == [0x0005]


def test_the_swap_is_a_move_not_a_swap_of_both_bytes():
    f = block_with([[0x0100, 0x0200]])
    dd2source.normalize_control_flags(f)
    assert [k.flags for k in f.blocks[0].keys] == [0x0001, 0x0002]


def test_keys_that_already_carry_a_code_are_left_alone():
    # the importer's own Key(0, 5, ...) placeholders and every drawing-node key
    f = block_with([[0x0005]])
    assert dd2source.normalize_control_flags(f) == 0
    assert [k.flags for k in f.blocks[0].keys] == [0x0005]


def test_the_transform_is_idempotent():
    f = block_with([[0x0400], [0x0500, 0x0500]])
    first = dd2source.normalize_control_flags(f)
    assert first == 3
    assert dd2source.normalize_control_flags(f) == 0


def test_non_root_drawing_keys_keep_their_high_byte():
    # a 0x100/0x200 high byte on a *drawing* node is the attachment show/hide flag, not a code
    f = block_with([[0x0001]])
    block = f.blocks[0]
    first = len(block.keys)
    block.keys.append(anm.Key(0, 0x0100, 0, 0, 0, 0))
    block.nodes.append(anm.Node(1, 0x100, 0, 0, 0, 0, first, 1, -1, -1))
    assert dd2source.normalize_control_flags(f) == 0
    assert block.keys[-1].flags == 0x0100


def test_r10_reports_a_root_with_no_control_code(tmp_path):
    f = block_with([[0x0500]])
    write_pack(tmp_path, f)
    found = classcheck.control_flag_findings(str(tmp_path))
    errors = [x for x in found if x["severity"] == "error"]
    assert errors and errors[0]["rule"] == "R10-control-code"


def test_r10_passes_once_the_codes_are_in_the_low_byte(tmp_path):
    f = block_with([[0x0500]])
    dd2source.normalize_control_flags(f)
    write_pack(tmp_path, f)
    found = classcheck.control_flag_findings(str(tmp_path))
    assert [x for x in found if x["severity"] == "error"] == []


def test_r10_accepts_a_drawing_only_bank(tmp_path):
    # a bank with no keys on its roots at all is not this rule's business
    f = block_with([[]])
    write_pack(tmp_path, f)
    assert [x for x in classcheck.control_flag_findings(str(tmp_path))
            if x["severity"] == "error"] == []


def write_pack(root, anmf):
    folder = os.path.join(str(root), "files", "Anime", "ANM_HI_JP.dat")
    os.makedirs(folder, exist_ok=True)
    data = anmf.to_bytes()
    with open(os.path.join(folder, "anm01230.lzs"), "wb") as fh:
        fh.write(anm.lzs_compress(data))
