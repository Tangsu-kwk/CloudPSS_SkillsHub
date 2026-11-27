"""Optional explicit YAML configuration; environment values take priority."""
import os
from pathlib import Path
import sys


_ORIGINAL_ENV = dict(os.environ)
_INJECTED: dict[str, str] = {}


def configure_cloudpss(config_path=None):
    selected = config_path or _ORIGINAL_ENV.get('AUTOMODELING_CONFIG')
    values = _read_settings(selected) if selected is not None else {}
    env_token = next((token for name in ('CLOUDPSS_TOKEN', 'CLOUDPSS_LOGIN_TOKEN', 'SIMSTUDIO_TOKEN')
                      if (token := _ORIGINAL_ENV.get(name, '').strip())), '')
    env_url = _ORIGINAL_ENV.get('CLOUDPSS_API_URL', '').strip()
    token = env_token or values.get('CLOUDPSS_TOKEN', '').strip()
    url = env_url or values.get('CLOUDPSS_API_URL', '').strip()
    token_source = ('environment' if env_token else 'YAML') if token else None
    url_source = ('environment' if env_url else 'YAML') if url else None
    if token_source and url_source and token_source != url_source:
        # 仅部署方可在进程环境授权，Agent 不得代为设置；不读取 YAML 开关。
        if os.environ.get('CLOUDPSS_ALLOW_MIXED_CONFIG', '').strip().lower() not in ('1', 'true', 'yes'):
            raise ValueError('Refusing to pair CloudPSS token and api_url from different sources; '
                             'configure both in the environment or both in YAML')
        print('[WARN] 混源/未授权端点配置已由 CLOUDPSS_ALLOW_MIXED_CONFIG 放行（部署方显式授权）',
              file=sys.stderr)
    effective = {
        'CLOUDPSS_TOKEN': (token, token_source),
        'CLOUDPSS_API_URL': (url, url_source),
    }
    # Restore the import-time environment before applying a different config.
    for name in _INJECTED:
        if name in _ORIGINAL_ENV:
            os.environ[name] = _ORIGINAL_ENV[name]
        else:
            os.environ.pop(name, None)
    _INJECTED.clear()
    for name, (value, source) in effective.items():
        if source is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
            _INJECTED[name] = source


def _read_settings(selected):
    path = Path(selected).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Specified CloudPSS configuration file does not exist')
    import yaml
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
        settings = data.get('cloudpss_settings', {})
        if not isinstance(settings, dict):
            raise ValueError
        values = {}
        for key, env in [('token', 'CLOUDPSS_TOKEN'), ('api_url', 'CLOUDPSS_API_URL')]:
            value = settings.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError
                values[env] = value
    except Exception:
        raise ValueError('Cannot read CloudPSS YAML settings; check file structure') from None
    return values
