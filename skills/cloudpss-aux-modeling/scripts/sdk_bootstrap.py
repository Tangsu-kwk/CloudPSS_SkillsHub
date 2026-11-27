"""Load the bundled wheel from a process-private extraction.

Shared temporary locations and home directories do not prove cache isolation,
so only the current process reuses its own verified extraction.
"""
import hashlib
import io
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
_ACTIVE_CACHE: Path | None = None


def _loaded_from(module, cache):
    filename = getattr(module, '__file__', None)
    return bool(filename and Path(filename).resolve().is_relative_to(cache.resolve()))


def activate():
    global _ACTIVE_CACHE
    loaded = sys.modules.get('auto_modeling')
    if _ACTIVE_CACHE is not None and _ACTIVE_CACHE.is_dir():
        if loaded is None or _loaded_from(loaded, _ACTIVE_CACHE):
            return _ACTIVE_CACHE
    if loaded is not None:
        raise RuntimeError('A different auto_modeling is already loaded; use a fresh Python process')
    cleanup()
    manifest = json.loads((SKILL / 'assets/sdk/bundle.json').read_text(encoding='utf-8'))
    wheel = SKILL / 'assets/sdk' / manifest['wheel']
    wheel_bytes = wheel.read_bytes()
    if hashlib.sha256(wheel_bytes).hexdigest() != manifest['sha256']:
        raise RuntimeError('Bundled SDK checksum mismatch; restore the verified wheel')
    # Do not put content from a previously populated directory on sys.path.
    cache = Path(tempfile.mkdtemp(prefix='cloudpss-sdk-'))
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
            names = archive.namelist()
            for name in names:
                if not (cache / name).resolve().is_relative_to(cache.resolve()):
                    raise ValueError('Invalid wheel member path')
            members = sorted(name for name in names if not name.endswith('/'))
            expected = {name: hashlib.sha256(archive.read(name)).digest() for name in members}
            archive.extractall(cache)
        extracted = {file.relative_to(cache).as_posix() for file in cache.rglob('*') if not file.is_dir()}
        if extracted != set(expected):
            raise RuntimeError('Extracted SDK file list does not match the verified wheel')
        for name in members:
            file = cache / name
            if (file.is_symlink() or not file.is_file()
                    or hashlib.sha256(file.read_bytes()).digest() != expected[name]):
                raise RuntimeError(f'Extracted SDK checksum mismatch: {name}')
    except BaseException:
        shutil.rmtree(cache)
        raise
    sys.path.insert(0, str(cache))
    _ACTIVE_CACHE = cache
    return cache


def cleanup():
    """Discard this module's private extraction and its auto_modeling imports."""
    global _ACTIVE_CACHE
    cache = _ACTIVE_CACHE
    if cache is None:
        return
    if cache.is_dir():
        shutil.rmtree(cache)
    for name, module in list(sys.modules.items()):
        if (name == 'auto_modeling' or name.startswith('auto_modeling.')) and _loaded_from(module, cache):
            del sys.modules[name]
    if str(cache) in sys.path:
        sys.path.remove(str(cache))
    _ACTIVE_CACHE = None


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
    for name, expected in [('cloudpss', '5.0.9'), ('mirascript', '0.1.103')]:
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
