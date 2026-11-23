"""Check the two proposed wire terminals in the current parameter scheme."""

import math

from auto_modeling.connection_checks import check_connection_groups
from auto_modeling.diagram_connections import _DiagramScope, _args, _condition, _evaluate
from auto_modeling.dynamic_pins import check_pin_definitions, pinlike_pins
from auto_modeling.job_inputs import _FAIL, _expression, _js_truth, _number, evaluate_args


class DiagramVariables(dict):
    """Resolve diagram variables only when the two instances reference them."""

    def __init__(self, values, document):
        super().__init__(values)
        self.scope = _DiagramScope({}, None, document, self)
        self.resolving = set()

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if _expression(value):
            if key in self.resolving:
                raise ValueError(f"Cyclic diagram variable expression: {key}")
            self.resolving.add(key)
            try:
                value = self[key] = _evaluate(self.scope, value)
            finally:
                self.resolving.remove(key)
        return value


def check_connection(model, source, target, resolve):
    document = model.toJSON()
    revision = document["revision"]
    diagram = revision["implements"]["diagram"]
    index = document.get("context", {}).get("currentConfig", 0)
    if type(index) is not int or not 0 <= index < len(document["configs"]):
        raise ValueError("No valid current parameter scheme for wire preview")
    globals_ = DiagramVariables(
        evaluate_args(document["configs"][index].get("args", {}), revision.get("parameters", [])),
        document,
    )
    for variable in diagram.get("variables", []):
        name = variable["key"]
        if name in globals_:
            raise ValueError(f"Duplicate diagram variable: {name}")
        globals_[name] = variable["value"]

    components, pins, infos, dimensions = {}, {}, {}, {}
    for terminal in (source, target):
        cid, key = terminal["cell"], terminal["port"]
        cell = diagram["cells"][cid]
        rid = cell["definition"]
        definition = resolve(rid)
        parameters = definition.get("parameters", [])
        args = _args(cell.get("args") or {}, parameters, cell, document, globals_)
        scope = _DiagramScope(args, cell, document, globals_)
        raw_enabled = (cell.get("props") or {}).get("enabled")
        if raw_enabled is not None and not _js_truth(_evaluate(scope, raw_enabled)):
            raise ValueError(f"Component {cid} is disabled by enabled={raw_enabled!r}")

        ordinary = check_pin_definitions({"rid": rid, "revision": {"pins": definition.get("pins", [])}}, args)
        pin = next((pin for pin in ordinary if pin["key"] == key), None)
        location = "pins"
        conditions = [pin.get("condition")] if pin is not None else []
        if pin is None:
            pin = next((pin for pin in pinlike_pins(definition, args) if pin["key"] == key), None)
            if pin is None:
                raise ValueError(f"Port {cid}.{key} not found in the current parameter scheme")
            location = "args"
            conditions = [condition for group in parameters for item in group.get("items", [])
                          if item.get("key") == key for condition in (group.get("condition"), item.get("condition"))]
        for condition in conditions:
            if not _condition(scope, condition):
                raise ValueError(f"Port {cid}.{key} is disabled by condition {condition!r}")

        path = f"{cid}.{location}.{key}"
        dims = []
        for axis, value in zip(("X", "Y"), [*(pin.get("dim") or []), 0, 0]):
            expr = {"source": str(value or 0), "ɵexp": ""}
            number = _number(_evaluate(scope, expr))
            if number is _FAIL or not math.isfinite(number):
                raise ValueError(f"Unable to evaluate {axis} dimension of port {cid}.{key}: {value!r}")
            dims.append(number)

        components[cid] = {"definition": rid, "enabled": True}
        pins[path] = pin
        infos[path] = {"key": cid, "pin": key}
        dimensions[path] = dims

    problems = check_connection_groups({"proposed": list(pins)}, components=components, pins=pins,
                                       pin_info=infos, port_group=(), dimensions=dimensions)
    if problems:
        messages = ", ".join(dict.fromkeys(problem["message"] for problem in problems))
        details = " and ".join(
            f"{info['key']}.{info['pin']} ({pins[path].get('connection')}, {dimensions[path]})"
            for path, info in infos.items()
        )
        raise ValueError(f"Cannot connect {details}: {messages}")
