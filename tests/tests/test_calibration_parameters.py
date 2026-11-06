import unittest

from Calibration_Task import (
    DEFAULT_PARAMS,
    _build_calibration_target_specs,
    _validate_calibration_params,
    pixels_to_visual_angle,
    visual_angle_to_pixels,
)
from DisplayCalibration import (
    load_calibrated_gray_level,
    load_calibrated_gray_level_from_workbook,
)


class DisplayCalibrationTests(unittest.TestCase):
    def test_level_five_matches_measured_gray(self):
        gray = load_calibrated_gray_level(5)
        self.assertEqual(gray["rgb_255"], (40, 40, 40))
        self.assertAlmostEqual(gray["luminance_cd_m2"], 5.875)
        self.assertEqual(gray["max_level"], 182)

    def test_extended_gray_level_is_available(self):
        gray = load_calibrated_gray_level(182)
        self.assertEqual(gray["rgb_255"], (255, 255, 255))
        self.assertAlmostEqual(gray["luminance_cd_m2"], 213.75)

    def test_level_160_is_read_directly_from_extended_workbook(self):
        gray = load_calibrated_gray_level_from_workbook(160)
        self.assertEqual(gray["rgb_255"], (232, 232, 232))
        self.assertAlmostEqual(gray["luminance_cd_m2"], 188.0)
        self.assertAlmostEqual(
            gray["estimated_luminance_cd_m2"],
            188.6072916666667,
        )
        self.assertEqual(gray["max_level"], 182)


class CalibrationGeometryTests(unittest.TestCase):
    def test_visual_angle_pixel_conversion_round_trip(self):
        pixels = visual_angle_to_pixels(9.0, 58.0, 54.0, 1920)
        recovered = pixels_to_visual_angle(pixels, 58.0, 54.0, 1920)
        self.assertAlmostEqual(recovered, 9.0)

    def test_nine_targets_keep_degree_coordinates(self):
        specs = _build_calibration_target_specs(
            DEFAULT_PARAMS,
            (1920, 1080),
        )
        self.assertEqual(len(specs), 9)
        self.assertEqual(specs[0]["target_deg"], (0.0, 0.0))
        self.assertEqual(specs[1]["target_deg"], (-9.0, 5.0))
        self.assertEqual(specs[8]["target_deg"], (9.0, -5.0))
        self.assertGreater(specs[1]["target"][1], 0.0)
        self.assertGreater(specs[8]["target"][0], 0.0)
        self.assertLess(specs[8]["target"][1], 0.0)

    def test_default_parameters_are_valid(self):
        self.assertIsNone(_validate_calibration_params(DEFAULT_PARAMS))


if __name__ == "__main__":
    unittest.main()
