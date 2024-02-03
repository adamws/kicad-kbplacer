# Annotation guide

Since [keyboard-layout-editor](http://www.keyboard-layout-editor.com/) layout
files contain only informations about the key location and its
appearance (like size, color and labels) the `kbplacer` plugin
must use some assumptions in order to find corresponding
footprints on the PCB.

This guide explains the process, show common problems and describes
possible solutions.

## Common scenarios

### Schematic order matches KLE key order

Following example show schematic and KLE image
with key labels which represent internal KLE ordering.

![annotation-guide-1](../resources/annotation-guide-1.png)

This is the simplest case which should not require any adjustments
as long as KiCad symbols are sorted by Y position.
The `kbplacer` plugin process keys in KLE order, which in this example
matches schematic ordering. This will be the case for
ortholinear and row staggered keyboards.

### Schematic order does not match KLE key order

Let's consider column staggered keyboard layout with same schematic
as in previous chapter.

![annotation-guide-2](../resources/annotation-guide-2.png)

Note that keys in KLE picture are in different order now.
That's because KLE uses topmost leftmost sorting.
Since `kbplacer` uses KLE order the placement on the PCB board would
be wrong:

![annotation-guide-3](../resources/annotation-guide-3.png)

In this simple example, only the order of two first columns
would be wrong but the effect might be amplified with more
complicated ergo layouts.

There are two ways to ensure matching order between schematic and KLE:

1. Adjust elements placement on the schematic to resemble physical layout
   of the switches. This way KiCad Y position annotation assignment will match
   KLE behaviour. Key matrix on the schematic is usually drawn
   in uniform grid for readability, this solution might be suitable for simple
   column staggered designs:

   ![annotation-guide-4](../resources/annotation-guide-4.png)

   Changing annotations by hand would also work but it is prone to breaking when
   running KiCad automatic re-annotation with `Keep existing annotations`
   option disabled.

2. Define expected annotation in KLE layout. This is called `explicit annotation`
   mode by `kbplacer`.

   If **all of the switches** in the provided layout file
   have digit-only front center label defined, then these numbers will used
   for searching footprints, for example:

   ![annotation-guide-5](../resources/annotation-guide-5.png)

   Note that labels in previous examples were used only for demonstrating
   how keys are ordered by KLE. If user specifies front center labels like
   in the above picture, then it takes priority over default (KLE) ordering.
   The front center label has been chosen because it is unlikely that it
   interferes with already defined layouts.
