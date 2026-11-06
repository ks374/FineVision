"""Frame-counted optical codes; advance once per subject flip."""


class DisplaySync:
    """5 white / 5 black / 5 white startup, then mirror stimulus visibility."""
    SPEC = {"startup": [5, 5, 5], "startup_levels": ["white", "black", "white"],
            "mode": "continuous_visibility"}

    def __init__(self):
        self.index = None
        self.is_on = False
        self.label = None

    @property
    def busy(self):
        return self.index is not None

    def start(self, label):
        if label != "TASK_START" or self.busy:
            raise ValueError("Only the startup sequence can be requested")
        self.index = 0

    def next_frame(self, visible=False, label="STIMULUS"):
        if self.index is not None:
            i = self.index
            visible = i < 5 or 10 <= i < 15
            label = "TASK_START_1" if i < 10 else "TASK_START_2"
            self.index = i + 1 if i < 15 else None
        edge = "ON" if visible and not self.is_on else "OFF" if self.is_on and not visible else None
        if edge == "OFF":
            label = self.label
        self.is_on = visible
        self.label = label
        return visible, edge, label


class FramePulse:
    CODES = {"TASK_START": 1, "TRIAL_START": 3, "NOFIX": 5,
             "BREAK": 7, "SUCCESS": 9}

    def __init__(self, gap_frames=3):
        self.gap_frames = gap_frames
        self.remaining = self.gap_remaining = 0
        self.label = None
        self.is_on = False

    @property
    def busy(self):
        return self.remaining > 0 or self.is_on or self.gap_remaining > 0

    def start(self, label):
        if self.busy:
            raise RuntimeError("Finish the pulse and black gap before starting another")
        self.label = label
        self.remaining = self.CODES[label]

    def next_frame(self):
        """Return (white, edge, label) for the frame about to be flipped."""
        if self.remaining:
            edge = "ON" if not self.is_on else None
            self.is_on = True
            self.remaining -= 1
            return True, edge, self.label
        if self.is_on:
            self.is_on = False
            self.gap_remaining = self.gap_frames - 1
            return False, "OFF", self.label
        if self.gap_remaining:
            self.gap_remaining -= 1
        return False, None, self.label
