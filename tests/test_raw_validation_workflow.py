import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
import Calibration_Task as task
from CalibrationManager import CalibrationManager
from CalibrationValidation import validation_offsets, require_fit_data, save_mapping
from CalibrationValidation import show_validation


IDENTITY = dict(model="affine_2d", ox=0., oy=0., gx=1., gy=1., gxy=0., gyx=0.)


class WorkflowTests(unittest.TestCase):
    def test_plot_close_defaults_to_no_update_and_saves_original_offsets(self):
        import matplotlib
        matplotlib.use('Agg', force=True)
        import matplotlib.pyplot as plt
        data=np.array([[0,0,0,0,10,20],[-100,100,0,0,-90,120],[100,-100,0,0,110,-80]])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as folder:
            with patch.object(matplotlib,'use'), patch.object(plt,'show'):
                self.assertFalse(show_validation(data,IDENTITY,folder))
            self.assertTrue((Path(folder)/'validation_before_update.png').exists())
            offsets=json.loads((Path(folder)/'validation_offsets.json').read_text())
            self.assertEqual(offsets['offsets_right_up_px'],[[10,20]]*3)
            plt.close('all')

    def test_offsets_are_evaluated_with_old_mapping(self):
        data = np.array([[0, 0, np.nan, np.nan, 10, 20], [100, 0, np.nan, np.nan, 110, 20],
                         [0, 100, np.nan, np.nan, 10, 120]])
        np.testing.assert_allclose(validation_offsets(data, IDENTITY), [[10,20]]*3)
        require_fit_data(data)
        fitted = CalibrationManager._fit_affine(data[:,4],data[:,5],data[:,0],data[:,1],IDENTITY)
        np.testing.assert_allclose(validation_offsets(data,fitted),0,atol=1e-10)

    def test_degenerate_raw_does_not_qualify_for_update(self):
        with self.assertRaises(ValueError):
            require_fit_data(np.zeros((9,6)))

    def run_validation(self, choice):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as folder:
            root=Path(folder)
            active=root/'eyelink_raw_pupil_setting.json'
            original=dict(default_left_cal=IDENTITY,default_right_cal=IDENTITY)
            active.write_text(json.dumps(original))
            (root/'eyelink_setting.json').write_text(json.dumps(dict(sample_source='gaze',calibration_file='old.json')))
            params=dict(task.DEFAULT_PARAMS)
            notebook=Mock();notebook.exp_params=params;notebook.prompt_for_parameters.return_value=True
            tracker=Mock(mode='eyelink');tracker.gaze_source=Mock()
            def make_tracker(*args,**kwargs):
                tracker.local_edf_path=str(Path(kwargs['save_dir'])/'test.edf')
                tracker.close.side_effect=lambda: Path(tracker.local_edf_path).write_bytes(b'mock')
                return tracker
            def window(**kwargs):
                win=Mock();win.size=kwargs['size'];return win
            manager=Mock();manager.calibration_report={};manager.targets=list(range(9))
            manager.collected_weights=np.ones(9)
            manager.collected_data=np.array([[0,0,np.nan,np.nan,10,20],[-100,100,np.nan,np.nan,-90,120],
                [0,100,np.nan,np.nan,10,120],[100,100,np.nan,np.nan,110,120],[-100,0,np.nan,np.nan,-90,20],
                [100,0,np.nan,np.nan,110,20],[-100,-100,np.nan,np.nan,-90,-80],[0,-100,np.nan,np.nan,10,-80],
                [100,-100,np.nan,np.nan,110,-80]],dtype=float)
            manager.run_calibration.return_value=(IDENTITY.copy(),IDENTITY.copy())
            manager._fit_affine.side_effect=CalibrationManager._fit_affine
            with patch.object(task,'__file__',str(root/'Calibration_Task.py')), \
                 patch.object(task,'FineVision_Notebook',return_value=notebook), \
                 patch.object(task,'create_tracker_runtime',side_effect=make_tracker) as create, \
                 patch.object(task.visual,'Window',side_effect=window), \
                 patch.object(task,'ArduinoController',return_value=Mock()), \
                 patch.object(task,'CalibrationManager',return_value=manager), \
                 patch.object(task,'edit_points',return_value=[dict(x_deg=0.,y_deg=0.,weight=1.),dict(x_deg=-4.,y_deg=0.,weight=1.),dict(x_deg=0.,y_deg=3.,weight=1.)]), \
                 patch.object(task,'show_validation',return_value=choice):
                task.main('eyelink',validation=True)
            manager.run_calibration.assert_called_once_with(IDENTITY,IDENTITY,apply_result=False)
            log=next((root/'experiment_logs').iterdir())
            settings=json.loads((log/'tracker_settings.json').read_text())
            self.assertEqual(settings['sample_source'],'raw')
            self.assertEqual(json.loads((root/'eyelink_setting.json').read_text())['sample_source'],'gaze')
            current=json.loads(active.read_text())
            if choice:
                self.assertAlmostEqual(current['default_right_cal']['ox'],-10)
                self.assertAlmostEqual(current['default_right_cal']['oy'],-20)
                self.assertEqual(current,json.loads((log/active.name).read_text()))
            else:
                self.assertEqual(current,original)
                manager._fit_affine.assert_not_called()
            self.assertTrue((log/'test.edf').exists())

    def test_no_update_preserves_active_mapping_and_records_edf(self):
        self.run_validation(False)

    def test_update_refits_and_saves_matching_active_and_log_mapping(self):
        self.run_validation(True)


if __name__=='__main__':
    unittest.main()
