import unittest
import wave
import winsound
from unittest.mock import patch

from FineVision_Util import (
    REWARD_SOUND_BEEP_COUNT,
    REWARD_SOUND_DURATION_S,
    REWARD_SOUND_FREQUENCY_HZ,
    REWARD_SOUND_PATH,
    play_reward_sound,
)


class RewardSoundTests(unittest.TestCase):
    def test_shared_reward_sound_plays_one_wav_file(self):
        with patch("FineVision_Util.winsound.PlaySound") as play_sound:
            play_reward_sound()

        self.assertEqual(REWARD_SOUND_BEEP_COUNT, 6)
        self.assertEqual(REWARD_SOUND_FREQUENCY_HZ, 1200)
        self.assertEqual(REWARD_SOUND_DURATION_S, 0.6)
        play_sound.assert_called_once_with(
            str(REWARD_SOUND_PATH),
            winsound.SND_FILENAME,
        )

    def test_reward_cue_wav_has_the_requested_duration(self):
        self.assertTrue(REWARD_SOUND_PATH.is_file())
        with wave.open(str(REWARD_SOUND_PATH), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 44_100)
            self.assertAlmostEqual(
                wav_file.getnframes() / wav_file.getframerate(),
                REWARD_SOUND_DURATION_S,
            )


if __name__ == "__main__":
    unittest.main()
