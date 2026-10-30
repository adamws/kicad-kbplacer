# Tests

To run tests with local changes, run from project root directory:

```
docker run --rm -v $(pwd):$(pwd) -w $(pwd) admwscki/kicad-kbplacer-primary:10.0.4-noble \
  /bin/bash -c "pip3 install --no-cache-dir hatch && hatch run test:test"
```

or use [just](https://github.com/casey/just) `test` recipe.

## Board snapshots

Example tests (`test_with_examples.py`) compare the produced board with a JSON snapshot
(`board_snapshot.py`: footprints with absolute pad positions and nets, tracks, vias,
Edge.Cuts outline), next to the SVG references. Snapshots are recorded on KiCad 10 only
(`tests/data/examples-references/kicad10/**/<test name>.snapshot.json`) and every other
version is compared against them. Regenerate them on KiCad 10 with:

```
docker run --rm -v $(pwd):$(pwd) -w $(pwd) admwscki/kicad-kbplacer-primary:10.0.7-noble \
  /bin/bash -c "pip3 install --no-cache-dir hatch && \
    hatch run test:test --save-snapshots-as-reference tests/test_with_examples.py"
```

The actual snapshot of each run is saved in the test's `report` directory.
