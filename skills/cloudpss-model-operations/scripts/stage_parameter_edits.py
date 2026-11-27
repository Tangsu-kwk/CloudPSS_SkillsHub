"""Stage instance parameter edits on a disposable model and return structured failures."""


def stage_parameter_edits(model, patches, *, definition_resolver):
    """Return (candidate, receipt); the caller adopts the candidate only on success."""
    from auto_modeling.component_args import update_diagram_components_args
    from auto_modeling.diagram_aux import model_from_document
    from auto_modeling.diagram_edit import DiagramCellNotFoundError

    if not isinstance(patches, (list, tuple)):
        return None, {
            'status': 'rejected', 'code': 'PARAMETER_EDIT_REJECTED',
            'patch_index': None, 'error_type': 'TypeError',
            'message': 'patches must be a list of mapping objects',
            'hint': '提交补丁列表后重试。',
        }
    candidate = model_from_document(model.toJSON())
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            return None, {
                'status': 'rejected', 'code': 'PARAMETER_EDIT_REJECTED',
                'patch_index': index, 'error_type': 'TypeError',
                'message': 'patch must be a mapping with cell/field/value keys',
                'hint': '核对补丁结构后，重新提交整组修改。',
            }
        missing = [k for k in ('cell', 'field', 'value') if k not in patch]
        if missing:
            return None, {
                'status': 'rejected', 'code': 'PARAMETER_EDIT_REJECTED',
                'patch_index': index, 'error_type': 'KeyError',
                'message': f"patch missing required keys: {', '.join(missing)}",
                'hint': '补全 cell/field/value 后，重新提交整组修改。',
            }
        cell, field = patch['cell'], patch['field']
        try:
            update_diagram_components_args(candidate, [cell], {field: patch['value']},
                                           definition_resolver=definition_resolver)
        except (DiagramCellNotFoundError, TypeError, ValueError) as exc:
            return None, {
                'status': 'rejected', 'code': 'PARAMETER_EDIT_REJECTED',
                'patch_index': index, 'cell': cell, 'field': field,
                'error_type': type(exc).__name__, 'message': str(exc),
                'hint': '核对实例 ID、定义中的字段名及值类型，再提交整组修改。',
            }
    return candidate, {'status': 'staged', 'patch_count': len(patches)}
