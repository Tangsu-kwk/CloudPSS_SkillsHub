"""Optional explicit YAML configuration; environment values take priority."""
import os
from pathlib import Path


def configure_cloudpss(config_path=None):
    selected = config_path or os.environ.get('AUTOMODELING_CONFIG')
    values = _read_settings(selected) if selected is not None else {}
    env_token = next((token for name in ('CLOUDPSS_TOKEN', 'CLOUDPSS_LOGIN_TOKEN', 'SIMSTUDIO_TOKEN')
                      if (token := os.environ.get(name, '').strip())), '')
    env_url = os.environ.get('CLOUDPSS_API_URL', '').strip()
    token = env_token or values.get('CLOUDPSS_TOKEN', '').strip()
    url = env_url or values.get('CLOUDPSS_API_URL', '').strip()
    token_source = ('environment' if env_token else 'YAML') if token else None
    url_source = ('environment' if env_url else 'YAML') if url else None
    if token_source and url_source and token_source != url_source:
        raise ValueError('Refusing to pair CloudPSS token and api_url from different sources; '
                         'configure both in the environment or both in YAML')
    if token:
        os.environ['CLOUDPSS_TOKEN'] = token
    if url:
        os.environ['CLOUDPSS_API_URL'] = url


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
