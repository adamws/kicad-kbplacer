$fn = $preview ? 0 : 100;


difference(){
	difference() {
		union() {
			linear_extrude(height = 3) {
				polygon(points = [[0.0, -71.4375], [0.0, 0.0], [61.9125, 0.0], [61.9125, -19.05], [52.3875, -57.150000000000006], [19.05, -71.4375], [0.0, -71.4375]]);
			}
		}
	}
	/* Holes Below*/
	union(){
		translate(v = [9.5250000000, -9.5250000000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
		translate(v = [38.1000000000, -9.5250000000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
		translate(v = [21.4312500000, -28.5750000000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
		translate(v = [42.8625000000, -28.5750000000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
		translate(v = [9.5250000000, -50.0062500000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
		translate(v = [30.9562500000, -47.6250000000, 0]) {
			cube(center = true, size = [14, 14, 6]);
		}
	} /* End Holes */ 
}
