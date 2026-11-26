"""Run the shared static-stack audit unchanged, keeping its receipt inside this worktree.

The shared script writes beside __file__; this runner supplies its own location as that
output anchor while compiling the shared source unchanged. No Unicorn is imported.
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
