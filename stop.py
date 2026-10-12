# SPDX-License-Identifier: GPL-3.0-only
"""Stop only processes belonging to this repository's repaired application."""

import os
import subprocess


def matching_pids(processes, executable):
    raise NotImplementedError("Exact process selection is not implemented")


def stop_game(app):
    raise NotImplementedError("Scoped application shutdown is not implemented")
