# ![icon](resources/icon-github.png) kicad-kbplacer

[![KiCad Repository](https://img.shields.io/badge/KiCad-Plugin%20Repository-blue)](https://gitlab.com/kicad/addons/metadata/-/tree/main/packages/com.github.adamws.kicad-kbplacer)
![Downloads](https://img.shields.io/github/downloads/adamws/kicad-kbplacer/total)
[![CircleCI](https://circleci.com/gh/adamws/kicad-kbplacer.svg?style=shield)](https://circleci.com/gh/adamws/kicad-kbplacer/tree/master)
[![PyPI](https://img.shields.io/pypi/v/kbplacer?color=44CC11)](https://pypi.org/project/kbplacer/)
[![Coverage Status](https://coveralls.io/repos/github/adamws/kicad-kbplacer/badge.svg?branch=master)](https://coveralls.io/github/adamws/kicad-kbplacer?branch=master)
[![Weblate](https://hosted.weblate.org/widgets/kicad-kbplacer/-/master-source/svg-badge.svg)](https://hosted.weblate.org/engage/kicad-kbplacer/)

KiCad plugin for mechanical keyboard design. It features automatic key placement
based on popular layout descriptions from [keyboard-layout-editor](http://www.keyboard-layout-editor.com/)
and [ergogen](https://github.com/ergogen/ergogen).

**Table of Contents**
- [Motivation](#motivation)
- [Features](#features)
- [Installation](#installation)
  - [As KiCad plugin](#installation-as-kicad-plugin)
  - [As python package](#installation-as-python-package)
- [How to use](#how-to-use)
  - [Direct usage](#direct-usage)
    - [Diode placement and routing](#diode-placement-and-routing)
    - [Additional elements placement](#additional-elements-placement)
    - [Track templating](#track-templating)
    - [Run without layout](#run-without-layout)
    - [Demo project](#demo-project)
  - [As python package](#as-python-package-usage)
    - [Run as a script](#run-as-a-script)
  - [As a service](#as-a-service)
- [Troubleshooting](#troubleshooting)
  - [Plugin does not load](#plugin-does-not-load)
  - [Plugin misbehaves or crashes](#plugin-misbehaves-or-crashes)

<!-- TOC --><a name="motivation"></a>
## Motivation

All PCB's for mechanical keyboards shares common properties which creates great
opportunity for scripting. Although this project does not aim to provide
complete automatic PCB generation tool it speeds up development process
by reducing tedious element placement and routing tasks.

<!-- TOC --><a name="features"></a>
## Features

- [x] Automatic keys and diodes placement
- [x] Key rotation support
- [x] Basic track routing
- [x] User selectable diode position in relation to key position
- [x] Configurable additional elements placement

> [!WARNING]
> Ergogen support is new experimental feature and it has not been tested extensively

![demo](resources/demo.gif)

Some examples can be found in [examples](./examples) directory.

<!-- TOC --><a name="installation"></a>
## Installation

<!-- TOC --><a name="installation-as-kicad-plugin"></a>
### As KiCad plugin

To install release version of this plugin, use KiCad's `Plugin and Content Manager`
and select `Keyboard footprints placer` from official plugin repository.

![pcm](resources/pcm.png)

To install development version, see how to use [custom plugin repository](./docs/custom_repository.md).
Custom repository is automatically updated with latest `master` branch builds
and it is available [here](https://adamws.github.io/kicad-kbplacer).

For development activities, it is recommended to checkout this repository and copy (or link)
content of `kbplacer` directory to one of the KiCad's plugin search paths.
For more details see [this](https://dev-docs.kicad.org/en/python/pcbnew/) guide.

After installation, plugin can be started by clicking plugin icon on the toolbar:

![plugin-icon-on-toolbar](resources/plugin-icon-on-toolbar.png)

or selecting it from `Tools -> External Plugins` menu.
For more details about plugin usage see [direct usage](#direct-usage) section.

<!-- TOC --><a name="installation-as-kicad-package"></a>
### As python package

The `kbplacer` can be installed with pip:

```shell
pip install kbplacer
```

When installed this way, it **can't** be launched from KiCad as KiCad plugin.
This option exist for usage via command line interface.
Command line interface provides more options but generally it is recommended for
more advanced users. For example it allows to create PCBs without schematic,
which is non-typical KiCad workflow.
For more see [usage as python package](#as-python-package-usage) section.

> [!IMPORTANT]
> Most of the `kbplacer` python package functionalities depends on `pcbnew` package
> which is distributed as part of KiCad installation.
> This means, that on Windows it is **required** to use python bundled with KiCad.
> On Linux, `pcbnew` package should be available globally (this can be verified by
> running `python -c "import pcbnew; print(pcbnew.Version())"`) so it may not work
> inside isolated environment. To install inside virtual environment created with `venv`
> it is required to use `--system-site-package` option when creating this environment.

> [!NOTE]
> Both installation methods can be used simultaneously. When installed as KiCad plugin,
> some scripting capabilities are still available, but in order to use `kbplacer`
> in another python scripts, installing as python package is required.

<!-- TOC --><a name="how-to-use"></a>
## How to use?

<!-- TOC --><a name="direct-usage"></a>
### Direct usage

This is _traditional_ way of using this tool. Before it can be used on `kicad_pcb` project
file, user needs to create it and populate with footprints. In typical KiCad workflow
this is started by creating schematic. When PCB file is ready, user can start `kbplacer`
plugin in GUI mode from KiCad and run it with selected options.
To use this tool in this way, it needs to be installed following [plugin installation guide](#as-kicad-plugin).

- Create switch matrix schematic which meets following requirements:
  - Each switch has dedicated diode with same annotation number
  - Symbols are ordered by Y position
  - Diodes are column-to-row configuration (COL = Anode, ROW = Cathode)

  ![schematic-example](resources/schematic-example.png)

  > [!NOTE]
  > Other matrix configurations are also supported. Track router will attempt
  > to connect closest (to each other) pads of switch and diode as long as both
  > have same `netname`, i.e. are connected on the schematic

- Create new PCB and load netlist
- Obtain json layout file from [keyboard-layout-editor](http://www.keyboard-layout-editor.com/) or
  convert [ergogen](https://github.com/ergogen/ergogen) points file to json

  <details>
  <summary>keyboard-layout-editor details</summary>

    ![kle-download](resources/kle-download.png)

    Plugin supports internal [kle-serial](https://github.com/ijprest/kle-serial) layout files
    and [via](https://www.caniusevia.com/docs/layouts) files.
    Detection of layout format will be done automatically.
    Conversion between layout downloaded from keyboard-layout-editor and its internal form
    can be done with [https://adamws.github.io/kle-serial](https://adamws.github.io/kle-serial/)
    or [keyboard-tools.xyz/kle-converter](http://keyboard-tools.xyz/kle-converter)

    > [!NOTE]
    > When using `via` layouts, switch matrix **must** be annotated according to `via` rules.
    > If layout supports [multiple layout of keys](https://www.caniusevia.com/docs/layouts#layout-options)
    > only the default one will be used by `kicad-kbplacer`.

  </details>

  <details>
  <summary>ergogen details</summary>

    - open your design in https://ergogen.cache.works/ and download `points.yaml`

      ![ergogen-points](resources/ergogen-points.png)

    - convert `yaml` to `json` (this operation is not integrated with `kicad-kbplacer` source
      because it would require installation of third-party `pyyaml` package and there is no
      good way to manage plugin dependencies yet)
      - you can use online converter, for example https://jsonformatter.org/yaml-to-json
    - converted file should be automatically recognized in next steps

  </details>

- Run `kicad-kbplacer` plugin
- Select json layout file and plugin options and click OK.

  ![plugin-gui](resources/plugin-gui.png)

It is possible to run this plugin from command line. Everything which can be done via GUI can
be also achieved using command line.
Execute following command (in the directory where plugin is installed) to get more details:

```
python -m com_github_adamws_kicad-kbplacer --help
```

> [!IMPORTANT]
> On windows, use python bundled with KiCad

<!-- TOC --><a name="diode-placement-and-routing"></a>
#### Diode placement and routing

By default diodes are placed like shown below. This placement may not work for all switch and diode
footprints combinations.

Before | After
--- | ---
![default-before](resources/default-before.png) | ![default-after](resources/default-after.png)

To use custom diode position there are two available options. Either select `Custom` in `Position` dropdown
and define `X/Y offset`, `Orientation` and `Front` or `Back` side:

  ![custom-position-example](resources/custom-position-example.png)

or manually place `D1` diode to desired position in relation to first switch and run plugin with
`Current relative` `Position` option selected.

  ![current-relative-position-example](resources/current-relative-position-example.png)

Remaining switch-diode pairs will be placed same as the first one.

Before | After
--- | ---
![custom-before](resources/custom-before.png) | ![custom-after](resources/custom-after.png)

Some custom diodes positions may be to difficult for router algorithm.
In the above example it managed to connect diodes to switches but failed to connect diodes together.

Switch-to-diode routing is not done with proper auto-routing algorithm and it is very limited.
It attempts to create track in the shortest way (using 45&deg; angles) and doesn't look for other options
if there is a collision, leaving elements unconnected.

<!-- TOC --><a name="track-templating"></a>
#### Track templating

If first switch-diode pair is routed before plugin execution, as shown below, `kicad-kbplacer` instead of
using it's built in routing algorithm, will copy user's track. This allow to circumvent plugin's router
limitations. This is applicable only for `Current relative` `Position` option.

Before | After
--- | ---
![custom-with-track-before](resources/custom-with-track-before.png) | ![custom-with-track-after](resources/custom-with-track-after.png)

<!-- TOC --><a name="additional-elements-placement"></a>
#### Additional elements placement

In case additional elements need to be automatically placed next to corresponding switches (for example
stabilizer footprints if not integral part of switch footprint, or RGB LEDs), define entries
in `Additional elements settings` section. It behaves very similarly to switch diodes options with few exceptions:

- there is no default position defined
- when footprint not found, algorithm proceeds. There is no 1-to-1 mapping required
- there is no track routing

<!-- TOC --><a name="run-without-layout"></a>
#### Run without layout

Creating tracks does not require layout file. `Keyboard layout file` field can be empty
when `Route tracks` option enabled. Plugin will attempt to create tracks for already placed
elements without moving them. This might be useful for PCB files generated by other tools,
for example [ergogen](https://github.com/ergogen/ergogen).

<!-- TOC --><a name="demo-project"></a>
#### Demo project

For example demo project see `demo` directory. This project contains 4x4 switch matrix with
layout json files in raw (`kle.json`) and internal (`kle_internal.json`) formats.
It requires [keyswitch-kicad-library](https://github.com/perigoso/keyswitch-kicad-library) to be installed.
Use this project to validate plugin installation.

<!-- TOC --><a name="as-python-package-usage"></a>
### As python package

For advanced users who want to integrate `kbplacer` with other tools or automate it's usage
there is an option to install this tool as python package. For details see
[installation as python package](#installation-as-python-package) section.

When installed, `kbplacer` may be used for parsing raw KLE data to it's internal form:

``` python
from kbplacer.kle_serial import parse_kle
keyboard = parse_kle([["", ""]])
print(f"This keyboard has only {len(keyboard.keys)} keys")
```

It can also create and manipulate `kicad_pcb` files. This enables _non traditional_ KiCad workflows
where schematic preparation can be completely skipped. For example see
[keyboard-pcbs](https://github.com/adamws/keyboard-pcbs/blob/master/via_layouts_to_boards.py) repository. It demonstrates how to create `.kicad_pcb` file with switch matrix from scratch.

> [!WARNING]
> This is work in progress. Creating keyboard PCBs without schematic is not recommended
> for inexperienced users. Internal `kbplacer` API is not stable.

<!-- TOC --><a name="run-as-a-script"></a>
#### Run as a script

The `kbplacer` module might be executing as a script using python's `-m` command line option.

```shell
python -m kbplacer
```

This is command line equivalent of running this tool as KiCad plugin with GUI interface.
Run it with `--help` option to get more details.

<!-- TOC --><a name="as-a-service"></a>
### As a service

This plugin is part of my another project. See [keyboard-tools](https://github.com/adamws/keyboard-tools) for more details.

<!-- TOC --><a name="troubleshooting"></a>
## Troubleshooting

<!-- TOC --><a name="plugin-does-not-load"></a>
### Plugin does not load

If plugin does not appear on the `Tools -> External Plugins` menu and its icon is missing on toolbar,
launch python scripting console `Tools -> Scripting Console` and type:

```
import pcbnew; pcbnew.GetWizardsBackTrace()
```

This should return backtrace with an information about the fault. Include this information in bug report.

<!-- TOC --><a name="plugin-misbehaves-or-crashes"></a>
### Plugin misbehaves or crashes

- Read stacktrace in error pop-up
- See `kbplacer.log` file, created in PCB directory

For bug reports please use [this template](https://github.com/adamws/kicad-kbplacer/issues/new?template=bug_report.md).

