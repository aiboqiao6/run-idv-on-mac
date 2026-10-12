# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a local workcopy of an already-installed PlayCover application."""

import subprocess


def scoped_entitlements(entitlements, app):
    raise NotImplementedError("Workcopy sandbox preparation is not implemented")


def build_workcopy(source, output):
    raise NotImplementedError("Local workcopy preparation is not implemented")
