$fn = $preview ? 0 : 100;


difference(){
	difference() {
		union() {
			linear_extrude(height = 3) {
				polygon(points = [[118.108845726812, -132.05203820042829], [232.64999999999998, -132.05203820042829], [232.64999999999998, -95.54163522034969], [118.108845726812, -95.54163522034969], [118.108845726812, -132.05203820042829]]);
			}
		}
	}
	/* Holes Below*/
	union(){
		translate(v = [130.4030743609, -108.0028511525, 0]) {
			rotate(a = -30) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [147.8183766184, -120.0312229203, 0]) {
			rotate(a = -45) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [203.1816233816, -120.0312229203, 0]) {
			rotate(a = 45) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
		translate(v = [220.3557713659, -107.1528511525, 0]) {
			rotate(a = 30) {
				cube(center = true, size = [14, 14, 6]);
			}
		}
	} /* End Holes */ 
}
