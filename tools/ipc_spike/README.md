# IPC API feasibility probes (migration plan, chunk 0)

Throwaway probes behind `docs/ipc-migration-spike-0.md`. Re-run them when a newer KiCad
nightly or `kicad-python` is available, and compare against the committed `results_*.json`.

- `probe_basic.py`, `probe_followup.py`: kipy against headless `kicad-cli api-server`
- `probe_batching.py`: request counts, commits, partial failures and W11 (write model W1–W11
  in `docs/ipc-migration-plan.md`)
- `swig_reference.py`: kbplacer's own SWIG transforms on KiCad 10, the reference for the IPC
  transform results

The IPC probes run in the CI nightly image, which ships kicad-python (pinned in
`.circleci/images/jammy/nightly.Dockerfile`). Pull it, or rebuild it locally after changing
the Dockerfile:

```sh
docker pull admwscki/kicad-kbplacer-primary:nightly-jammy
# or: docker build -t admwscki/kicad-kbplacer-primary:nightly-jammy \
#       -f .circleci/images/jammy/nightly.Dockerfile .circleci/images/jammy
docker run --rm -v $(pwd):/repo -w /repo admwscki/kicad-kbplacer-primary:nightly-jammy \
  python3 tools/ipc_spike/probe_basic.py /repo /tmp/out
docker run --rm -v $(pwd):/repo -w /repo admwscki/kicad-kbplacer-primary:10.0.6-noble \
  python3 tools/ipc_spike/swig_reference.py
```

`swig_reference.py` reads boards from `/repo`; mount the project root there.
