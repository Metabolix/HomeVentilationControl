from time import ticks_ms, ticks_diff

class Timestamp:
    """Easily store timestamps and check elapsed time.

    Create x = Timestamp(), check x.between(0, 10_000).
    Create x = Timestamp(10_000), check x.passed().
    Create x = Timestamp(), set x.set_valid_between(0, 60_000), check x.valid().
    Create x = Timestamp(), read x.ms().

    All values must be below 86400_000 ms (1 day). Days are counted for printing.
    """

    def __init__(self, offset = 0):
        self.empty = offset is None
        self._valid_ms_0 = self._valid_ms_1 = None
        if not self.empty:
            self._ticks_ms = ticks_ms()
            self._ms = -offset
            self._days = 0

    def between(self, ms_0, ms_1):
        return self.update() and not self._days and ms_0 <= self._ms <= ms_1

    def passed(self):
        return self.update() and self._ms >= 0

    def ms(self):
        return self.update() and self._days * 86400_000 + self._ms

    def set_valid_between(self, ms_0, ms_1):
        self._valid_ms_0, self._valid_ms_1 = ms_0, ms_1
        self.valid()

    def valid(self):
        u = self.update()
        self._valid_0 = u and (self._valid_ms_0 is None or self._days or self._ms >= self._valid_ms_0) and True or False
        self._valid_1 = u and (self._valid_ms_1 is None or (not self._days and self._ms <= self._valid_ms_1)) and True or False
        return self._valid_0 and self._valid_1

    def update(self):
        if not self.empty:
            t = ticks_ms()
            self._ms += ticks_diff(t, self._ticks_ms)
            if self._ms >= 86400_000:
                self._days += 1
                self._ms -= 86400_000
            self._ticks_ms = t
            return True

    def __str__(self):
        def timestr(ms, d = 0):
            h = ms // 3600_000
            m = (ms - 3600_000 * h) // 60_000
            s = (ms - 3600_000 * h - 60_000 * m) // 1_000
            if d:
                return f"{d} days, {h:02}:{m:02}:{s:02}"
            if h or m:
                return f"{h:02}:{m:02}:{s:02}"
            ms = ms - 1_000 * s
            return f"{s}.{ms:03}"
        if self.empty:
            return "None"
        # FIXME: In some use cases, updating the timestamp here
        # can lead to discrepancy between logic and debug prints;
        # in others, not updating will keep it at 0.000 forever.
        # Crude heuristic: if validity checking is used, don't update here.
        if self._valid_ms_0 is self._valid_ms_1 is None:
            self.update()
        if self._ms < 0:
            return "<0"
        t = timestr(self._ms, self._days)
        if self._valid_ms_0 is not None and not self._valid_0:
            return t + " (<" + timestr(self._valid_ms_0) + ")"
        if self._valid_ms_1 is not None and not self._valid_1:
            return t + " (>" + timestr(self._valid_ms_1) + ")"
        return t
