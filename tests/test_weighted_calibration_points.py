import unittest
from unittest.mock import Mock
import numpy as np
from CalibrationPoints import DEFAULT_POINTS, normalize_points
from Calibration_Task import DEFAULT_PARAMS, _build_calibration_target_specs, _validate_calibration_params
from CalibrationManager import CalibrationManager

IDENTITY = dict(ox=0., oy=0., gx=1., gy=1.)

class WeightedPointsTests(unittest.TestCase):
    def test_default_three_geometry_and_weights(self):
        p=dict(DEFAULT_PARAMS, **{'Calibration Points': DEFAULT_POINTS})
        _validate_calibration_params(p)
        specs=_build_calibration_target_specs(p,(1920,1080))
        self.assertEqual([s['target_deg'] for s in specs],[(0.,0.),(-4.,0.),(0.,3.)])
        self.assertEqual([s['weight'] for s in specs],[1.,1.,1.])
        self.assertLess(specs[1]['target'][0],0)
        self.assertGreater(specs[2]['target'][1],0)

    def test_invalid_points_and_outside_screen(self):
        for ps in (DEFAULT_POINTS[:2], [dict(x_deg=i,y_deg=0,weight=1) for i in range(3)],
                   [dict(p,weight=0) for p in DEFAULT_POINTS], [dict(p,weight=float('nan')) for p in DEFAULT_POINTS]):
            with self.assertRaises(ValueError): normalize_points(ps)
        with self.assertRaises(ValueError):
            _validate_calibration_params(dict(DEFAULT_PARAMS,**{'Calibration Points': DEFAULT_POINTS+[dict(x_deg=70,y_deg=0,weight=1)]}))

    def test_no_fixed_point_limit(self):
        ps=DEFAULT_POINTS+[dict(x_deg=(i%10)/10,y_deg=(i//10)/100,weight=1) for i in range(1000)]
        self.assertEqual(len(normalize_points(ps)),1003)

    def test_linear_weights_not_squared(self):
        raw=np.array([[0,0],[1,0],[0,1],[1,1]],dtype=float)
        target=raw.copy();target[-1]+=[3,-2]
        w=np.array([1,2,3,8.])
        fit=CalibrationManager._fit_affine(*raw.T,*target.T,IDENTITY,weights=w)
        design=np.column_stack((np.ones(4),raw))
        expected=np.linalg.solve(design.T@np.diag(w)@design,design.T@np.diag(w)@target)
        actual=np.array([[fit['ox'],fit['oy']],[fit['gx'],fit['gyx']],[fit['gxy'],fit['gy']]])
        np.testing.assert_allclose(actual,expected,atol=1e-10)
        equal=CalibrationManager._fit_affine(*raw.T,*target.T,IDENTITY,weights=np.ones(4))
        self.assertNotAlmostEqual(fit['ox'],equal['ox'])
        scaled=CalibrationManager._fit_affine(*raw.T,*target.T,IDENTITY,weights=w*100)
        for key in ('ox','oy','gx','gy','gxy','gyx'):self.assertAlmostEqual(fit[key],scaled[key])

    def test_bad_weights_rejected(self):
        for w in ([1,1], [1,0,1], [1,float('inf'),1]):
            with self.assertRaises(ValueError):
                CalibrationManager._fit_affine([0,1,0],[0,0,1],[0,1,0],[0,0,1],IDENTITY,weights=w)

    def test_collection_weights_reach_applied_mapping(self):
        raw=np.array([[0,0],[1,0],[0,1],[1,1]],dtype=float)
        target=raw.copy();target[-1]+=[3,-2]
        data=np.column_stack((target,raw,raw))
        m=CalibrationManager.__new__(CalibrationManager)
        m.shared_data=Mock(mode='eyelink')
        m.shared_data.get_calibration_left.return_value=IDENTITY
        m.shared_data.get_calibration_right.return_value=IDENTITY
        m.collected_weights=np.array([1,2,3,8.])
        m._set_calibration_dict=Mock();m._send_tracker_event=Mock()
        left,right=m._calculate_and_apply(data)
        expected=CalibrationManager._fit_affine(*raw.T,*target.T,IDENTITY,weights=m.collected_weights)
        self.assertEqual(right,expected)
        m._set_calibration_dict.assert_any_call('right',expected)

if __name__=='__main__': unittest.main()
