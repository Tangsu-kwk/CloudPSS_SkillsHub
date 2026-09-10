"""CloudPSS SDK type and create-only persistence boundary."""

import copy
import os
import re


def json_value(value):
    if hasattr(value, "toJSON"):
        return json_value(value.toJSON())
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def validate_rid(rid):
    if not isinstance(rid, str) or not re.fullmatch(r"model/[^/\s]+/[-_A-Za-z0-9]+", rid):
        raise ValueError("Expected full RID: model/<owner>/<key>")
    return rid


class SDKAdapter:
    def configure(self, token=None, api_url=None):
        import cloudpss
        if api_url:
            os.environ["CLOUDPSS_API_URL"] = api_url
        if token:
            cloudpss.setToken(token.strip())

    def fetch(self, rid):
        import cloudpss
        return cloudpss.Model.fetch(rid)

    def component(self, data):
        from cloudpss.model.implements.component import Component
        return Component(copy.deepcopy(data))

    def revision(self, data):
        from cloudpss.model.revision import ModelRevision
        return ModelRevision(copy.deepcopy(data))

    def topology(self, project):
        import cloudpss
        configs = project.configs
        selected = project.context.get("currentConfig")
        if isinstance(configs, list):
            if type(selected) is not int or not 0 <= selected < len(configs):
                raise ValueError("currentConfig must index configs")
        elif not isinstance(configs, dict) or selected not in configs:
            raise ValueError("currentConfig does not identify a config")
        revision = json_value(cloudpss.ModelRevision.create(project.revision))
        topology = json_value(cloudpss.ModelTopology.fetch(
            revision["hash"], "emtp", configs[selected], maximumDepth=0))
        return {"revision_hash": revision["hash"], "topology": topology,
                "component_count": len(topology.get("components", {}))}

    def create_copy(self, project, rid, name=None, desc=None):
        import cloudpss
        validate_rid(rid)
        candidate = copy.deepcopy(project)
        candidate.rid = rid
        if name is not None:
            candidate.name = name
        if desc is not None:
            candidate.description = desc
        # Model.save(key) first calls update. Only create enforces no overwrite.
        response = json_value(cloudpss.Model.create(candidate))
        if not isinstance(response, dict) or response.get("errors"):
            return {"status": "save_failed", "saved_rid": None,
                    "saved_to_cloud": False, "error": "CloudPSS rejected model creation"}
        created = (response.get("data") or {}).get("createModel") or {}
        if created.get("rid") != rid:
            return {"status": "save_outcome_unknown", "saved_rid": rid,
                    "saved_to_cloud": None, "error": "Unexpected create response; inspect RID before retry"}
        try:
            loaded = self.fetch(rid)
            expected = json_value(project.revision.implements)
            actual = json_value(loaded.revision.implements)
            verified = (loaded.rid == rid and actual == expected
                        and json_value(loaded.configs) == json_value(project.configs)
                        and json_value(loaded.jobs) == json_value(project.jobs))
        except Exception:
            verified = False
        return {"status": "saved" if verified else "saved_unverified", "saved_rid": rid,
                "saved_to_cloud": True, "readback_verified": verified}
