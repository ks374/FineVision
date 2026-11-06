"""Shared subject-aware names for experiment records."""
import re


def subject_filename(subject_id):
    """Keep Unicode names while removing Windows path separators/reserved chars."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(subject_id).strip()).rstrip(' .')
    if not value or not value.strip('_ .'):
        raise ValueError("Subject ID must contain a monkey name.")
    return value


def confirm_session_parameters(manager):
    """Confirm identity before any files or tracker recording are opened."""
    if not manager.prompt_for_parameters():
        return False
    subject_filename(manager.exp_params["Subject ID"])
    manager.session_parameters_confirmed = True
    manager.session_subject_id = str(manager.exp_params["Subject ID"])
    return True
