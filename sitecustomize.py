from __future__ import annotations

import sys

if sys.platform == "win32":
    import platform

    # Python 3.14's Windows platform helpers prefer WMI for CPU/machine details.
    # On some developer machines WMI can hang indefinitely, which blocks pandas
    # and polars imports via platform.machine(). The environment variables are
    # enough for this repo's dependency checks, so disable that optional path.
    if hasattr(platform, "_wmi"):
        platform._wmi = None
