"""Core modeling methods migrated from FuZhuJM2/CaseEditToolbox.py.

Names and call shapes follow the reference. SDK errors now raise, key collisions
are rejected, and saveProject creates only. Simulation/report methods stay out.
"""

import copy
import json
import os
from pathlib import Path

from .sdk_adapter import SDKAdapter, json_value, validate_rid


def source(value):
    return value.get("source") if isinstance(value, dict) and "source" in value else value


def merge_fields(current, changes, *, pins=False):
    if not isinstance(changes, dict):
        raise TypeError("args/pins must be objects")
    unknown = set(changes) - set(current)
    if unknown:
        raise ValueError(f"Unknown {'pins' if pins else 'parameters'}: {sorted(unknown)}")
    result = copy.deepcopy(current)
    for key, value in changes.items():
        if pins and not isinstance(value, str):
            raise TypeError(f"Pin {key} must be a connection-name string")
        if not pins and (value is None or isinstance(value, list)
                         or isinstance(value, dict) and "source" not in value):
            raise TypeError(f"Parameter {key} requires a scalar or source expression")
        old = current[key]
        if isinstance(old, dict) and "source" in old:
            result[key] = {**copy.deepcopy(old), **(copy.deepcopy(value) if isinstance(value, dict)
                                                   else {"source": value})}
        else:
            result[key] = copy.deepcopy(value)
    return result


class CaseEditToolbox:
    def __init__(self, *, adapter=None):
        self.adapter = adapter or SDKAdapter()
        self.config = {"token": os.getenv("SIMSTUDIO_TOKEN"),
                       "apiURL": os.getenv("CLOUDPSS_API_URL", "https://cloudpss.net/"),
                       "username": None, "model": None, "comLibName": "saSource.json",
                       "deleteEdges": True, "iGraph": False}
        self.project = None
        self.original_rid = None
        self.compLib, self.compCount, self.pos = {}, {}, {}
        self.compLabelDict, self.channelPinDict = {}, {}
        self.current_canvas = None
        self.topo = None
        self.connection_edges_before = {}
        self.connection_components_before = {}
        self.connection_snapshot_available = False

    def setConfig(self, token=None, apiURL=None, username=None, model=None,
                  comLibName=None, iGraph=None):
        values = dict(token=token, apiURL=apiURL, username=username, model=model,
                      comLibName=comLibName, iGraph=iGraph)
        for key, value in values.items():
            if value is not None:
                if key == "iGraph":
                    if type(value) is not bool:
                        raise TypeError("iGraph must be boolean")
                    if value:
                        raise NotImplementedError("Network visualization is not migrated")
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{key} must be a nonempty string")
                self.config[key] = value
        self.adapter.configure(self.config["token"], self.config["apiURL"])

    def loadComponentLibrary(self):
        path = Path(self.config["comLibName"])
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        self.compLib = json.loads(path.read_text(encoding="utf-8"))
        self.compCount = {key: 0 for key in self.compLib}

    def setInitialConditions(self, *, project=None):
        """Optional project injection reuses a host model without fetching again."""
        self.adapter.configure(self.config["token"], self.config["apiURL"])
        rid = f"model/{self.config['username']}/{self.config['model']}"
        self.project = project if project is not None else self.adapter.fetch(validate_rid(rid))
        self.original_rid = getattr(self.project, "rid", None) or rid
        self.loadComponentLibrary()
        self.pos = {}
        self.topo = None
        self.connection_edges_before = {}
        self.connection_components_before = {}
        self.connection_snapshot_available = False
        edge_count_before = sum(1 for c in self.getAllComponents().values()
                                if getattr(c, "shape", None) == "diagram-edge")
        self.connection_audit = {
            "mode": "pin" if self.config["deleteEdges"] else "preserved",
            "converted": False,
            "diagram_edge_count_before": edge_count_before,
            "diagram_edge_count_removed": 0,
            "diagram_edge_count_after": edge_count_before,
        }
        if self.config["deleteEdges"] and edge_count_before:
            # Normalize an isolated copy. Failed topology resolution or a
            # changed connection partition must not mutate the caller's model.
            original = self.project
            self.project = copy.deepcopy(original)
            try:
                before = self.refreshTopology()
                before_groups = self._connection_groups(self.topo)
                self.connection_edges_before = {
                    key: json_value(comp) for key, comp in self.getAllComponents().items()
                    if getattr(comp, "shape", None) == "diagram-edge"
                }
                self.connection_components_before = {
                    key: {"label": getattr(comp, "label", None),
                          "pins": copy.deepcopy(getattr(comp, "pins", {}) or {})}
                    for key, comp in self.getAllComponents().items()
                    if getattr(comp, "shape", None) == "diagram-component"
                }
                removed_edges = self.deleteEdges()
                after = self.refreshTopology()
                if self._connection_groups(self.topo) != before_groups:
                    raise ValueError("Edge-to-pin conversion changed topology connections")
                converted_cells = copy.deepcopy(self.getAllComponents())
                if any(getattr(c, "shape", None) == "diagram-edge" for c in converted_cells.values()):
                    raise ValueError("Edge-to-pin conversion left graphical edges")
            except Exception:
                self.project = original
                self.topo = None
                self.connection_audit = {"mode": "uninitialized", "status": "conversion_failed"}
                self.connection_edges_before = {}
                self.connection_components_before = {}
                raise
            self.project = original
            self.connection_snapshot_available = True
            # Preserve host project/revision identity after full verification.
            original.revision.implements.diagram.cells.clear()
            original.revision.implements.diagram.cells.update(converted_cells)
            self.connection_audit.update(
                converted=True, status="topology_equivalent",
                diagram_edge_count_removed=len(removed_edges), diagram_edge_count_after=0,
                before_revision_hash=before["revision_hash"],
                after_revision_hash=after["revision_hash"],
                connected_net_count=len(before_groups[0]),
            )
        elif self.config["deleteEdges"]:
            self.connection_audit["status"] = "no_edges_to_convert"
        self.setCompLabelDict()
        self.setChannelPinDict()
        canvases = self.project.revision.implements.diagram.canvas
        self.current_canvas = canvases[0]["key"] if canvases else None
        for canvas in canvases:
            self.initCanvasPos(canvas["key"])

    @staticmethod
    def _connection_groups(topology):
        """Compare net membership, not platform-generated node numbers."""
        groups, empty = {}, set()
        for path, comp in topology.get("components", {}).items():
            for pin, node in (comp.get("pins") or {}).items():
                endpoint = (path, str(pin))
                if node in (None, ""):
                    empty.add(endpoint)
                else:
                    groups.setdefault(str(node), set()).add(endpoint)
        return frozenset(frozenset(group) for group in groups.values()), frozenset(empty)

    def getRevision(self, file=None):
        data = copy.deepcopy(json_value(self.project.revision))
        if file is not None:
            directory = Path(file)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "revision.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def loadRevision(self, revision=None, file=None):
        if (revision is None) == (file is None):
            raise ValueError("Provide exactly one of revision or file")
        data = revision if file is None else json.loads(Path(file).read_text(encoding="utf-8"))
        self.project.revision = self.adapter.revision(data)
        self.connection_edges_before = {}
        self.connection_components_before = {}
        self.connection_snapshot_available = False
        self.topo = None
        self.setCompLabelDict()
        self.setChannelPinDict()
        self.pos = {}
        for canvas in self.project.revision.implements.diagram.canvas:
            self.initCanvasPos(canvas["key"])

    def getAllComponents(self):
        return self.project.revision.implements.diagram.cells

    def getComponentByKey(self, key):
        return self.getAllComponents()[key]

    def getComponentsByRid(self, rid):
        return {k: c for k, c in self.getAllComponents().items() if getattr(c, "definition", None) == rid}

    @staticmethod
    def _page(items, offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset >= 0 and 1 <= limit <= 100 required")
        return {"total": len(items), "items": copy.deepcopy(items[offset:offset + limit]),
                "offset": offset, "next_offset": offset + limit if offset + limit < len(items) else None}

    def getConnections(self, identifier=None, *, pin=None, node=None, offset=0, limit=20):
        """Read endpoints of selected networks; empty pins never form a net.

        Uses the last refreshed topology when present, otherwise exact named
        pins. Does not silently refresh topology or modify the working model.
        """
        if (identifier is None) == (node is None):
            raise ValueError("Provide exactly one of identifier or node")
        if node is not None and (not isinstance(node, str) or not node.strip()):
            raise ValueError("node must be a nonempty exact pin name")
        if pin is not None and (identifier is None or not isinstance(pin, str)):
            raise ValueError("pin requires identifier and a string pin key")
        key = self._resolve_comp_key(identifier) if identifier is not None else None
        if key is not None:
            comp = self.getComponentByKey(key)
            if getattr(comp, "shape", None) != "diagram-component":
                raise ValueError("identifier must select a component")
            if pin is not None and pin not in comp.pins:
                raise ValueError("Unknown component pin")
        entries = []
        topology = (self.topo or {}).get("components", {})
        for cid, comp in sorted(self.getAllComponents().items()):
            if getattr(comp, "shape", None) != "diagram-component":
                continue
            for p, name in sorted((getattr(comp, "pins", {}) or {}).items()):
                top_node = topology.get('/' + cid, {}).get('pins', {}).get(p)
                entries.append({"key": cid, "label": getattr(comp, "label", None),
                                "canvas": getattr(comp, "canvas", None), "pin": p,
                                "node": name, "topology_node": top_node})
        def group(e):
            if self.topo is not None:
                n = e['topology_node']
                return ('topology', str(n)) if n not in (None, '') else None
            return ('named_pin', e['node']) if e['node'] else None
        selected = ([e for e in entries if e['key'] == key and (pin is None or e['pin'] == pin)]
                    if key is not None else [e for e in entries if e['node'] == node])
        groups = {group(e) for e in selected} - {None}
        endpoints = {(e['key'], e['pin']) for e in selected}
        items = [dict(e, selected=(e['key'], e['pin']) in endpoints)
                 for e in entries if group(e) in groups or (e['key'], e['pin']) in endpoints]
        return {"basis": "refreshed_topology" if self.topo is not None else "named_pins_only",
                "physical_validation": False, "selected_pin_count": len(selected),
                **self._page(items, offset, limit)}

    def getDiagramEdges(self, identifier=None, *, view="original", offset=0, limit=20):
        """Read current edges or immutable initialization provenance.

        Incident edges include edge-to-edge branches, never traverse through
        component interiors. Raw endpoints are retained; no invented pin ids.
        """
        if view not in {"original", "current"}:
            raise ValueError("view must be original or current")
        if identifier is not None and (not isinstance(identifier, str) or not identifier.strip()):
            raise ValueError("identifier must be nonempty")
        historical = view == "original"
        if historical:
            edges = self.connection_edges_before
            components = self.connection_components_before
        else:
            edges = {k: json_value(c) for k, c in self.getAllComponents().items()
                     if getattr(c, "shape", None) == "diagram-edge"}
            components = {k: json_value(c) for k, c in self.getAllComponents().items()
                          if getattr(c, "shape", None) == "diagram-component"}
        available = self.connection_snapshot_available if historical else True
        if not available:
            return {"view": view, "snapshot_available": False, "reason": "No initialization edge snapshot in this session",
                    **self._page([], offset, limit)}
        selected = set(edges)
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("identifier must be nonempty")
            if identifier in edges or identifier in components:
                key = identifier
            else:
                matches = [k for k, c in components.items() if c.get('label') == identifier]
                if len(matches) != 1:
                    raise ValueError("Unknown or ambiguous snapshot identifier; use exact key")
                key = matches[0]
            selected = {key} if key in edges else {k for k,e in edges.items()
                        if any((e.get(s) or {}).get('cell') == key for s in ('source','target'))}
            while True:
                expanded = selected | {k for k,e in edges.items() if k in selected or
                    any((e.get(s) or {}).get('cell') in selected for s in ('source','target'))}
                for k in selected:
                    expanded.update((edges[k].get(s) or {}).get('cell') for s in ('source','target')
                                    if (edges[k].get(s) or {}).get('cell') in edges)
                if expanded == selected: break
                selected = expanded
        rows=[]
        for k in sorted(selected):
            e=edges[k]
            rows.append({"key":k,"canvas":e.get('canvas'),
                         "source":copy.deepcopy(e.get('source',{})),"target":copy.deepcopy(e.get('target',{})),
                         "historical":historical})
        return {"view":view,"snapshot_available":available,
                "meaning":"initialization snapshot, not current connectivity" if historical else "current diagram edges",
                **self._page(rows,offset,limit)}

    def _resolve_comp_key(self, identifier):
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Component identifier must be a nonempty string")
        identifier = identifier.strip()
        components = self.getAllComponents()
        if identifier in components:
            return identifier
        keys = [k for k, c in components.items() if identifier in
                (getattr(c, "label", None), source(getattr(c, "args", {}).get("Name")))]
        if not keys:
            # User display names are case-insensitive only when unique. SDK keys
            # and definition RIDs remain exact, and ambiguous names always fail.
            keys = [k for k, c in components.items() if any(
                isinstance(name, str) and name.casefold() == identifier.casefold()
                for name in (getattr(c, "label", None), source(getattr(c, "args", {}).get("Name"))))]
        if not keys:
            raise KeyError(f"Component not found: {identifier}")
        if len(keys) != 1:
            raise ValueError(f"Ambiguous component {identifier}: {keys}")
        return keys[0]

    def _resolve_comp_keys(self, identifiers):
        if not isinstance(identifiers, list) or not identifiers:
            raise ValueError("identifiers must be a nonempty list")
        return [self._resolve_comp_key(identifier) for identifier in identifiers]

    def convertLabelToKey(self, labels):
        return {"busIds": self._resolve_comp_keys(labels)}

    def setCompLabelDict(self):
        labels = {}
        for key, comp in self.getAllComponents().items():
            label = getattr(comp, "label", None)
            if label:
                labels.setdefault(label, []).append(key)
        self.compLabelDict = {label: keys[0] for label, keys in labels.items() if len(keys) == 1}

    def setChannelPinDict(self):
        self.channelPinDict = {pin: key for key, comp in
                               self.getComponentsByRid("model/CloudPSS/_newChannel").items()
                               for pin in comp.pins.values() if pin}

    def screenCompByArg(self, compRID, conditions, compList=None):
        conditions = conditions if isinstance(conditions, list) else [conditions]
        selected = set(self._resolve_comp_keys(compList)) if compList is not None else None
        result = {}
        for key, comp in self.getComponentsByRid(compRID).items():
            if selected is not None and key not in selected:
                continue
            for condition in conditions:
                value = comp.label if condition["arg"] == "label" else source(comp.args.get(condition["arg"]))
                if condition.get("Set") is not None and value not in condition["Set"]:
                    break
                try:
                    if condition.get("Min") is not None and float(value) < float(condition["Min"]):
                        break
                    if condition.get("Max") is not None and float(value) > float(condition["Max"]):
                        break
                except (TypeError, ValueError):
                    break
            else:
                result[key] = comp
        return result

    def initCanvasPos(self, canvas):
        self.pos[canvas] = dict(dx=20, dy=20, x0=20, y0=20, x=20, y=20, maxdy=0)

    def createCanvas(self, canvas, name):
        if not canvas or not name:
            raise ValueError("canvas and name are required")
        canvases = self.project.revision.implements.diagram.canvas
        if any(c["key"] == canvas for c in canvases):
            raise ValueError("Canvas already exists")
        canvases.append({"key": canvas, "name": name})
        self.initCanvasPos(canvas)

    def addxPos(self, canvas, compJson, MaxX=None):
        pos = self.pos[canvas]
        pos["x"] += compJson["size"]["width"]
        pos["maxdy"] = max(pos["maxdy"], compJson["size"]["height"])
        if MaxX is not None and pos["x"] > MaxX:
            self.newLinePos(canvas)

    def newLinePos(self, canvas):
        pos = self.pos[canvas]
        pos.update(x=pos["x0"], y=pos["y"] + pos["dy"] + pos["maxdy"], maxdy=0)

    def addComp(self, compJson, id1=None, canvas=None, position=None, args=None, pins=None, label=None):
        data = copy.deepcopy(compJson)
        for key, value in dict(id=id1, canvas=canvas, position=position, label=label).items():
            if value is not None:
                data[key] = copy.deepcopy(value)
        if data["id"] in self.getAllComponents():
            raise ValueError(f"Component key already exists: {data['id']}")
        if not any(c["key"] == data["canvas"] for c in self.project.revision.implements.diagram.canvas):
            raise ValueError("Unknown canvas")
        data["args"] = merge_fields(data.get("args", {}), args or {})
        data["pins"] = merge_fields(data.get("pins", {}), pins or {}, pins=True)
        self.getAllComponents()[data["id"]] = self.adapter.component(data)
        self.topo = None
        self.setCompLabelDict()
        self.setChannelPinDict()

    def addCompInCanvas(self, compJson, key, canvas, addN=None, addN_label=None,
                        args=None, pins=None, label=None, dX=10, MaxX=None):
        if canvas not in self.pos:
            raise ValueError("Canvas position is not initialized")
        count = self.compCount.get(key, 0)
        id1 = key
        if addN is not False:
            count += 1
            while f"{key}_{count}" in self.getAllComponents():
                count += 1
            id1 = f"{key}_{count}"
        label = label or id1
        args = copy.deepcopy(args or {})
        if addN_label:
            label += f"_{count}"
            if "Name" in args:
                args["Name"] = str(source(args["Name"])) + f"_{count}"
        position = {k: self.pos[canvas][k] for k in ("x", "y")}
        self.addComp(compJson, id1, canvas, position, args, pins, label)
        self.compCount[key] = count
        self.addxPos(canvas, compJson, MaxX)
        self.pos[canvas]["x"] += dX
        return id1, label

    def updateCompArgs(self, args, compId):
        comp = self.getComponentByKey(self._resolve_comp_key(compId))
        comp.args = merge_fields(comp.args, args)
        self.topo = None
        return "更新成功"

    def deleteComponent(self, compId):
        """New method: remove an instance and its incident diagram edges."""
        key = self._resolve_comp_key(compId)
        comp = self.getComponentByKey(key)
        if getattr(comp, "shape", None) != "diagram-component":
            raise ValueError("deleteComponent requires a diagram-component")
        removed = {key}
        # Include edges attached to edges to avoid dangling diagram references.
        while True:
            edges = {k for k, c in self.getAllComponents().items()
                     if getattr(c, "shape", None) == "diagram-edge" and any(
                         getattr(c, side, {}).get("cell") in removed for side in ("source", "target"))}
            if edges <= removed:
                break
            removed.update(edges)
        for item in removed:
            self.getAllComponents().pop(item)
        self.topo = None
        self.setCompLabelDict()
        self.setChannelPinDict()
        return sorted(removed)

    def refreshTopology(self):
        self.topo = None
        result = self.adapter.topology(self.project)
        self.topo = result["topology"]
        return result

    def getEdgeTopoPinNum(self, cid):
        def visit(key, seen):
            if key in seen:
                return None
            seen.add(key)
            edge = self.getComponentByKey(key)
            for side in ("source", "target"):
                endpoint = getattr(edge, side, {})
                cell = endpoint.get("cell")
                if not cell:
                    continue
                if "port" in endpoint:
                    node = self.topo.get("components", {}).get("/" + cell, {}).get("pins", {}).get(endpoint["port"])
                else:
                    node = visit(cell, seen)
                if node not in (None, ""):
                    return node
            return None
        if self.topo is None:
            raise ValueError("Refresh topology first")
        return visit(cid, set())

    def deleteEdges(self):
        """Convert graphical connections to named pins using a fresh topology."""
        if self.topo is None:
            raise ValueError("Refresh topology first")
        nodes = {}
        for path, item in self.topo.get("components", {}).items():
            comp = self.getComponentByKey(path.lstrip("/"))
            for pin, node in item.get("pins", {}).items():
                if node not in (None, ""):
                    nodes.setdefault(str(node), []).append((comp, pin))
        edges = [k for k, c in self.getAllComponents().items() if getattr(c, "shape", None) == "diagram-edge"]
        affected = set()
        for key in edges:
            node = self.getEdgeTopoPinNum(key)
            if node is None or str(node) not in nodes:
                raise ValueError(f"Cannot resolve edge topology: {key}")
            affected.add(str(node))
        updates = []
        existing = {v for c in self.getAllComponents().values() for v in getattr(c, "pins", {}).values() if v}
        for node in sorted(affected):
            entries = nodes[node]
            names = {c.pins[p] for c, p in entries if c.pins[p]}
            if len(names) > 1:
                raise ValueError("Topology net has multiple aliases; conversion requires explicit resolution")
            name = next(iter(names), "AutoAddPin_" + node)
            if not names:
                while name in existing:
                    name += "_"
            existing.add(name)
            updates.extend((c, p, name) for c, p in entries)
        for comp, pin, name in updates:
            comp.pins[pin] = name
        for key in edges:
            self.getAllComponents().pop(key)
        self.topo = None
        return edges

    def saveProject(self, newID, name=None, desc=None, *, confirmed=False):
        validate_rid(newID)
        if newID in {self.original_rid, getattr(self.project, "rid", None)}:
            raise ValueError("Only a new RID may be saved")
        if confirmed is not True:
            raise ValueError("Explicit confirmation is required")
        return self.adapter.create_copy(self.project, newID, name, desc)
