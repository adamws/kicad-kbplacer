# Examples

Each example has own directory with following file structure:

- `kle.json` - keyboard's layout downloaded from [keyboard-layout-editor](http://www.keyboard-layout-editor.com).
- `kle-internal.json` - keyboard's layout after processing with [kle-serial](https://github.com/ijprest/kle-serial).
  This file is expected by `kbplacer` plugin.
- `keyboard.net` - example's netlist.
- `keyboard-before.kicad_pcb` - PCB file with loaded netlist and parts placed
  at default location (by KiCad's netlist loader). This file is useful for manual
  testing of plugin's code changes.
- `keyboard-after.kicad_pcb` - PCB file after running plugin. Demonstrates
  current capabilities - this file does not contain any manual changes.
- `fp-lib-table` - footprints location file, points to external dependencies
  stored in parent's `libs` directory.
- `keyboard-layout.png` - picture of keyboard-layout-editor layout.
- `render.svg` - picture of PCB, this file is created by KiCad's SVG export.

## Examples summary

Name | Keyboard layout | PCB result
--- | --- | ---
2x2 (ok) | ![2x2-layout](./2x2/keyboard-layout.png) | ![2x2-after](./2x2/render.svg)
3x2-sizes (ok) | ![3x2-sizes-layout](./3x2-sizes/keyboard-layout.png) | ![3x2-sizes-after](./3x2-sizes/render.svg)<br/>Note that in this example `SW2` belongs to column 1 and `SW4&SW6` to column 2.
1x4-rotations-90-step (not ok) | ![1x4-rotations-90-step-layout](./1x4-rotations-90-step/keyboard-layout.png) | ![1x4-rotations-90-step-after](./1x4-rotations-90-step/render.svg)<br/>Diodes are not connected together.
2x3-rotations (not ok) | ![2x3-rotations-layout](./2x3-rotations/keyboard-layout.png) | ![2x3-rotations-after](./2x3-rotations/render.svg)<br/>Trace connecting `SW3` and `SW4` is excluded because it would be to close to drill hole. Placement is ok but some traces need to be added manually.
