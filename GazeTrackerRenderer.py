from collections import deque

from psychopy import event, visual


class GazeTrackerRenderer:
    """Draw the operator gaze cursor and return task-space gaze samples."""

    def __init__(
        self,
        win_ctl,
        shared_data,
        scale_x,
        scale_y,
        is_simulating=0,
    ):
        self.win_ctl = win_ctl
        self.shared_data = shared_data
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.is_simulating = is_simulating

        if self.is_simulating:
            self.mouse = event.Mouse(win=win_ctl)
            print("Mouse gaze simulation enabled.")

        self.cursor = visual.Circle(
            win_ctl,
            radius=6,
            fillColor="yellow",
            opacity=0.8,
        )
        self.tail_line = visual.ShapeStim(
            win_ctl,
            vertices=[(0, 0), (0, 0)],
            closeShape=False,
            lineWidth=2.0,
            lineColor="yellow",
            opacity=0.6,
        )
        self.trail = deque(maxlen=60)
        # EyeLink decisions use the newest unfiltered sample. QY preserves the
        # existing five-frame smoothing on the operator view.
        smooth_samples = (
            1 if getattr(shared_data, "mode", None) == "eyelink" else 5
        )
        self.smooth_buffer = deque(maxlen=smooth_samples)

    def reset_trail(self):
        self.trail.clear()
        self.smooth_buffer.clear()

    def update_and_draw(self):
        if self.is_simulating:
            mouse_x, mouse_y = self.mouse.getPos()
            gaze = {
                "x": mouse_x / self.scale_x,
                "y": mouse_y / self.scale_y,
                "valid": True,
            }
        else:
            gaze = self.shared_data.get_latest_cal()
            if gaze["valid"]:
                self.smooth_buffer.append((gaze["x"], gaze["y"]))
                gaze["x"] = sum(
                    point[0] for point in self.smooth_buffer
                ) / len(self.smooth_buffer)
                gaze["y"] = sum(
                    point[1] for point in self.smooth_buffer
                ) / len(self.smooth_buffer)
                mouse_x = gaze["x"] * self.scale_x
                mouse_y = gaze["y"] * self.scale_y

        if gaze["valid"]:
            self.trail.append((mouse_x, mouse_y))
            if len(self.trail) >= 2:
                self.tail_line.vertices = list(self.trail)
                self.tail_line.draw()
            self.cursor.pos = (mouse_x, mouse_y)
            self.cursor.draw()
        return gaze
