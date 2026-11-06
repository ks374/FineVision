import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import InSessionRawCalibration as module

IDENTITY=dict(model='affine_2d',ox=0.,oy=0.,gx=1.,gy=1.,gxy=0.,gyx=0.)
TEST_TMP = Path(__file__).resolve().parents[1] / 'tmp'
TEST_TMP.mkdir(exist_ok=True)

class InSessionRawTests(unittest.TestCase):
    def setup_case(self):
        b=Mock(sample_source='raw',calibration_file='old_snapshot.json')
        b.get_calibration_left.return_value=IDENTITY.copy()
        b.get_calibration_right.return_value=IDENTITY.copy()
        reader=SimpleNamespace(raw_calibration=IDENTITY.copy(),drain=Mock())
        win=Mock(size=(1920,1080),color='black')
        params={'Subject Monitor Width (cm)':54.,'Subject Monitor Height (cm)':30.,
            'Viewing Distance (cm)':60.,'Fixation Point Radius (deg)':.04,
            'Fix Window Radius (deg)':3.,'Wait Time (s)':5.,'ITI (s)':3.5,'Reward Length (s)':.5}
        return b,reader,win,params

    def test_four_points_activate_both_consumers_and_shared_file(self):
        b,reader,win,params=self.setup_case()
        manager=Mock(calibration_report={})
        targets=np.array([[-100,100],[200,-200],[-100,-200],[200,100]],float)
        manager.collected_data=np.column_stack((targets,targets,targets))
        manager.run_calibration.return_value=(IDENTITY,IDENTITY)
        manager._fit_affine.return_value=dict(IDENTITY,ox=5.)
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            active=Path(tmp)/'active.json';active.write_text(json.dumps(dict(default_right_cal=IDENTITY)))
            with patch.object(module,'CalibrationManager',return_value=manager) as factory:
                self.assertTrue(module.run_four_point_calibration(backend=b,reader=reader,subject_win=win,control_win=win,arduino=None,params=params,log_dir=Path(tmp)/'session',active_path=active))
            self.assertEqual([s['target_deg'] for s in factory.call_args.kwargs['target_specs']], [list(p) for p in module.POINTS_DEG])
            self.assertEqual(reader.raw_calibration['ox'],5.)
            b.set_calibration_right_dict.assert_called_once_with(dict(IDENTITY,ox=5.))
            self.assertEqual(json.loads(active.read_text())['default_right_cal']['ox'],5.)
            manager.run_calibration.assert_called_once_with(IDENTITY,IDENTITY,apply_result=False)

    def test_escape_keeps_old_mapping(self):
        b,reader,win,params=self.setup_case();manager=Mock(calibration_report={})
        manager.run_calibration.return_value=None
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp, patch.object(module,'CalibrationManager',return_value=manager):
            active=Path(tmp)/'active.json';active.write_text('{}')
            self.assertFalse(module.run_four_point_calibration(backend=b,reader=reader,subject_win=win,control_win=win,arduino=None,params=params,log_dir=Path(tmp)/'session',active_path=active))
            self.assertEqual(active.read_text(),'{}');b.set_calibration_right_dict.assert_not_called()

    def test_activation_error_rolls_back_file_and_reader(self):
        b,reader,_,_=self.setup_case()
        b.set_calibration_right_dict.side_effect=[RuntimeError('update failed'),None]
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            active=Path(tmp)/'active.json';original=dict(default_right_cal=IDENTITY);active.write_text(json.dumps(original))
            with self.assertRaises(RuntimeError):module.activate_mapping(b,reader,IDENTITY,dict(IDENTITY,ox=5.),active,Path(tmp)/'session',{})
            self.assertEqual(json.loads(active.read_text()),original)
            self.assertEqual(reader.raw_calibration,IDENTITY)
            self.assertEqual(b.calibration_file,'old_snapshot.json')

    def test_pumped_reads_drain_queue_outside_trials(self):
        b,reader,_,_=self.setup_case();source=module.PumpedSource(b,reader)
        source.get_latest();source.get_latest_cal()
        self.assertEqual(reader.drain.call_count,2)
        reader.drain.assert_called_with(0)

if __name__=='__main__':unittest.main()
