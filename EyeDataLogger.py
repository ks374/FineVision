"""Non-blocking, process-based CSV logging for continuous gaze samples."""

import csv
import os
import queue
import time
from multiprocessing import Process


STOP_TOKEN = None


class GazeCsvWriter(Process):
    """
    Drain timestamped gaze samples from a multiprocessing queue.

    Timestamps are assigned by the eye-tracker process when the SDK sample is
    received.  Disk-write latency therefore cannot change their alignment with
    task events.
    """

    def __init__(self, sample_queue, csv_path, batch_size=100, flush_interval_s=1.0):
        super().__init__(name="GazeCsvWriter")
        self.sample_queue = sample_queue
        self.csv_path = os.path.abspath(csv_path)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_s = max(0.1, float(flush_interval_s))
        self.daemon = False

    def run(self):
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        pending_rows = []
        last_flush = time.perf_counter()

        # A large userspace buffer plus batched writerows keeps disk I/O away
        # from both the PsychoPy render loop and the eye-tracker polling loop.
        with open(
            self.csv_path,
            "w",
            newline="",
            encoding="utf-8-sig",
            buffering=1024 * 1024,
        ) as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["Time", "Gaze_Target_X", "Gaze_Target_Y"])
            csv_file.flush()

            while True:
                timeout = max(
                    0.0,
                    self.flush_interval_s - (time.perf_counter() - last_flush),
                )
                try:
                    sample = self.sample_queue.get(timeout=timeout)
                except queue.Empty:
                    sample = "__FLUSH__"

                if sample is STOP_TOKEN:
                    if pending_rows:
                        writer.writerows(pending_rows)
                    csv_file.flush()
                    break

                if sample != "__FLUSH__":
                    sample_time, gaze_x, gaze_y = sample
                    pending_rows.append(
                        [
                            f"{float(sample_time):.6f}",
                            f"{float(gaze_x):.6f}",
                            f"{float(gaze_y):.6f}",
                        ]
                    )

                now = time.perf_counter()
                if (
                    len(pending_rows) >= self.batch_size
                    or now - last_flush >= self.flush_interval_s
                ):
                    if pending_rows:
                        writer.writerows(pending_rows)
                        pending_rows.clear()
                    csv_file.flush()
                    last_flush = now
