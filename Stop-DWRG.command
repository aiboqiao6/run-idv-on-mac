#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

work_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$work_dir/stop.py"
