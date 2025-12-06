# Tools

- `layout2image.py` - generate KLE style SVG image from keyboard layout
- `layout2url.py` - generate KLE url
- `layout2openscad.py` - generate plate for [openscad](https://openscad.org/) (:warning: experimental)

## How to run

The `kbplacer` project uses `pyprojet.toml` with [`hatch`](https://hatch.pypa.io) project manager.
It defines `tools` environment with required dependencies and scripts.
To execute, run:

```shell
$ hatch run tools:layout2image {args...}
$ hatch run tools:layout2url {args...}
$ hatch run tools:layout2openscad {args...}
```

Alternatively, install required dependencies and run as regular python script:

```shell
python tools/layout2image.py {args...}
python tools/layout2url.py {args...}
python tools/layout2openscad.py {args...}
```

## Examples

To generate layout image based on layout file:

```shell
hatch run tools:layout2image --in tests/data/ergogen-layouts/absolem-simple-points.yaml \
  --out absolem.svg
```

![absolem-svg](../resources/absolem.svg)

To generate KLE url for run:

```shell
hatch run tools:layout2url --in tests/data/ergogen-layouts/absolem-simple-points.yaml
```

This will produce following
[link](https://editor.keyboard-tools.xyz/#share=NrDeCICdwLgAgEwAYA0coA9aIHQGYBWPAdgBYAONKAT2yR1OLwDZzSqt4BaexltqrW68mrdugCG2YlQDudHAE4+rKgAsFy0eQC+VcAF0UAKDBRsXZFUic4ARnrlyxJnY4WR-ceCFweDbW95eHotfnVNFV19I1MIaHgrdBtsPHxyPFJSZmtfegIxOxl0W38o718ywLlI7QiQpSi9dEMTMwS-JMxsRRxyAnIkPDx3YQCvQQ9xsRqGsNV0DTmmmLb47DsCa1tQxTs8BARchWZFFmIckqnyybGb9GC4UKj6p8btZvBWuPNuTe2NggcAgCEhNsVwKVPDN0JVoQIHrVwoskaxPt92tguil4KRgZt9kdkr47MCkMQ7OQiZDrtVYbSJojlnUUcz+OjYpjuNjbL0kAhmJkIVDpgifAyYeBHs8WeAlm95tEWpz1olUMlbECwUUEJRiRsGPsSMKJWK4aKgqi9XKrRy1r9OuruvA7KTDopiAQ3Fc7nTxb7GVKra8ZezVj8OjzUjgkKQ7KQBccXThQeQHIpRn54RVTZa2QsbfmlV8VQ7LE6cfZ6MgkEgCN4Rfd-VmLbMFS9We2PuGuYgK7YCDhXU5Dkn7DhmBRXSaA5LzU3pe9kYWu2HlfaOuWAfByEPDswCDOW03537F4qQ0u0T3VfYthqFEwQUMx6SD4pmPzM1VA6fA+eOxXUNr3XCMLH+B8XSBVMPUuGlZzNXM22A615RQu0wLVbc4DSZw8FdalIF8IF41YT1v2zW5jzPYNO3Qm8yyjeBen4c4KNbekELzVcCzQq9iwxW8mPHZhTmIckxyBQg8CQU52JPJCmR41DbQYzdhNdFMKRcalGz9P9JQA2U+MVDDe2EoFTmUOtJIYRhBl0xTmx-QzaKA-izNvLdIKrFME3JBsnIMsUjOXEyVlA8z+2wPEXFYL99USFNnDTeT9Kc0LeNUyKvOE3dsmyFw0t-DK3PC7scodCDnTeJsiKxCcQQIXVirnUqi0vUy1PA+8arsIELhcRRer0kquOQ-jOoiksNyxaL4DSIh00I3w0iQcgD2YI8XMQ8alJQqaKpmzDHWw3oKSGZxWt26j-zK7Ljqi7C8VIIUqTHRaEE9BL4Nutq9qDDq6I87ruXmuBd0GUSPWunMAcylSi08h1hLSMgDwIDNErgPFMmHa1Rv+v6QvupHQdOnzelIZRFEcgHgu4g7ga6yqOgoZ6+mQBAijHQckEUAXCFhqidsZybmemwSy3Znz8u5gU6eJuGlYmi8JaOqWOgubDB2yEFrXq+BmGBRh+W9X7RZFyj9vF9yWcerztZ84gcBcJwBeFziVZttW7clgwDCAA).

To convert `ergogen` layouts to KLE see [layout and format conversion script](../README.md#layout-format-conversion-script)

> [!WARNING]
> Tools are not yet part of `kbplacer` package and are tested mostly by-hand.
> To execute limited tests we have run `hatch run tools:test`.
