"""Optional explicit YAML configuration; environment values take priority."""
import os
from pathlib import Path


def configure_cloudpss(config_path=None):
    selected = config_path or os.environ.get('AUTOMODELING_CONFIG')
    if selected is None:
        return  # Environment-only use does not read an implicit repository file.
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
    for env, value in values.items():
        if not os.environ.get(env, '').strip():
            os.environ[env] = value
    if 'CLOUDPSS_API_URL' in values and 'CLOUDPSS_TOKEN' not in values \
            and (os.environ.get('CLOUDPSS_TOKEN', '').strip()
                 or os.environ.get('CLOUDPSS_LOGIN_TOKEN', '').strip()):
        # 同源配对: 环境令牌 + YAML 地址的组合可把受信令牌发给未受信主机
        raise ValueError('Refusing to pair an environment token with a YAML-supplied api_url; '
                         'configure token and api_url in the same source')
