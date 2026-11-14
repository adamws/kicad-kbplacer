$fn = $preview ? 0 : 100;


difference(){
	difference() {
		union() {
			linear_extrude(height = 3) {
				polygon(points = [[-13.01139197104675, -26.9492360742766], [108.21132963474386, -26.9492360742766], [108.21132963474386, 13.963891971046747], [-13.01139197104675, 13.963891971046747], [-13.01139197104675, -26.9492360742766]]);
			}
		}
	}
	/* Holes Below*/
	union(){
		translate(v = [0.0000000000, -0.0000000000, 0]) {
			rotate(a = -30) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [18.4311948892, -13.4788518927, 0]) {
			rotate(a = -45) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [77.0239643803, -13.4788518927, 0]) {
			rotate(a = 45) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [95.1999376637, 0.9525000000, 0]) {
			rotate(a = 30) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
	} /* End Holes */ 
}
