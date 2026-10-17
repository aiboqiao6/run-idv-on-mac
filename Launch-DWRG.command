#!/bin/bash
set -euo pipefail

work_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin=""
for candidate in "$(command -v python3 || true)" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        python_bin="$candidate"
        break
    fi
done
if [[ -z "$python_bin" ]]; then
    printf '需要 Python 3.10 或更新版本。请安装后重试。\n' >&2
    exit 1
fi

"$python_bin" -B "$work_dir/pc-support-tools/launcher.py" "$@" && status=0 || status=$?
if [[ "$status" -ne 0 && -t 0 && "$#" -eq 0 ]]; then
    read -r -p '启动失败，按回车关闭窗口。' _reply
fi
exit "$status"
