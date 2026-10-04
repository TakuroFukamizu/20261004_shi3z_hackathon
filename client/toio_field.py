"""Mat geometry for the toio hub: bounds, grid cells, and the checks a target must pass."""
import math

MARGIN = 15    # a target must be this far inside the mat edge (mat units, 1 unit = about 1.38 mm)
MIN_GAP = 35   # a target must be this far from other cubes and other targets (a cube is about 23 units)


class Mat:
    def __init__(self, x_min, y_min, x_max, y_max, cols=None, rows=None):
        self.x_min, self.y_min, self.x_max, self.y_max = x_min, y_min, x_max, y_max
        self.cols, self.rows = cols, rows

    def contains(self, x, y, margin=MARGIN):
        return (self.x_min + margin <= x <= self.x_max - margin
                and self.y_min + margin <= y <= self.y_max - margin)

    def _cell_size(self):
        if not self.cols or not self.rows:
            raise ValueError("this mat has no grid; use x and y")
        return (self.x_max - self.x_min) / self.cols, (self.y_max - self.y_min) / self.rows

    def cell_center(self, col, row):
        """Centre of a cell. col counts from the left, row from the top, both from 1."""
        w, h = self._cell_size()
        if not (1 <= col <= self.cols and 1 <= row <= self.rows):
            raise ValueError("cell must be col 1..%d, row 1..%d" % (self.cols, self.rows))
        return round(self.x_min + (col - 0.5) * w), round(self.y_min + (row - 0.5) * h)

    def cell_of(self, x, y):
        """(col, row) containing a point, or None if off the mat or the mat has no grid."""
        if not self.cols or not self.rows:
            return None
        if not (self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max):
            return None
        w, h = self._cell_size()
        return (min(self.cols, int((x - self.x_min) / w) + 1),
                min(self.rows, int((y - self.y_min) / h) + 1))


def check_targets(mat, targets, obstacles=()):
    """targets: {cube id: (x, y)}. obstacles: [(label, x, y)]. Returns an error string, or None if fine."""
    for cid, (x, y) in targets.items():
        if not mat.contains(x, y):
            return "cube %s: target (%d, %d) is outside the mat" % (cid, x, y)
    items = list(targets.items())
    for i, (a, (ax, ay)) in enumerate(items):
        for b, (bx, by) in items[i + 1:]:
            if math.hypot(ax - bx, ay - by) < MIN_GAP:
                return "cubes %s and %s: targets are too close together" % (a, b)
        for label, ox, oy in obstacles:
            if math.hypot(ax - ox, ay - oy) < MIN_GAP:
                return "cube %s: target is too close to %s" % (a, label)
    return None
