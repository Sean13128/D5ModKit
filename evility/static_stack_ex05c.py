"""Run the shared audit unchanged, keeping its receipt inside this worktree.

The shared script writes beside __file__. Supply this runner's location as that
output anchor; the source itself is compiled unchanged. No Unicorn is imported.
"""
from pathlib import Path
import sys


if __name__ == "__main__":
    worktree = Path(__file__).resolve().parents[1]
    workspace = worktree.parents[2]
    source = workspace / "Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py"
    sys.argv = [str(source), worktree.name]
    namespace = {"__name__": "__main__", "__file__": __file__}
    exec(compile(source.read_text(), str(source), "exec"), namespace)
