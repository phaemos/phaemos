"""The boot, seq and up fields that protect a machine from replayed posts.

The API refuses a post whose (boot, seq) is not newer than the last one it accepted for the key. boot is
kept in a small file in the state folder: mode 0600 in a folder of mode 0700, one file per key, named by a
hash of the key and never holding it. At each start boot becomes the larger of the stored value plus one
and the Unix time in seconds (capped at the API's limit), so it still rises if the file was wiped. seq
starts at 0 for each run. Two programs started in the same second with the same key can get the same boot,
so run one at a time per key.
"""

import contextlib
import hashlib
import os
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MAX_BOOT = 2_147_483_647
MAX_SEQ = 4_294_967_295


def state_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """PHAEMOS_STATE_DIR, else XDG_STATE_HOME/phaemos, else ~/.local/state/phaemos."""
    env = os.environ if environ is None else environ
    if env.get("PHAEMOS_STATE_DIR"):
        return Path(env["PHAEMOS_STATE_DIR"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / "phaemos"
    if env.get("HOME"):
        return Path(env["HOME"]) / ".local" / "state" / "phaemos"
    return None


class ReplayCounter:
    """Stamps readings with boot, seq and up."""

    def __init__(
        self,
        key: str,
        directory: Path | None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.warning = ""
        self._lock = threading.Lock()
        self._seq = 0
        self._monotonic = monotonic
        self._start = monotonic()
        self.boot = min(int(clock()), MAX_BOOT)
        if directory is None:
            self.warning = (
                "no state folder (set PHAEMOS_STATE_DIR or HOME): boot comes from the clock and is not stored"
            )
            return
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        path = directory / f"boot-{digest}"
        try:
            previous = int(path.read_text().strip())
        except FileNotFoundError:
            previous = 0
        except (OSError, ValueError) as error:
            previous = 0
            self.warning = f"the boot counter file is unreadable, so boot comes from the clock only: {error}"
        self.boot = min(max(previous + 1, self.boot), MAX_BOOT)
        try:
            _store(directory, path, self.boot)
        except OSError as error:
            if not self.warning:
                self.warning = (
                    f"the boot counter could not be stored ({error}): a later run may repeat a boot"
                )

    def stamp(self, reading: Mapping[str, Any]) -> dict[str, Any]:
        """A copy of the reading with boot, seq and up added. A reading that already carries boot or seq
        is returned as it is, because the caller chose them."""
        out = dict(reading)
        if "boot" in out or "seq" in out:
            return out
        with self._lock:
            if self._seq > MAX_SEQ:
                raise RuntimeError("the sequence number is used up for this run")
            out["boot"] = self.boot
            out["seq"] = self._seq
            out["up"] = int(self._monotonic() - self._start)
            self._seq += 1
        return out


def _store(directory: Path, path: Path, boot: int) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(directory)
    if os.path.islink(directory) or not os.path.isdir(directory):
        raise OSError(f"{directory} is not a plain folder")
    if info.st_mode & 0o022:
        raise OSError(f"{directory} can be written by other users")
    temp = path.with_name(path.name + ".tmp")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(temp)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(f"{boot}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
