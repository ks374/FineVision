"""Four-point RAW calibration using a running task's windows and connection."""
import math
import time
from pathlib import Path
import numpy as np
from CalibrationManager import CalibrationManager
from CalibrationValidation import require_fit_data, write_json, save_mapping

POINTS_DEG = ((-3., 5.), (6., -6.), (-3., -6.), (6., 5.))


class PumpedSource:
    """Keep the link queue drained while the calibration owns the frame loop."""
    mode = 'eyelink'
    def __init__(self, backend, reader):
        self.backend, self.reader = backend, reader
    def __getattr__(self, name):
        return getattr(self.backend, name)
    def get_latest(self):
        self.reader.drain(0)
        return self.backend.get_latest()
    def get_latest_cal(self):
        self.reader.drain(0)
        return self.backend.get_latest_cal()


def activate_mapping(backend, reader, left, right, active_path, log_dir, metadata):
    """Persist and activate both consumers; rollback on a failed update."""
    import json
    active_path = Path(active_path)
    previous = json.loads(active_path.read_text(encoding='utf-8')) if active_path.exists() else None
    old_left, old_right = backend.get_calibration_left(), backend.get_calibration_right()
    old_reader = dict(reader.raw_calibration)
    old_file = backend.calibration_file
    try:
        save_mapping(active_path, log_dir, left, right, metadata)
        backend.set_calibration_left_dict(left)
        backend.set_calibration_right_dict(right)
        reader.raw_calibration = dict(right)
        backend.calibration_file = str(Path(log_dir) / 'eyelink_raw_pupil_setting.json')
    except BaseException:
        backend.set_calibration_left_dict(old_left)
        backend.set_calibration_right_dict(old_right)
        reader.raw_calibration = old_reader
        backend.calibration_file = old_file
        if previous is not None:
            write_json(active_path, previous)
        elif active_path.exists():
            active_path.unlink()
        raise


def run_four_point_calibration(*, backend, reader, subject_win, control_win,
                               arduino, params, log_dir, active_path):
    if backend.sample_source != 'raw':
        raise ValueError('In-session four-point calibration requires RAW mode.')
    log_dir = Path(log_dir); log_dir.mkdir(parents=True, exist_ok=False)
    source = PumpedSource(backend, reader)
    def pixels(angle, axis):
        size = params['Subject Monitor Width (cm)' if axis == 0 else 'Subject Monitor Height (cm)']
        return math.tan(math.radians(angle))*params['Viewing Distance (cm)']/size*subject_win.size[axis]
    specs = [dict(target=(pixels(x,0),pixels(y,1)),target_deg=[x,y],weight=1.,region='in_session_four') for x,y in POINTS_DEG]
    radius = pixels(params['Fixation Point Radius (deg)'],0)
    for s in specs:
        if any(abs(s['target'][axis])+radius >= subject_win.size[axis]/2 for axis in (0,1)):
            raise ValueError('Four-point calibration target lies outside the task display.')
    manager = CalibrationManager(subject_win, control_win, source, str(log_dir/'collection.json'),
        arduino_controller=arduino, tracker_backend=backend, target_specs=specs,
        fixation_point_radius_px=radius, fixation_window_radius_px=pixels(params['Fix Window Radius (deg)'],0),
        background_color=subject_win.color, fixation_duration_s=.5,
        max_wait_time_s=params['Wait Time (s)'], iti_s=params['ITI (s)'],
        reward_ms=round(params['Reward Length (s)']*1000), sample_duration_s=.1, minimum_samples=20)
    manager.ctl_target.fillColor = manager.ctl_target.lineColor = 'green'
    old_left, old_right = backend.get_calibration_left(), backend.get_calibration_right()
    metadata = dict(source='in_session_four_point_RAW',points_deg=POINTS_DEG,
                    parameters=dict(params),independently_validated=False,started_pc=time.perf_counter())
    try:
        # Collection uses the old map for fixation gating; do not apply a partial fit.
        result = manager.run_calibration(old_left, old_right, apply_result=False)
        if result is None:
            manager.calibration_report['status'] = 'aborted'
            return False
        data = manager.collected_data
        require_fit_data(data)
        if len(data) != 4:
            raise ValueError('Exactly four accepted calibration targets are required.')
        left = manager._fit_affine(data[:,2],data[:,3],data[:,0],data[:,1],old_left,weights=np.ones(4))
        right = manager._fit_affine(data[:,4],data[:,5],data[:,0],data[:,1],old_right,weights=np.ones(4))
        if not all(math.isfinite(float(v)) for k,v in right.items() if k != 'model'):
            raise ValueError('Non-finite calibration coefficients.')
        metadata['completed_pc'] = time.perf_counter()
        activate_mapping(backend, reader, left, right, active_path, log_dir, metadata)
        manager.calibration_report.update(status='complete',calibration=dict(left=left,right=right),metadata=metadata)
        return True
    except BaseException as exc:
        manager.calibration_report.update(status='failed',error=repr(exc))
        raise
    finally:
        write_json(log_dir/'collection.json',manager.calibration_report)
        subject_win.flip();control_win.flip()
