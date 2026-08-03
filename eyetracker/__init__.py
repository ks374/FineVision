"""FineVision eye-tracker backends.

Tasks depend on the small interface exported here instead of importing a
vendor SDK directly.  Vendor-specific entry scripts remain separate so that
operators can tell which hardware a task will use before running it.
"""

from .runtime import create_tracker_runtime

__all__ = ["create_tracker_runtime"]
