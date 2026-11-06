import ast
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
import time
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import Saccade_Elec_stim_Eyelink_Intan as task
from SaccadeElecLogic import make_plan, qualifies, advance, gaze_degrees


class ProtocolTests(unittest.TestCase):
    def test_schedule_and_balanced_control(self):
        for bank in (0, 128):
            plan = make_plan(bank, 123, (3, 12, -6, 6))
            self.assertEqual(len(plan), 970)
            self.assertTrue(all(c['kind'] == 'precontrol' for c in plan[:10]))
            stim = [c for c in plan if c['kind'] == 'stim']
            self.assertEqual(len(stim), 768)
            self.assertEqual(set(Counter((c['hw'], c['current_uA']) for c in stim).values()), {2})
            self.assertEqual({c['hw'] for c in stim}, set(range(bank, bank+128)))
            controls = plan[14::5]
            self.assertEqual(len(controls), 192)
            cells = {(int((c['target_deg'][0]-3)/9*16), int((c['target_deg'][1]+6)/12*12)) for c in controls}
            self.assertEqual(len(cells), 192)
            self.assertEqual(plan, make_plan(bank, 123, (3,12,-6,6)))

    def test_validation_and_retries(self):
        task.validate(task.DEFAULTS)
        p = dict(task.DEFAULTS, **{'RF x_min (deg)': -2, 'RF x_max (deg)': 2,
                                  'RF y_min (deg)': -2, 'RF y_max (deg)': 2})
        task.validate(p)  # RF may cover fixation and the control target window.
        self.assertFalse(advance({'kind':'control'}, 'nofix_2', False))
        self.assertTrue(advance({'kind':'control'}, 'success', False))
        self.assertFalse(advance({'kind':'stim'}, 'break_1', False))
        self.assertTrue(advance({'kind':'stim'}, 'nofix_2', True))

    def test_timestamp_and_strict_amplitude_boundary(self):
        event = dict(valid=True, eye=1, start_ms=100, end_ms=150, amplitude_deg=.76)
        self.assertTrue(qualifies(event, 100, 467))
        for changes in ({'start_ms':99}, {'start_ms':468}, {'amplitude_deg':.75}, {'eye':0}, {'valid':False}):
            self.assertFalse(qualifies(dict(event, **changes), 100, 467))

    def test_coordinates(self):
        self.assertEqual(gaze_degrees((960,540), (1920,1080), (54,30), 60), (0,0))
        x = 960 + math.tan(math.radians(8))*60/54*1920
        self.assertAlmostEqual(gaze_degrees((x,540),(1920,1080),(54,30),60)[0], 8)


class ResponseTests(unittest.TestCase):
    """Execute the real response state machine using simulated display time."""
    def run_response(self, kind='stim', sacc_start=100, received=.18, gaze=None,
                     target_deg=(4,0), cycle_s=1/60, electrical=False, target_px=(100,0),
                     sacc_amplitude=4):
        source = ast.parse((ROOT/'Saccade_Elec_stim_Eyelink_Intan.py').read_text(encoding='utf-8'))
        launch = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        cls = next(n for n in launch.body if isinstance(n,ast.ClassDef))
        clock = types.SimpleNamespace(t=0)
        p = dict(task.DEFAULTS)
        env = dict(task.__dict__, plan=[None]*250, SaccadeTask=object, p=p,
                   args=types.SimpleNamespace(mouse=False),
                   time=types.SimpleNamespace(perf_counter=lambda:clock.t))
        exec(compile(ast.Module(body=[cls], type_ignores=[]),'<task-state-test>','exec'),env)
        obj = env['Task'].__new__(env['Task'])
        obj.row = {'target_screen_deg':list(target_deg)}
        commands=[]
        obj.worker = types.SimpleNamespace(submit=lambda action,c: commands.append(action) or
            dict(command_pc=clock.t,done=True)) if electrical else None
        obj.wait_job=lambda job:None
        obj.pending_events = []
        obj.reader = types.SimpleNamespace(tracker_ms=lambda pc:pc*1000)
        obj.stim_frames = 10
        obj.refresh = 60
        obj.fix_x_deg = obj.fix_y_deg = 0
        obj.stim_x_px, obj.stim_y_px = target_px
        obj.stim_radius_px = 20
        obj._in_window = lambda g,x,y,r: g['valid'] and math.hypot(g['x']-x,g['y']-y)<=r
        markers = []
        obj.mark = lambda label, **kw: markers.append((label,kw))
        injected = False
        light = []
        def frame(**kw):
            nonlocal injected
            clock.t += cycle_s
            obj.flip_pc = clock.t
            light.append(kw.get('stim_pd',False))
            if kw.get('callback'):
                kw['callback'](clock.t)
            if received is not None and clock.t >= received and not injected:
                obj.pending_events.append(dict(valid=True,eye=1,start_ms=sacc_start,
                    end_ms=sacc_start+25,amplitude_deg=sacc_amplitude,end_deg=[4,0],received_pc=clock.t))
                injected = True
            return gaze(clock.t) if gaze else {'valid':True,'x':0,'y':0}
        obj.frame = frame
        status = obj.response({'kind':kind}, {'valid':True,'x':0,'y':0})
        duration=obj.row['stimoff_pc']-obj.row['stimon_pc']
        self.assertGreaterEqual(duration,task.WAVEFORM['nominal_train_ms']/1000)
        self.assertLessEqual(duration,task.WAVEFORM['nominal_train_ms']/1000+2*cycle_s+1e-9)
        self.assertEqual(commands,['trigger'] if electrical else [])
        return status,obj.row

    def test_late_delivery_inside_window(self):
        status,row = self.run_response(sacc_start=450, received=.55)
        self.assertEqual(status,'nofix_2')
        self.assertNotIn('saccade',row)
        self.assertLess(row['response_finished_pc']-row['response_deadline_pc'],1/60+1e-9)

    def test_control_hold_succeeds_even_if_event_receipt_is_late(self):
        good = lambda t: dict(valid=True,x=100,y=0)
        status,row = self.run_response(kind='control',sacc_start=400,received=.55,gaze=good)
        self.assertEqual(status,'success')
        self.assertNotIn('saccade_qualified_pc',row)
        self.assertEqual(row['response_success_criterion'],'target_window_hold_only')

    def test_no_grace_parameter(self):
        self.assertNotIn('Event arrival grace (ms)',task.DEFAULTS)

    def test_historical_and_outside_window_rejected(self):
        self.assertEqual(self.run_response(sacc_start=0)[0],'nofix_2')
        self.assertEqual(self.run_response(sacc_start=600,received=.62)[0],'nofix_2')

    def test_control_requires_target_hold(self):
        self.assertEqual(self.run_response(kind='control')[0],'nofix_2')
        self.assertEqual(self.run_response(kind='control', target_deg=(0,0),
            target_px=(0,0), received=None)[0], 'success')  # Already inside is eligible after onset.
        good = lambda t: dict(valid=True,x=100 if t>.12 else 0,y=0)
        self.assertEqual(self.run_response(kind='control',gaze=good)[0],'success')
        brief = lambda t: dict(valid=True,x=100 if .18<t<.21 else 0,y=0)
        self.assertEqual(self.run_response(kind='control',gaze=brief)[0],'break_2')

    def test_controls_hold_without_any_saccade_event(self):
        good = lambda t: dict(valid=True,x=100 if t>.12 else 0,y=0)
        for kind in ('control','precontrol'):
            status,row = self.run_response(kind=kind,received=None,gaze=good)
            self.assertEqual(status,'success')
            self.assertNotIn('saccade',row)
            self.assertEqual(row['response_end_reason'],'target_hold_complete')

    def test_small_saccade_does_not_gate_control_hold(self):
        good = lambda t: dict(valid=True,x=100 if t>.12 else 0,y=0)
        self.assertEqual(self.run_response(kind='control',gaze=good,sacc_amplitude=.1)[0],'success')
        self.assertEqual(self.run_response(kind='stim',sacc_amplitude=.1)[0],'nofix_2')

    def test_control_hold_must_finish_before_deadline(self):
        late = lambda t: dict(valid=True,x=100 if t>.46 else 0,y=0)
        self.assertEqual(self.run_response(kind='control',received=None,gaze=late)[0],'break_2')

    def test_25hz_startup_allows_300ms_fixation_setting(self):
        source = ast.parse((ROOT/'Saccade_Elec_stim_Eyelink_Intan.py').read_text(encoding='utf-8'))
        launch = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        cls = next(n for n in launch.body if isinstance(n,ast.ClassDef))
        fake_visual = types.SimpleNamespace(Rect=lambda *a,**k:object(),
                                            TextStim=lambda *a,**k:object())
        with tempfile.TemporaryDirectory() as folder:
            env = dict(task.__dict__, plan=[None]*250, SaccadeTask=object, p=dict(task.DEFAULTS),
                       args=types.SimpleNamespace(mouse=True),
                       out=Path(folder), BASE={}, visual=fake_visual,
                       GazeTrackerRenderer=lambda *a:object(), calibration={}, rgb=[])
            exec(compile(ast.Module(body=[cls],type_ignores=[]),'<init-test>','exec'),env)
            klass=env['Task']
            klass.update_params=lambda self:None
            win=types.SimpleNamespace(size=(1920,1080),getActualFrameRate=lambda **kw:25)
            ctl=types.SimpleNamespace(size=(800,450))
            backend=types.SimpleNamespace(gaze_source=object(), send_event=lambda message:None)
            instance=klass(backend,win,ctl)
            self.assertFalse(hasattr(instance,'stim_frames'))
            self.assertFalse(hasattr(instance,'min_fix_pd_s'))
            for journal in (instance.events_log,instance.sacc_log,instance.trials_log,instance.frames_log,instance.raw_gaze_log):
                journal.close()

    def test_slow_cycles_do_not_stretch_stimulus_to_45_iterations(self):
        status,row=self.run_response(cycle_s=.012, sacc_start=600, received=.65)
        self.assertEqual(status,'nofix_2')
        self.assertLess(row['stimoff_pc']-row['stimon_pc'],.191)
        self.assertAlmostEqual(row['response_deadline_pc'],row['stimoff_pc']+.3)
        self.assertEqual(row['response_end_pc'],row['response_deadline_pc'])
        self.assertLess(row['response_finished_pc']-row['response_deadline_pc'],.012+1e-9)

    def test_electrical_trigger_is_once_and_deadline_uses_dispatch(self):
        status,row=self.run_response(electrical=True,cycle_s=.012,sacc_start=400,received=.45)
        self.assertEqual(status,'success')
        self.assertAlmostEqual(row['response_deadline_pc'],row['stim_command_pc']+.4666666666666667)
        self.assertLessEqual(row['saccade']['received_pc'],row['response_deadline_pc'])
        self.assertLessEqual(row['saccade_qualified_pc'],row['response_deadline_pc'])
        self.assertEqual(row['response_deadline_reference'],'stim_command_pc_plus_nominal_train')

    def test_first_saccade_finishes_response_early_after_stimulus_offset(self):
        status,row=self.run_response(sacc_start=100,received=.15)
        self.assertEqual(status,'success')
        self.assertLess(row['response_end_pc'],row['response_deadline_pc'])
        self.assertGreaterEqual(row['response_end_pc'],row['stimoff_pc'])

    def test_event_ending_after_deadline_is_not_accepted(self):
        status,row=self.run_response(electrical=True,sacc_start=475,received=.51)
        self.assertEqual(status,'nofix_2')


class FixationTimingTests(unittest.TestCase):
    def make_task(self):
        source=ast.parse((ROOT/'Saccade_Elec_stim_Eyelink_Intan.py').read_text(encoding='utf-8'))
        launch=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
        cls=next(n for n in launch.body if isinstance(n,ast.ClassDef))
        clock=types.SimpleNamespace(t=0.)
        p=dict(task.DEFAULTS, **{'Fixation Duration Min (ms)':30,'Fixation Duration Max (ms)':30,'Gap Duration (ms)':10})
        env=dict(task.__dict__, plan=[None]*250,SaccadeTask=object,p=p,args=types.SimpleNamespace(mouse=False),
            time=types.SimpleNamespace(perf_counter=lambda:clock.t),event=types.SimpleNamespace(getKeys=lambda:[]),
            calibration={'target_luminance_cd_m2_by_color':{'Gray':{150:1}}})
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<fixation-test>','exec'),env)
        obj=env['Task'].__new__(env['Task'])
        class Window:
            size=(1920,1080)
            def __init__(self,dt):self.dt=dt;self.callbacks=[]
            def callOnFlip(self,fn):self.callbacks.append(fn)
            def flip(self):
                clock.t+=self.dt
                for fn in self.callbacks:fn()
                self.callbacks=[]
        obj.win_sub=Window(.005);obj.win_ctl=Window(.006)
        obj.reader=None;obj.pending_events=[];obj.fix_pd=0;obj.last_pd=False;obj.frame_id=0
        obj.row={'kind':'stim','plan_id':1};obj.attempt=1;obj.paused=obj.pause=obj.edit_requested=False
        obj.fix_x_px=obj.fix_y_px=0;obj.fix_radius_px=20
        obj._in_window=lambda g,x,y,r:g['valid'] and math.hypot(g['x']-x,g['y']-y)<=r
        obj.gaze_renderer=Mock();obj.gaze_renderer.update.return_value=dict(x=0,y=0,valid=True,timestamp=1.5)
        for attr in ('fix_sub','fix_ctl','stim_sub','stim_ctl','fix_window_ctl','stim_window_ctl','pd','info','frames_log'):
            setattr(obj,attr,Mock())
        obj.marks=[]
        def mark(label,pc=None,**kw):
            pc=clock.t if pc is None else pc;obj.marks.append((label,pc,kw));return pc
        obj.mark=mark
        return obj,clock

    def test_detection_sample_and_pd_flip_are_separate_and_ten_cycles(self):
        obj,clock=self.make_task()
        obj.frame(fix=True,acquire_fix=True)
        self.assertEqual(obj.row['fixation_enter_sample_eyelink'],1500.)
        self.assertEqual(obj.row['fixation_detected_pc'],0.)
        self.assertEqual(obj.row['fixation_pd_on_pc'],.005)
        self.assertEqual(obj.fix_pd,9)
        for _ in range(9):obj.frame(fix=True)
        self.assertEqual(obj.fix_pd,0)
        obj.frame(fix=True)
        logs=[call.args[0] for call in obj.frames_log.write.call_args_list]
        self.assertEqual(sum(r['pd'] for r in logs),10)
        self.assertEqual(len([m for m in obj.marks if m[0]=='FIXON']),1)
        self.assertGreater(obj.row['fixation_pd_off_pc'],obj.row['fixation_pd_on_pc'])

    def test_short_fixation_is_not_extended_to_complete_pd_pulse(self):
        obj,clock=self.make_task()
        obj.attempt=0;obj.condition_attempts={};obj.parameter_revision=0;obj.arduino=None
        obj.control_rgb=[255]*3;obj.control_level=150
        obj.scale_x=obj.scale_y=1;obj.fix_x_deg=obj.fix_y_deg=0
        obj.viewing_distance_cm=60;obj.monitor_width_cm=54;obj.monitor_height_cm=30
        obj.response=lambda c,g:'response'
        self.assertEqual(obj.run_attempt(dict(kind='stim',plan_id=1,target_deg=[0,0])),'response')
        self.assertLess(obj.row['fixation_hold_actual_s'],.06)
        self.assertGreater(clock.t-obj.row['fixoff_pc'],.01)
        self.assertEqual(sum(c.args[0]['pd'] for c in obj.frames_log.write.call_args_list),10)


class RuntimeParameterTests(unittest.TestCase):
    def make_task(self, action='confirm'):
        source = ast.parse((ROOT/'Saccade_Elec_stim_Eyelink_Intan.py').read_text(encoding='utf-8'))
        launch = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'launch')
        cls = next(n for n in launch.body if isinstance(n, ast.ClassDef))
        p = dict(task.DEFAULTS)
        manager = types.SimpleNamespace(exp_params=dict(p))
        def prompt(**kwargs):
            self.assertIn('Intan channels', kwargs['disabled_parameters'])
            candidate = dict(manager.exp_params, **{'Fix Window Radius (deg)': 1.5,
                                                   'Control calibrated level': 100})
            kwargs['parameter_validator'](candidate)
            manager.exp_params.update(candidate)
            return action
        manager.prompt_for_runtime_parameters = prompt
        env = dict(task.__dict__, plan=[None]*250, SaccadeTask=object, TaskAbort=RuntimeError,
                   p=p, manager=manager, BASE=dict(task.DEFAULTS),
                   calibration={'rgb_by_color': {'Gray': {100: [100, 101, 102]}}},
                   event=types.SimpleNamespace(clearEvents=lambda: None))
        exec(compile(ast.Module(body=[cls], type_ignores=[]), '<runtime-test>', 'exec'), env)
        obj = env['Task'].__new__(env['Task'])
        obj.parameter_revision = 0
        obj.reader = None
        obj.paused = obj.edit_requested = True
        obj.pending_events = [object()]
        obj.task_manager = types.SimpleNamespace(exp_params={})
        obj.update_params = lambda: None
        obj.marks = []
        obj.mark = lambda label, **kw: obj.marks.append((label, kw))
        return obj, p, env

    def test_edit_applies_and_logs_without_replacing_shared_parameters(self):
        obj, p, _ = self.make_task()
        shared = p
        obj.edit_runtime_parameters()
        self.assertIs(p, shared)
        self.assertEqual(p['Fix Window Radius (deg)'], 1.5)
        self.assertEqual(obj.task_manager.exp_params['Fix Window Radius (deg)'], 1.5)
        self.assertEqual(obj.control_rgb, [100, 101, 102])
        self.assertEqual(obj.parameter_revision, 1)
        self.assertFalse(obj.paused)
        self.assertEqual(obj.pending_events, [])
        self.assertEqual(obj.marks[-1][0], 'PARAMETERS_UPDATED')

    def test_cancel_leaves_active_parameters_unchanged(self):
        obj, p, _ = self.make_task('cancel')
        with self.assertRaises(RuntimeError):
            obj.edit_runtime_parameters()
        self.assertEqual(p, task.DEFAULTS)
        self.assertEqual(obj.parameter_revision, 0)

    def test_plan_and_hardware_fields_cannot_change(self):
        for key in task.LOCKED_RUNTIME_PARAMS:
            candidate = dict(task.DEFAULTS)
            candidate[key] = 'changed'
            with self.assertRaises(ValueError, msg=key):
                task.validate_runtime(candidate, task.DEFAULTS)

    def test_modal_pause_discards_large_backlog_before_resume(self):
        obj, p, _ = self.make_task()
        kinds = iter([200]*25000 + [0x3F, 6, 0])
        backend = types.SimpleNamespace(sample_source='gaze',
            _tracker=types.SimpleNamespace(sendCommand=lambda c: 0,
                getNextData=lambda: next(kinds)),
            _pylink=types.SimpleNamespace(ENDSACC=6))
        obj.reader = task.EyeEvents(backend, p, None)
        obj.reader.synchronize = lambda: {'clock_offset_ms': 10}
        obj.edit_runtime_parameters()
        self.assertFalse(obj.paused)
        label, data = obj.marks[0]
        self.assertEqual(label, 'PAUSE_LINK_QUEUE_CLEARED')
        self.assertEqual(data['discarded_items'], 25002)
        self.assertEqual(data['lost_data_markers'], 1)

    def test_cleanup_does_not_read_failed_queue(self):
        obj, _, _ = self.make_task()
        def fail(*a, **kw):
            raise AssertionError('cleanup must not use frame or read EyeLink')
        obj.frame = fail
        obj.reader = types.SimpleNamespace(drain=fail)
        calls = []
        obj.win_sub = types.SimpleNamespace(flip=lambda: calls.append('subject_black'))
        obj.win_ctl = types.SimpleNamespace(flip=lambda: calls.append('control_black'))
        obj.worker = None
        obj.arduino = None
        for name in ('events_log', 'sacc_log', 'trials_log', 'frames_log'):
            setattr(obj, name, types.SimpleNamespace(close=lambda n=name: calls.append(n)))
        obj.cleanup()
        self.assertEqual(len(calls), 6)
        self.assertEqual(obj.marks[-1][0], 'SESSION_BLACKOUT')

    def test_resume_reprepares_without_replaying_delivered_condition(self):
        obj, p, env = self.make_task()
        conditions = [dict(kind='stim', plan_id=11), dict(kind='stim', plan_id=12)]
        env['plan'] = conditions
        clock = types.SimpleNamespace(t=0.)
        env['time'] = types.SimpleNamespace(perf_counter=lambda: clock.t)
        obj.delay = lambda seconds: setattr(clock, 't', clock.t + seconds)
        commands, executed = [], []
        obj.worker = types.SimpleNamespace(submit=lambda action, c=None: commands.append(
            (action, c['plan_id'] if c else None)))
        obj.wait_job = lambda *a, **k: None
        obj.pause = True
        def edit():
            obj.edit_requested = False
            obj.paused = False
        obj.edit_runtime_parameters = edit
        def attempt(c):
            executed.append(c['plan_id'])
            obj.row = dict(delivered=True, end_pc=clock.t)
            return 'success'
        obj.run_attempt = attempt
        obj.finish = lambda status: None
        obj.run()
        self.assertEqual(executed, [11, 12])
        self.assertEqual([c for a, c in commands if a == 'prepare_trial'], [11, 11, 12])


class RecordingBoundaryTests(unittest.TestCase):
    def test_task_snapshots_raw_settings_without_changing_shared_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'shared.json'
            destination = Path(directory)/'session.json'
            import json
            settings = dict(host_ip='100.1.1.1', sample_source='raw', active_eye='right',
                            calibration_file='raw_affine.json', sample_rate_hz=1000)
            source.write_text(json.dumps(settings), encoding='utf-8')
            calibration = Path(directory)/'raw_affine.json'
            calibration.write_text('{"default_right_cal": {"gx": 2}}', encoding='utf-8')
            path = task.session_eyelink_raw_settings(source, destination)
            actual = json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertEqual(actual['sample_source'], 'raw')
            self.assertEqual(actual['host_ip'], settings['host_ip'])
            self.assertTrue(Path(actual['calibration_file']).is_absolute())
            self.assertEqual(Path(actual['calibration_file']).read_text(encoding='utf-8'), calibration.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(source.read_text(encoding='utf-8')), settings)

    def test_abort_cleanup_waits_for_stimulation_and_reward_before_tail_request(self):
        obj, p, env = RuntimeParameterTests().make_task()
        clock = types.SimpleNamespace(t=10.)
        env['time'] = types.SimpleNamespace(perf_counter=lambda: clock.t,
            sleep=lambda seconds: setattr(clock, 't', clock.t+seconds))
        obj.trial_active = True
        obj.trigger = dict(done=True, command_pc=10.)
        obj.row = dict(reward_pc=10.)
        obj.win_sub = Mock()
        obj.win_ctl = Mock()
        obj.arduino = None
        for name in ('events_log', 'sacc_log', 'trials_log', 'frames_log'):
            setattr(obj, name, Mock())
        calls = []
        def submit(action):
            calls.append((action, clock.t))
            return dict(done=True)
        obj.worker = types.SimpleNamespace(submit=submit, thread=types.SimpleNamespace(join=lambda **kw: None))
        obj.cleanup()
        self.assertEqual([a for a, _ in calls], ['protect_trial_tail', 'close'])
        self.assertGreaterEqual(calls[0][1], 10+p['Reward Length (s)'])
        self.assertGreaterEqual(calls[0][1], 10+task.WAVEFORM['nominal_train_ms']/1000)

    def test_slow_uploads_retries_and_visual_trials_keep_guards(self):
        obj, p, env = RuntimeParameterTests().make_task()
        env['plan'] = [dict(kind='stim', plan_id=1), dict(kind='control', plan_id=2)]
        clock = types.SimpleNamespace(t=0.)
        env['time'] = types.SimpleNamespace(perf_counter=lambda: clock.t)
        obj.delay = lambda seconds: setattr(clock, 't', clock.t+seconds)
        actions, trials, ends = [], [], []
        latest_prepared = [0.]
        def submit(action, c=None):
            actions.append((action, clock.t))
            if action == 'prepare_trial':
                if ends:
                    self.assertGreaterEqual(clock.t-ends[-1], task.RECORD_GUARD_S-1e-8)
                clock.t += 4.0  # Upload longer than nominal ITI.
                latest_prepared[0] = clock.t
            return dict(done=True, action=action)
        obj.worker = types.SimpleNamespace(submit=submit)
        obj.wait_job = lambda job, **kwargs: None
        obj.pause = False
        attempts = Counter()
        def attempt(c):
            self.assertGreaterEqual(clock.t-latest_prepared[0], task.RECORD_GUARD_S-1e-8)
            trials.append((c['plan_id'], clock.t))
            attempts[c['plan_id']] += 1
            clock.t += .3
            delivered = c['kind'] == 'stim' and attempts[c['plan_id']] > 1
            obj.row = dict(delivered=delivered, end_pc=clock.t)
            return 'success' if delivered or c['kind'] == 'control' else 'break_1'
        obj.run_attempt = attempt
        def finish(status):
            clock.t += .5  # Reward/event tail belongs to the trial.
            obj.row['recording_event_end_pc'] = clock.t
            ends.append(clock.t)
        obj.finish = finish
        obj.run()
        self.assertEqual([pid for pid, _ in trials], [1, 1, 2])
        self.assertFalse(any(a == 'clear_trial_slot' for a, _ in actions))
        self.assertEqual(sum(a == 'verify_trial_recording' for a, _ in actions), 3)

    def test_finish_protects_after_reward_end(self):
        obj, p, env = RuntimeParameterTests().make_task()
        clock = types.SimpleNamespace(t=10.)
        env['time'] = types.SimpleNamespace(perf_counter=lambda: clock.t)
        env['plan'] = [None]
        obj.row = dict(kind='stim', plan_id=1)
        obj.attempt = 1
        obj.trial_active = True
        obj.frame = lambda **kw: None
        obj.mark = lambda *a, **kw: clock.t
        obj.delay = lambda seconds: setattr(clock, 't', clock.t+seconds)
        obj.arduino = Mock()
        reward_times = []
        obj.arduino.reward.side_effect = lambda *args: reward_times.append(clock.t)
        obj.trials_log = Mock()
        calls = []
        obj.worker = types.SimpleNamespace(submit=lambda action: calls.append((action, clock.t)))
        obj.wait_job = lambda job: None
        obj.finish('success')
        self.assertEqual(reward_times, [10.3])
        self.assertEqual(obj.row['reward_delay_s'], .3)
        self.assertEqual(obj.row['reward_pc'], 10.3)
        self.assertGreaterEqual(obj.row['recording_event_end_pc'], 10.3+p['Reward Length (s)'])
        self.assertAlmostEqual(obj.row['recording_protect_until_pc'], clock.t+task.RECORD_GUARD_S)
        self.assertEqual(calls, [('protect_trial_tail', clock.t)])
        self.assertFalse(obj.trial_active)


class QueueTests(unittest.TestCase):
    def test_active_trial_still_rejects_lost_data(self):
        backend = types.SimpleNamespace(sample_source='gaze',
            _tracker=types.SimpleNamespace(sendCommand=lambda c: 0, getNextData=lambda: 0x3F),
            _pylink=types.SimpleNamespace(ENDSACC=6))
        reader = task.EyeEvents(backend, task.DEFAULTS, None)
        with self.assertRaisesRegex(RuntimeError, 'lost data'):
            reader.drain(1)

    def test_drain_reads_through_samples_and_old_events(self):
        class E:
            def getStartGaze(self): return (960,540)
            def getEndGaze(self): return (1060,540)
            def getEye(self): return 1
            def getStartTime(self): return 100
            def getEndTime(self): return 130
            def getStatus(self): return 0
            def getPeakVelocity(self): return 100
        kinds = iter([200,5,6,200,6,0])
        backend = types.SimpleNamespace(sample_source='gaze',
            _tracker=types.SimpleNamespace(sendCommand=lambda c:0,
                getNextData=lambda:next(kinds), getFloatData=lambda:E()),
            _pylink=types.SimpleNamespace(ENDSACC=6))
        logs=[]
        reader=task.EyeEvents(backend,task.DEFAULTS,types.SimpleNamespace(write=logs.append))
        self.assertEqual(len(reader.drain(1)),2)
        self.assertEqual(len(logs),2)


if __name__ == '__main__':
    unittest.main()
