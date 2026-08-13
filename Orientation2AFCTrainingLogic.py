"""Pure helpers for the orientation 2AFC task."""


STAGE_OPTIONS = [
    "Stage 1 - single target",
    "Stage 2 - dot pair plus single target",
    "Stage 3 - dot pair plus two paired-dot targets",
    "Stage 4 - dot pair plus two single-dot targets",
]


def stage_number(stage_value):
    """Return the numeric stage encoded by a parameter-menu value."""
    text = str(stage_value).strip().lower()
    for number in (1, 2, 3, 4):
        if text.startswith(f"stage {number}") or text == str(number):
            return number
    raise ValueError(
        "Training Stage must be one of the four Stage 1/2/3/4 options."
    )


def correct_target_for_orientation(orientation):
    """Map the trained visual category to its saccade report target."""
    if orientation == "Horizontal":
        return "Right"
    if orientation == "Vertical":
        return "Up"
    raise ValueError(f"Unknown orientation: {orientation}")


def dot_pair_positions(
    center_x,
    center_y,
    horizontal_center_distance,
    vertical_center_distance,
    arrangement,
):
    """Return two dot centers for a horizontal or vertical cue pair."""
    if arrangement == "Horizontal":
        half_distance = float(horizontal_center_distance) / 2.0
        return (
            (float(center_x) - half_distance, float(center_y)),
            (float(center_x) + half_distance, float(center_y)),
        )
    if arrangement == "Vertical":
        half_distance = float(vertical_center_distance) / 2.0
        return (
            (float(center_x), float(center_y) - half_distance),
            (float(center_x), float(center_y) + half_distance),
        )
    raise ValueError(f"Unknown dot-pair arrangement: {arrangement}")


def choice_target_arrangement(target_name):
    """Map each report location to the paired-dot marker used in Stage 3."""
    if target_name == "Right":
        return "Horizontal"
    if target_name == "Up":
        return "Vertical"
    raise ValueError(f"Unknown choice target: {target_name}")


def choice_accuracy_counts(trials, recent_limit=None):
    """Return correct/completed-choice counts, optionally for recent choices."""
    choice_trials = [
        trial
        for trial in trials
        if isinstance(trial.get("Choice_Correct"), bool)
    ]
    if recent_limit is not None:
        choice_trials = choice_trials[-int(recent_limit) :]
    return (
        sum(trial["Choice_Correct"] for trial in choice_trials),
        len(choice_trials),
    )
