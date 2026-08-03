"""Launch older single-file tasks with an explicit tracker selection."""

import runpy


def run_legacy_task(module_name, tracker_mode):
    runpy.run_module(
        module_name,
        run_name="__main__",
        init_globals={
            "TRACKER_MODE_OVERRIDE": tracker_mode,
            "IS_SIMULATING_OVERRIDE": 0,
        },
    )
