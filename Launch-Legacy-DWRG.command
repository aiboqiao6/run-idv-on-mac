#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

work_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app="$work_dir/work/DWRG-PathFixed.app"
documents="$HOME/Library/Containers/com.netease.id5/Data/Documents"

if [[ ! -d "$app" || ! -f "$app/client" ]]; then
    printf 'Missing repaired application: %s\n' "$app" >&2
    exit 1
fi
if [[ ! -d "$documents" ]]; then
    printf 'Missing game Documents directory: %s\n' "$documents" >&2
    exit 1
fi

codesign --verify --deep --strict "$app"
mkdir -p -- "$documents/local_shader_cache/res3"
open "$app" --args -ApplePersistenceIgnoreState YES
