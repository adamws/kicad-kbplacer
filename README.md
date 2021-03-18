# kicad-kbplacer

[![CircleCI](https://img.shields.io/circleci/build/github/adamws/kicad-kbplacer)](https://circleci.com/gh/adamws/kicad-kbplacer/tree/master)
[![CircleCIReport](https://img.shields.io/badge/build-report-informational)](https://circleci.com/api/v1.1/project/github/adamws/kicad-kbplacer/latest/artifacts/0/report.html)

KiCad plugin for mechanical keyboard design. It features automatic key placement
based on popular layout description from [keyboard-layout-editor](http://www.keyboard-layout-editor.com/)

## Motivation

All PCB's for mechanical keyboards shares common properties which creates great
opportunity for scripting. Although this project does not aim to provide
complete automatic PCB generation tool it speeds up development process
by reducing tidiuos element placement task.

## Features

- [x] Automatic keys and diodes placement
- [x] Support for different annotation schemes
- [x] Basic track routing
- [x] Key rotation support
- [ ] User selectable diode position in relation to key position

![demo](demo.gif)

## Installation

- Clone this repository
- Copy `keyautoplace.py` (or create symbolic link) to one of the KiCad's plugin
  search locations. For details see [kicad documentation](https://docs.kicad-pcb.org/doxygen/md_Documentation_development_pcbnew-plugins.html)
- Open KiCad's Pcbnew, run `Tools->External Plugins...->Refresh Plugins`.
  KeyAutoPlace plugin should appear in plugin list.

## How to use?

### Direct usage

- Create new PCB and load netlist
- Obtain [kle-serial](https://github.com/ijprest/kle-serial) compatible layout
  json file (**note**: this is not json which can be downloaded directly from [keyboard-layout-editor](http://www.keyboard-layout-editor.com/)
  website. Expected json format can be seen in `examples` directory.

  For conversion you can use [https://adamws.github.io/kle-serial](https://adamws.github.io/kle-serial/)
  or [keyboard-tools.xyz/kle-converter](http://keyboard-tools.xyz/kle-converter)
- Run KeyAutoPlace plugin
- Select desired json file and click OK.

### As a service

This plugin is part of my another project. See [keyboard-tools](https://github.com/adamws/keyboard-tools)

## Troubleshooting

- See stacktrace
- See created `keyautoplace.log` file (in PCB directory)

## Known bugs and limitations

- Tested only with SOD-323F diodes. Predefined diode location might not be
  suitable for larger footprints and custom location is not supported without
  code modification
- Tested only with KiCad version 5.1.5

