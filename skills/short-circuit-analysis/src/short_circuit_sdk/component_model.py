"""Read-only functions from the bundled automodeling 0.1.0 SDK."""
def _error_diagnostics(errors):
    """Keep diagnostic fields only; never emit full extensions or request data."""
    import os
    import re

    def clean(value):
        text = str(value)
        token = os.environ.get("CLOUDPSS_TOKEN")
        if token:
            text = text.replace(token, "[REDACTED]")
        return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)[:2000]

    result = []
    for error in errors if isinstance(errors, list) else []:
        if not isinstance(error, dict):
            continue
        item = {"message": clean(error.get("message", "Unknown GraphQL error"))}
        if isinstance(error.get("path"), list):
            item["path"] = [clean(part) for part in error["path"]]
        extensions = error.get("extensions")
        if isinstance(extensions, dict):
            for key in ("code", "status", "statusCode"):
                if key in extensions:
                    item[key] = clean(extensions[key])
        result.append(item)
    return result
