# source_trace (SOURCEPREP1)

Traces every file an offline import opens, to inventory what lives outside the kit.

    TRACE_DIR=/path/to/empty PYTHONPATH=<kit>/tools/source_trace .venv-macos/bin/python tools/import_game.py d4 --only D4_Class_1080 --out OUT --jobs 1
    python -I tools/source_trace/classify.py /path/to/empty OUT.json --sums "<Disgaea Source>/SHA256SUMS-20261102.txt" --skip OUT

`sitecustomize.py` only acts when `TRACE_DIR` is set; it adds a Python audit hook (open, listdir/scandir, Popen)
and writes `<pid>.log`, so child processes the importers start are traced too. It records paths only,
never file contents. Reads only; it changes no kit behaviour.
