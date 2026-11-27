"""Load the bundled wheel without depending on the original development tree."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

SKILL = Path(__file__).resolve().parents[1]


def activate():
    manifest = json.loads((SKILL / 'assets/sdk/bundle.json').read_text(encoding='utf-8'))
    wheel = SKILL / 'assets/sdk' / manifest['wheel']
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != manifest['sha256']:
        raise RuntimeError('Bundled SDK checksum mismatch; restore the verified wheel')
    # 缓存目录必须用户私有: 共享临时目录(如 POSIX /tmp)可被其他本地账号预置,
    # 仅凭 .ready 存在就把缓存加入 sys.path 首位, 会让未校验代码获得导入优先权。
    # 改用用户主目录(多用户系统上 ACL 隔离), 并在命中前校验 .ready 内容与 wheel 摘要一致。
    cache = Path.home() / '.cache' / 'cloudpss-shitu-sdk' / digest
    ready = cache / '.ready'
    if ready.is_file():
        try:
            ready_ok = ready.read_text(encoding='ascii').strip() == digest
        except (OSError, UnicodeDecodeError):
            ready_ok = False
        if not ready_ok:
            shutil.rmtree(cache, ignore_errors=True)  # 缓存损坏/被篡改: 重建
    if not ready.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='extract-', dir=cache.parent))
        try:
            with zipfile.ZipFile(wheel) as archive:
                for name in archive.namelist():
                    if not (staging / name).resolve().is_relative_to(staging.resolve()):
                        raise ValueError('Invalid wheel member path')
                archive.extractall(staging)
            (staging / '.ready').write_text(digest, encoding='ascii')
            try:
                staging.rename(cache)
            except OSError:
                if not ready.is_file():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    loaded = sys.modules.get('auto_modeling')
    if loaded and not Path(loaded.__file__).resolve().is_relative_to(cache.resolve()):
        raise RuntimeError('A different auto_modeling is already loaded; use a fresh Python process')
    sys.path.insert(0, str(cache))
    return cache


def doctor(*, check_auth=False, config=None):
    cache = activate()
    from configure_cloudpss import configure_cloudpss
    # Explicit auth check loads only the requested configuration, without printing it.
    if check_auth:
        configure_cloudpss(config)
    versions = {}
    for name in ('cloudpss', 'mirascript', 'requests', 'py-ubjson', 'websocket-client', 'PyYAML'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    issues = [name + ' is missing' for name, value in versions.items() if value is None]
    for name, expected in [('cloudpss', '5.0.10'), ('mirascript', '0.1.103')]:
        if versions[name] is not None and versions[name] != expected:
            issues.append(name + ' version differs from validated ' + expected)
    if sys.version_info < (3, 12):
        issues.append('Python >=3.12 is required')
    auth = bool(os.environ.get('CLOUDPSS_TOKEN', '').strip()) if check_auth else None
    if check_auth and not auth:
        issues.append('CLOUDPSS_TOKEN is missing; inject credentials or provide --config')
    return {'status': 'issues' if issues else 'ok', 'python': sys.executable,
            'skill': str(SKILL), 'sdk_runtime': str(cache), 'dependencies': versions,
            'token_configured': auth, 'authentication_verified_online': False,
            'node_available': bool(os.environ.get('AUTOMODELING_NODE') or shutil.which('node')),
            'plot_render_packages': {name: importlib.util.find_spec(name) is not None for name in ('plotly', 'kaleido')},
            'issues': issues, 'network_used': False}
