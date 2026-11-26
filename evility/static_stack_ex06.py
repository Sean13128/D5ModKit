"""Run the shared static-stack audit unchanged for EX-06.

The section's *code* does not depend on the table's contents (only its data words do), so the audit that
covers the new skill-match branch and the skill pass is the same audit the earlier cards ran: the shared
script builds the section, follows every call/branch from each wrapper entry and each internal call
target, and checks alignment, home-space clearance, returns and rsp writes.

The shared script writes beside __file__; this runner supplies its own location as that output anchor
while compiling the shared source unchanged. No Unicorn is imported.
"""
from pathlib import Path


if __name__ == "__main__":
    worktree = Path(__file__).resolve().parents[1]
    workspace = worktree.parents[2]
    source = workspace / "Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py"
    namespace = {"__name__": "__main__", "__file__": __file__, "__argv": None}
    import sys
    sys.argv = [str(source), worktree.name]
    exec(compile(source.read_text(), str(source), "exec"), namespace)
