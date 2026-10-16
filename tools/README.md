# Tools

- `layout2image.py` - generate KLE style SVG image from keyboard layout
- `layout2openscad.py` - generate plate for [openscad](https://openscad.org/) (:warning: experimental)
- `profiling/kle-ng-api-task.sh` - reproduce a complete kle-ng-api task (schematic + pcb) for memory profiling

## Memory profiling (memray)

`profiling/kle-ng-api-task.sh` runs one `kbplacer` process with both
`--create-sch-file` and `--create-pcb-file`, mirroring the arguments
`kle-ng-api` builds for a single generation request. It is meant to estimate the
peak memory of a complete task (useful for sizing worker memory limits, since
KiCad's `pcbnew` SWIG bindings have historically leaked). Run it under
[memray](https://github.com/bloomberg/memray) inside docker with:

```shell
just profile-memray                  # KiCad 9.0.9, full routing (worst case)
just profile-memray 10.0.3-noble     # different KiCad version
just profile-memray 9.0.9-noble none # disable routing
```

Outputs land in `./output_memray/`: `profile.bin`, `flamegraph.html` (peak
usage) and `flamegraph-leaks.html` (memory still allocated at exit). The recipe
also prints `memray summary`/`stats`, whose peak/high-water-mark is the number
to compare against the container memory limit.

## How to run

The `kbplacer` project uses `pyprojet.toml` with [`hatch`](https://hatch.pypa.io) project manager.
It defines `tools` environment with required dependencies and scripts.
To execute, run:

```shell
$ hatch run tools:layout2image {args...}
$ hatch run tools:layout2openscad {args...}
```

Alternatively, install required dependencies and run as regular python script:

```shell
python tools/layout2image.py {args...}
python tools/layout2openscad.py {args...}
```

## Examples

To generate layout image based on layout file:

```shell
hatch run tools:layout2image --in tests/data/ergogen-layouts/absolem-simple-points.yaml \
  --out absolem.svg
```

![absolem-svg](../resources/absolem.svg)

To convert `ergogen` layouts to KLE see [layout and format conversion script](../README.md#layout-format-conversion-script)

> [!WARNING]
> Tools are not yet part of `kbplacer` package and are tested mostly by-hand.
> To execute limited tests we have run `hatch run tools:test`.
