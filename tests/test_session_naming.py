import json
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import SaccadeTask as saccade
import SaccadeMultiStimTask as multi
import Orientation2AFCTrainingTask as orientation
from OrientationBar2AFCTrainingTask import OrientationBar2AFCTrainingTask
import EyeLink_Native_Calibration as native
from SessionNaming import confirm_session_parameters, subject_filename


@pytest.mark.parametrize('module,prefix,task_class', [
    (saccade, 'Saccade', saccade.SaccadeTask),
    (multi, 'SaccadeMultiStim', multi.SaccadeMultiStimTask),
    (orientation, 'Orientation2AFC', orientation.Orientation2AFCTrainingTask),
    (orientation, 'OrientationBar2AFC', OrientationBar2AFCTrainingTask),
])
def test_subject_and_collision_suffix_match_directory_and_log(module, prefix, task_class):
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'datetime') as clock:
        clock.now.return_value = datetime(2026, 9, 14, 12, 30, 0)
        kwargs = {'subject_id': 'Monkey_M879'}
        if module is orientation:
            kwargs['session_prefix'] = prefix
        first, _ = module._create_session_dir(root, **kwargs)
        suffix, folder = module._create_session_dir(root, **kwargs)
        assert first == 'Monkey_M879_20260914_123000'
        assert suffix == first + '_001'
        assert Path(folder).name == f'{prefix}_{suffix}'
        task = task_class.__new__(task_class)
        task.session_timestamp = suffix
        assert task._task_log_filename() == f'{prefix}_task_log_{suffix}.csv'


def test_confirmation_uses_newly_selected_subject():
    manager = SimpleNamespace(exp_params={'Subject ID': 'Monkey_H18'})
    def prompt():
        manager.exp_params['Subject ID'] = 'Monkey_M879'
        return True
    manager.prompt_for_parameters = prompt
    assert confirm_session_parameters(manager)
    assert manager.session_subject_id == 'Monkey_M879'
    assert manager.session_parameters_confirmed


def test_cancel_does_not_confirm_session():
    manager = SimpleNamespace(prompt_for_parameters=Mock(return_value=False))
    assert not confirm_session_parameters(manager)
    assert not hasattr(manager, 'session_subject_id')


def test_subject_filename_is_safe_and_preserves_unicode():
    assert subject_filename(' 猴子/H18:* ') == '猴子_H18__'
    with pytest.raises(ValueError):
        subject_filename('  ')


def test_native_edf_and_json_share_subject_and_session():
    with tempfile.TemporaryDirectory() as root, patch.object(native, 'SCRIPT_DIR', Path(root)):
        session, host, edf = native._native_edf_paths(
            datetime(2026, 9, 14, 12, 30), '猴子_M879'
        )
        native._write_session_log(
            native.NativeCalibrationConfig(subject_id='猴子_M879'),
            'completed', None, None, session_id=session,
            host_edf_name=host, local_edf_path=edf,
        )
        report = edf.with_suffix('.json')
        assert report.exists()
        assert json.loads(report.read_text(encoding='utf-8'))['subject_id'] == '猴子_M879'
        assert len(host.split('.')[0]) == 8
