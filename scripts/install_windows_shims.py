"""Windows-only developer convenience: stub the POSIX modules Home Assistant imports.

Home Assistant officially supports Linux only; ``homeassistant.runner`` imports ``fcntl`` and
``homeassistant.util.resource`` imports ``resource``. Neither is used by the test suite, so
minimal stubs in the virtualenv let ``pytest`` run natively on Windows. The dev container and
CI run on Linux and never need this.

Usage: ``uv run python scripts/install_windows_shims.py``
"""

from __future__ import annotations

import pathlib
import sys
import sysconfig

FCNTL = '''"""Stub of the POSIX fcntl module for Windows development (see scripts/install_windows_shims.py)."""

LOCK_EX = 2
LOCK_NB = 4
LOCK_SH = 1
LOCK_UN = 8


def flock(fd, operation):  # noqa: ANN001, ANN201, ARG001
    """No-op file lock."""
    return None


def fcntl(fd, cmd, arg=0):  # noqa: ANN001, ANN201, ARG001
    """No-op fcntl."""
    return 0
'''

RESOURCE = '''"""Stub of the POSIX resource module for Windows development (see scripts/install_windows_shims.py)."""

RLIMIT_NOFILE = 7
RLIM_INFINITY = -1


def getrlimit(resource):  # noqa: ANN001, ANN201, ARG001
    """Pretend the soft and hard limits are already high."""
    return (65536, 65536)


def setrlimit(resource, limits):  # noqa: ANN001, ANN201, ARG001
    """No-op."""
    return None
'''


def main() -> None:
    if sys.platform != "win32":
        print("not on Windows, nothing to do")
        return
    site = pathlib.Path(sysconfig.get_paths()["purelib"])
    for name, body in (("fcntl.py", FCNTL), ("resource.py", RESOURCE)):
        target = site / name
        if target.exists():
            print(f"{target} exists, skipping")
            continue
        target.write_text(body, encoding="utf-8")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
