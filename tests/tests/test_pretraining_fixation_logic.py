import unittest

from PretrainingFixationLogic import (
    PretrainingTrialController,
    validate_pretraining_params,
)


class PretrainingTrialControllerTests(unittest.TestCase):
    def test_manual_reward_ends_fixation_immediately_and_only_once(self):
        controller = PretrainingTrialController(max_fixation_s=5.0)

        first = controller.press_reward(elapsed_s=1.25)
        second = controller.press_reward(elapsed_s=1.50)

        self.assertTrue(first.reward_requested)
        self.assertTrue(first.fixation_finished)
        self.assertEqual(first.result, "ManualReward")
        self.assertEqual(first.fixation_duration_s, 1.25)
        self.assertFalse(second.reward_requested)

    def test_timeout_ends_fixation_without_reward(self):
        controller = PretrainingTrialController(max_fixation_s=2.0)

        before = controller.update(elapsed_s=1.99)
        at_limit = controller.update(elapsed_s=2.0)

        self.assertFalse(before.fixation_finished)
        self.assertFalse(before.reward_requested)
        self.assertTrue(at_limit.fixation_finished)
        self.assertFalse(at_limit.reward_requested)
        self.assertEqual(at_limit.result, "NoReward")
        self.assertEqual(at_limit.fixation_duration_s, 2.0)

    def test_reward_at_or_after_timeout_is_rejected(self):
        controller = PretrainingTrialController(max_fixation_s=2.0)

        decision = controller.press_reward(elapsed_s=2.0)

        self.assertTrue(decision.fixation_finished)
        self.assertFalse(decision.reward_requested)
        self.assertEqual(decision.result, "NoReward")

    def test_abort_finishes_trial_without_reward(self):
        controller = PretrainingTrialController(max_fixation_s=2.0)

        decision = controller.abort(elapsed_s=0.75)

        self.assertTrue(decision.fixation_finished)
        self.assertFalse(decision.reward_requested)
        self.assertEqual(decision.result, "Aborted")
        self.assertEqual(decision.fixation_duration_s, 0.75)

    def test_duration_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            PretrainingTrialController(max_fixation_s=0)

    def test_parameter_validation_accepts_training_values(self):
        validate_pretraining_params({
            "Fixation Point Radius (pix)": 25,
            "Maximum Fixation Display (s)": 4.0,
            "Reward Duration (ms)": 250,
            "Black Screen Duration (s)": 1.0,
            "Subject Screen Index": 1,
            "Control Screen Index": 0,
        })

    def test_parameter_validation_rejects_negative_reward_duration(self):
        with self.assertRaisesRegex(ValueError, "Reward Duration"):
            validate_pretraining_params({
                "Fixation Point Radius (pix)": 25,
                "Maximum Fixation Display (s)": 4.0,
                "Reward Duration (ms)": -1,
                "Black Screen Duration (s)": 1.0,
                "Subject Screen Index": 1,
                "Control Screen Index": 0,
            })


if __name__ == "__main__":
    unittest.main()
