"""Install bundled SDK dependencies into a task-owned virtual environment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

SKILL = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', type=Path, required=True, help='Task-owned environment path')
    parser.add_argument('--plots', action='store_true', help='Include optional Plotly/Kaleido image rendering')
    args = parser.parse_args()
    target = args.venv.resolve()
    if target.exists() and not (target / 'pyvenv.cfg').is_file():
        raise ValueError('Target exists and is not a virtual environment; choose a new path')
    if not target.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    manifest = json.loads((SKILL / 'assets/sdk/bundle.json').read_text(encoding='utf-8'))
    from sdk_bootstrap import activate
    cache = activate()
    try:
        wheel = cache / Path(manifest['wheel']).name
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest['sha256']:
            raise RuntimeError('Private SDK wheel copy checksum mismatch')
        wheel_arg = str(wheel) + ('[job-plots]' if args.plots else '')
        result = subprocess.run([str(python), '-m', 'pip', 'install', wheel_arg], check=False)
    finally:
        sys.path.remove(str(cache))
        shutil.rmtree(cache)
    if result.returncode:
        return result.returncode
    print(json.dumps({'status': 'installed', 'python': str(python), 'plots': args.plots}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
