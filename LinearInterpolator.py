class LinearInterpolator:
    def __init__(self, points, min_dx = 1, min_dy = 1, max_points = None):
        self.points = sorted((int(x), int(y)) for x, y in points)
        self.points[1] # assert len(self.points) > 1
        self.min_dx = min_dx
        self.min_dy = min_dy
        self.max_points = max_points

    def add_point(self, x, y, monotonic):
        # Always preserve end points.
        if not self.points[0][0] < x < self.points[-1][0] or not self.points[0][1] < y < self.points[-1][1] or not self.max_points:
            return
        # Remove old values which are too close or non-monotonic.
        for i in reversed(range(1, len(self.points) - 1)):
            x0, y0 = self.points[i]
            if (monotonic and (x < x0) != (y < y0)) or abs(x - x0) < self.min_dx or abs(y - y0) < self.min_dy:
                self.points.pop(i)
        if len(self.points) < self.max_points:
            self.points.append((x, y))
            self.points.sort()

    def value_at(self, x):
        i0, i1 = 0, len(self.points) - 1
        while i1 - i0 > 1:
            i = (i1 + i0) >> 1
            xi, yi = self.points[i]
            if xi == x:
                return yi
            if xi < x:
                i0 = i
            else:
                i1 = i
        x0, y0 = self.points[i0]
        x1, y1 = self.points[i0 + 1]
        return y0 + (y1 - y0) * (x - x0) // (x1 - x0)
