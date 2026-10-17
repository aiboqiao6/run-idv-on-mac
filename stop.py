# SPDX-License-Identifier: GPL-3.0-only
"""Stop only processes belonging to this repository's repaired application."""

import os
import signal
import subprocess
import sys
from pathlib import Path


def matching_pids(processes, executable):
    """Select an exact executable path, never a basename or substring."""
    if (not isinstance(processes, str) or not isinstance(executable, str)
            or not os.path.isabs(executable)):
        raise ValueError("Expected process text and an absolute executable path")
    result = []
    for line in processes.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        if pid > 0 and (command == executable or command.startswith(executable + " ")):
            result.append(pid)
    return result


def stop_game(app):
    executable = str(Path(app).resolve() / "client")
    processes = subprocess.run(["ps", "-axww", "-o", "pid=,command="], check=True,
                               capture_output=True, text=True, timeout=10)
    count = 0
    for pid in matching_pids(processes.stdout, executable):
        # Recheck after enumeration so an already-reused PID is not signaled.
        current = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="],
                                 capture_output=True, text=True, timeout=10)
        if current.returncode == 1:
            continue
        current.check_returncode()
        if not matching_pids(f"{pid} {current.stdout.strip()}", executable):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        count += 1
    return count


def main():
    if sys.platform != "darwin":
        print("Shutdown requires macOS.", file=sys.stderr)
        return 1
    try:
        root = Path(__file__).resolve().parent
        count = sum(stop_game(root / relative) for relative in
                    ('.pc-launcher/DWRG-PC.app', 'work/DWRG-PathFixed.app'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Shutdown failed: {error}", file=sys.stderr)
        return 1
    print(f"Stop requested for {count} repaired game process(es).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
