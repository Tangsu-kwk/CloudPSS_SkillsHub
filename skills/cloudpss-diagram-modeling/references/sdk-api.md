# 独立 SDK 模块签名索引

按源码生成；列出顶层公开函数和类及其公开方法，包含辅助接口，不作为 MCP 工具数量。

## `auto_modeling.canvas_edit.add_diagram_canvas`

Allocate the official collision-checked key and open the new canvas.

```python
add_diagram_canvas(model, name)
```

## `auto_modeling.canvas_edit.update_diagram_canvas`

Omitted name leaves it unchanged; empty names work; explicit null fails.

```python
update_diagram_canvas(model, key, name=_OMITTED)
```

## `auto_modeling.canvas_edit.delete_diagram_canvas`

Delete a canvas and its own cells, following public action module 8415.

```python
delete_diagram_canvas(model, key)
```

## `auto_modeling.case_checks.prepare_case_checks`

Return cases problems, an isolated normalized document, and coverage.

```python
prepare_case_checks(model, *, functions=None, runtime=None)
```

## `auto_modeling.check_environment.CheckEnvironmentError`

Required check inputs unavailable; no task should be submitted.

## `auto_modeling.check_environment.load_job_policies`

```python
load_job_policies(*, requester=None)
```

## `auto_modeling.check_environment.load_check_environment`

Return detached definitions/functions/policies/runtime read via GraphQL.

```python
load_check_environment(model, *, requester=None)
```

## `auto_modeling.check_messages.check_message`

```python
check_message(group, problem)
```

## `auto_modeling.choice_checks.evaluate_choices`

```python
evaluate_choices(field, scope)
```

## `auto_modeling.component_args.get_diagram_components_args`

Return detached parameter dictionaries keyed by component ID.

```python
get_diagram_components_args(model, ids)
```

## `auto_modeling.component_args.get_diagram_components`

Project SDK cells to the public tool's nine fields as detached objects.

```python
get_diagram_components(model, ids)
```

## `auto_modeling.component_args.update_diagram_components_args`

Validate types against definitions, then update components in order.

```python
update_diagram_components_args(model, ids, args, *, definition_resolver=None)
```

## `auto_modeling.component_checks.prepare_component_checks`

```python
prepare_component_checks(model, *, definitions)
```

## `auto_modeling.component_model.ComponentModelError`

The request failed or its response did not satisfy the tool contract.

```python
ComponentModelError.__init__(self, message, graphql_errors=None)
```

## `auto_modeling.component_model.get_component_model`

Return the public tool's six fields, or None for an unavailable model.

```python
get_component_model(rid: str)
```

## `auto_modeling.component_model.compare_json`

Compare JSON strictly, ignoring object key order only.

```python
compare_json(expected: Any, actual: Any, path: str='$')
```

## `auto_modeling.component_reads.get_diagram_components_props`

Return properties keyed by ID; repeated IDs collapse, empty IDs return {}.

```python
get_diagram_components_props(model, ids)
```

## `auto_modeling.component_reads.get_diagram_components_pins`

Return stored pin values, not definition-level pin metadata or topology.

```python
get_diagram_components_pins(model, ids)
```

## `auto_modeling.component_subscriptions.official_subscriptions`

```python
official_subscriptions()
```

## `auto_modeling.component_subscriptions.load_component_subscriptions`

Discover groups and retain visibility for standard SimStudio mode.

```python
load_component_subscriptions(stored=None, *, requester=None)
```

## `auto_modeling.configs.list_configs`

Observed public list projection; does not expose args or pins.

```python
list_configs(model)
```

## `auto_modeling.configs.get_config`

Return a detached scheme; None uses model.context['currentConfig'].

```python
get_config(model, index=None)
```

## `auto_modeling.configs.add_config`

Append provided converted args, with no implicit defaults or selection.

```python
add_config(model, name, args)
```

## `auto_modeling.configs.update_config`

Merge whole argument values atomically; None leaves the name unchanged.

```python
update_config(model, index, args, name=None)
```

## `auto_modeling.configs.delete_config`

Splice a scheme, preserving currentConfig, materializing a new selection.

```python
delete_config(model, index)
```

## `auto_modeling.connection_checks.check_connection_groups`

Return worker connection problems from explicit prepared inputs.

```python
check_connection_groups(groups, *, components, pins, pin_info, port_group, dimensions)
```

## `auto_modeling.custom_graphic.GraphicRuntimeError`

Local graphic runtime unavailable or failed; nothing has been saved.

## `auto_modeling.custom_graphic.custom_graphic`

Build graphic and normalize only this detached document after success.

```python
custom_graphic(document)
```

## `auto_modeling.diagram_aux.model_from_document`

Load a detached browser document, preserving deleted (null) cell slots.

```python
model_from_document(document)
```

## `auto_modeling.diagram_aux.add_diagram_text`

```python
add_diagram_text(model, label, position, size, canvas, content, style)
```

## `auto_modeling.diagram_aux.get_diagram_texts`

```python
get_diagram_texts(model, ids)
```

## `auto_modeling.diagram_aux.update_diagram_texts`

```python
update_diagram_texts(model, ids, content=_OMITTED)
```

## `auto_modeling.diagram_aux.find_diagram_texts`

```python
find_diagram_texts(model, canvases=_OMITTED, label=_OMITTED)
```

## `auto_modeling.diagram_aux.add_diagram_link`

```python
add_diagram_link(model, label, position, size, canvas, href, shape, style)
```

## `auto_modeling.diagram_aux.get_diagram_links`

```python
get_diagram_links(model, ids)
```

## `auto_modeling.diagram_aux.update_diagram_links`

```python
update_diagram_links(model, ids, href=_OMITTED, shape=_OMITTED)
```

## `auto_modeling.diagram_aux.find_diagram_links`

```python
find_diagram_links(model, canvases=_OMITTED, label=_OMITTED)
```

## `auto_modeling.diagram_batch.get_diagram_nodes`

```python
get_diagram_nodes(model, ids)
```

## `auto_modeling.diagram_batch.update_diagram_nodes`

```python
update_diagram_nodes(model, ids, position=_OMITTED, size=_OMITTED)
```

## `auto_modeling.diagram_batch.find_diagram_nodes`

```python
find_diagram_nodes(model, canvases=_OMITTED, area=_OMITTED)
```

## `auto_modeling.diagram_batch.update_diagram_edges`

```python
update_diagram_edges(model, ids, source=_OMITTED, target=_OMITTED, vertices=_OMITTED, *, definition_resolver=None)
```

## `auto_modeling.diagram_batch.find_diagram_edges`

```python
find_diagram_edges(model, canvases=_OMITTED, terminals=_OMITTED)
```

## `auto_modeling.diagram_batch.update_diagram_components_props`

```python
update_diagram_components_props(model, ids, props)
```

## `auto_modeling.diagram_batch.update_diagram_components_pins`

```python
update_diagram_components_pins(model, ids, pins)
```

## `auto_modeling.diagram_batch.update_diagram_cells`

```python
update_diagram_cells(model, ids, label=_OMITTED, style=_OMITTED)
```

## `auto_modeling.diagram_batch.find_diagram_components`

```python
find_diagram_components(model, canvases=None, definitions=None, labels=None, args=None)
```

## `auto_modeling.diagram_batch.connected_diagram_components`

```python
connected_diagram_components(model, ids, min_depth=0, max_depth=1)
```

## `auto_modeling.diagram_connections.check_diagram_connections`

Return edge/connection problem records from an SDK Model or document.

```python
check_diagram_connections(model, *, definitions)
```

## `auto_modeling.diagram_contract.resolve_definition`

```python
resolve_definition(rid, resolver=None)
```

## `auto_modeling.diagram_contract.new_id`

```python
new_id(model, prefix, *, cell=False)
```

## `auto_modeling.diagram_contract.default_pins`

```python
default_pins(definitions, values)
```

## `auto_modeling.diagram_contract.fill_pins`

```python
fill_pins(original, updating, definitions)
```

## `auto_modeling.diagram_contract.terminal_input`

```python
terminal_input(value, name)
```

## `auto_modeling.diagram_contract.check_terminal`

```python
check_terminal(model, terminal, side, resolver=None)
```

## `auto_modeling.diagram_edit.DiagramCellNotFoundError`

Observed missing-cell business failure; core API uses Python exceptions.

```python
DiagramCellNotFoundError.__init__(self, key)
```

## `auto_modeling.diagram_edit.add_diagram_component`

Add a definition-validated component, including editor defaults.

```python
add_diagram_component(model, definition, position, canvas, args, pins, label=None, size=None, *, definition_resolver=None)
```

## `auto_modeling.diagram_edit.add_diagram_edge`

Add an edge with definition-level ports; pin labels are unchanged.

```python
add_diagram_edge(model, source, target, vertices=None, *, definition_resolver=None)
```

## `auto_modeling.diagram_edit.add_dynamic_diagram_edge`

Add an edge whose terminal may be generated from component arguments.

```python
add_dynamic_diagram_edge(model, source, target, vertices=None, *, definition_resolver=None)
```

## `auto_modeling.diagram_edit.get_diagram_edges`

Return detached edge projections; helper for structural verification.

```python
get_diagram_edges(model, ids)
```

## `auto_modeling.diagram_edit.get_diagram_cells`

Return the public cell projection; no geometry or inferred defaults.

```python
get_diagram_cells(model, ids)
```

## `auto_modeling.diagram_edit.delete_diagram_cells`

Remove requested cells and incident edges from a caller-owned model.

```python
delete_diagram_cells(model, ids)
```

## `auto_modeling.diagram_identity.remap_job_cell_references`

Return detached jobs with declared literal cell selector lists remapped.

```python
remap_job_cell_references(jobs, mapping)
```

## `auto_modeling.diagram_identity.rename_diagram_cell_ids`

Rename a subset of SDK cells and their declared references atomically.

```python
rename_diagram_cell_ids(model, mapping)
```

## `auto_modeling.diagram_reads.list_diagram_canvases`

```python
list_diagram_canvases(model)
```

## `auto_modeling.diagram_reads.list_diagram_variables`

```python
list_diagram_variables(model)
```

## `auto_modeling.diagram_reads.get_diagram_variable`

```python
get_diagram_variable(model, key)
```

## `auto_modeling.diagram_reads.update_diagram_variable`

```python
update_diagram_variable(model, key, value)
```

## `auto_modeling.diagram_reads.delete_diagram_variable`

```python
delete_diagram_variable(model, key)
```

## `auto_modeling.dynamic_pins.evaluated_instance_args`

Evaluate instance parameters against an isolated current scheme/variables.

```python
evaluated_instance_args(document, component, definition)
```

## `auto_modeling.dynamic_pins.pinlike_pins`

Monitoring terminals created by pinLike parameters with a non-empty label.

```python
pinlike_pins(definition, args)
```

## `auto_modeling.dynamic_pins.instance_pin_definitions`

Pure effective terminals for a flat definition and an actual SDK instance.

```python
instance_pin_definitions(model, component, definition)
```

## `auto_modeling.dynamic_pins.check_pin_definitions`

Return original pins or derived pins from already evaluated arguments.

```python
check_pin_definitions(definition, args)
```

## `auto_modeling.expression_diagnostics.expression_error`

```python
expression_error(exc)
```

## `auto_modeling.graphic_checks.check_graphic`

Return official-style ``graphic`` problem records.

```python
check_graphic(document)
```

## `auto_modeling.graphql_reads.GraphQLReadError`

## `auto_modeling.graphql_reads.get_metadata`

```python
get_metadata(rid, requester=None)
```

## `auto_modeling.graphql_reads.get_job_function`

Use the real GraphQL adapter; runtime MCP enrichment remains unverified.

```python
get_job_function(rid, requester=None)
```

## `auto_modeling.job_checks.check_job_system`

policies is an explicit snapshot; [] means a known empty policy cache.

```python
check_job_system(model, *, policies)
```

## `auto_modeling.job_function_list.list_job_functions`

Return MCP's three-field list, retaining server order across pages.

```python
list_job_functions(*, requester=None, page_size=100)
```

## `auto_modeling.job_functions.JobFunctionError`

```python
JobFunctionError.__init__(self, message, graphql_errors=None)
```

## `auto_modeling.job_functions.get_graphql_job_function`

Project six definition fields; not the full frontend runtime definition.

```python
get_graphql_job_function(rid, requester=None, *, runtime_definitions=None)
```

## `auto_modeling.job_functions.get_job_function`

Reproduce the browser's available-function registry JSON without MCP.

```python
get_job_function(rid, requester=None)
```

## `auto_modeling.job_functions.load_job_functions`

Load the full runtime JSON registry once for independent checks/runs.

```python
load_job_functions(*, requester=None)
```

## `auto_modeling.job_inputs.JobInputError`

Argument preparation failed; no caller-owned model has been modified.

## `auto_modeling.job_inputs.evaluate_args`

Return defined evaluated fields, preserving caller inputs.

```python
evaluate_args(args, parameters, *, owner=None, document=None)
```

## `auto_modeling.job_inputs.prepare_job_inputs`

Prepare arguments/policy/debug for one model job; does not submit.

```python
prepare_job_inputs(model, configIndex, jobIndex, *, definition)
```

## `auto_modeling.job_receiver.JobReceiverError`

Reception failed; the known task can be reattached, never resubmitted.

```python
JobReceiverError.__init__(self, job_id, reason)
```

## `auto_modeling.job_receiver.JobReceiver`

```python
JobReceiver.__init__(self, session, job_id, *, timeout, startup_timeout, requester)
JobReceiver.stop(self, timeout=2)
```

## `auto_modeling.job_results.JobAbortError`

The remote mutation may have committed; never retry automatically.

```python
JobAbortError.__init__(self, message, *, outcome='unknown', graphql_errors=None)
```

## `auto_modeling.job_results.request_abort_job`

Explicit remote abort, without creating/fetching a browser task record.

```python
request_abort_job(jobId, *, requester=None, timeout=3)
```

## `auto_modeling.job_results.fetch_job_info`

Server metadata, explicitly distinct from browser cached get_job_info.

```python
fetch_job_info(jobId, *, requester=None)
```

## `auto_modeling.job_results.fetch_job_record_info`

Read the standard browser-record metadata projection from the service.

```python
fetch_job_record_info(jobId, *, requester=None)
```

## `auto_modeling.job_results.import_completed_job`

Fetch a terminal server job and its complete raw stream into a session.

```python
import_completed_job(jobId, *, session, requester=None, job_fetcher=None, timeout=30)
```

## `auto_modeling.job_results.JobResults`

SDK task-record storage, with built-in independent result transport.

```python
JobResults.listen(self, jobId, *, timeout=86400, startup_timeout=30, requester=None)
JobResults.stop_receiver(self, jobId)
JobResults.close(self)
JobResults.register(self, record)
JobResults.import_job_info(self, jobId, *, requester=None, refresh=False)
JobResults.export_records(self)
JobResults.import_records(self, records)
JobResults.get_job_info(self, jobId)
JobResults.abort_job(self, jobId, *, requester=None)
JobResults.get_job_logs(self, jobId, block, *, timeout=30)
JobResults.get_job_plots(self, jobId, block, plot_layout=None, *, timeout=30)
```

## `auto_modeling.job_results.get_job_info`

Cached MCP semantics with session; current standard projection without.

```python
get_job_info(jobId, *, session=None, requester=None)
```

## `auto_modeling.job_results.abort_job`

```python
abort_job(jobId, *, session, requester=None)
```

## `auto_modeling.job_results.get_job_logs`

```python
get_job_logs(jobId, block, *, session=None, timeout=30)
```

## `auto_modeling.job_results.get_job_plots`

```python
get_job_plots(jobId, block, plot_layout=None, *, session=None, timeout=30)
```

## `auto_modeling.job_runner.JobPreflightError`

```python
JobPreflightError.__init__(self, problems)
```

## `auto_modeling.job_runner.prepare_run_job`

Read independent check inputs, check, and build a detached task plan.

```python
prepare_run_job(model, configIndex, jobIndex, *, requester=None)
```

## `auto_modeling.job_runner.run_job`

Check, submit memory revision/task, start SDK receiver; return task ID.

```python
run_job(model, configIndex, jobIndex, *, session, requester=None)
```

## `auto_modeling.job_schemes.add_job`

Append converted supplied args and return its index; selection stays.

```python
add_job(model, rid, name, args, *, definition_resolver=None)
```

## `auto_modeling.job_schemes.update_job`

Resolve the function and validate the full update before writing.

```python
update_job(model, index, args, name=_OMITTED, *, definition_resolver=None)
```

## `auto_modeling.job_schemes.delete_job`

Splice any calculation scheme while preserving the current index.

```python
delete_job(model, index, *, definition_resolver=None)
```

## `auto_modeling.job_submission.JobSubmissionError`

Expose recovery evidence without retrying or claiming remote rollback.

```python
JobSubmissionError.__init__(self, message, *, stage, outcome, revision_hash=None, job_id=None, graphql_errors=None)
```

## `auto_modeling.job_submission.prepare_job_submission`

Return a detached two-mutation plan, without checking or submitting.

```python
prepare_job_submission(model, configIndex, jobIndex, *, definition, author, revision_message)
```

## `auto_modeling.job_submission.job_input_with_revision`

Bind the server-returned revision hash; never use a local fake hash.

```python
job_input_with_revision(plan, revision_hash)
```

## `auto_modeling.job_submission.submit_job_plan`

Create revision and job explicitly; return only the job ID as MCP does.

```python
submit_job_plan(plan, *, requester=None, session=None, start_receiver=True)
```

## `auto_modeling.log_results.log_html`

Escape text, preserve indentation and link diagram-cell paths.

```python
log_html(content, html=False)
```

## `auto_modeling.log_results.log_messages`

Merge log groups and return detached HTML messages, in key order.

```python
log_messages(messages)
```

## `auto_modeling.parameter_checks.check_parameter_constraints`

Return untranslated worker problem records in constraint order.

```python
check_parameter_constraints(value, field, *, scope, data, message='component arg:unsatisfied constraint')
```

## `auto_modeling.parameter_definition_checks.check_parameter_definitions`

Return official-style `parameters` group problem records.

```python
check_parameter_definitions(document)
```

## `auto_modeling.parameter_defs.add_parameter_group`

```python
add_parameter_group(model, name, description=None, position=None)
```

## `auto_modeling.parameter_defs.update_parameter_group`

```python
update_parameter_group(model, group, name=None, description=None, condition=None)
```

## `auto_modeling.parameter_defs.delete_parameter_group`

```python
delete_parameter_group(model, group)
```

## `auto_modeling.parameter_defs.add_parameter`

```python
add_parameter(model, group, key, position=None, type=None, options=None)
```

## `auto_modeling.parameter_defs.update_parameter`

Merge definition fields atomically; value=None restores its type default.

```python
update_parameter(model, param, options)
```

## `auto_modeling.parameter_defs.delete_parameter`

Delete the definition and return {"0": group index, "1": item index}.

```python
delete_parameter(model, param)
```

## `auto_modeling.parameter_defs.get_parameter_options`

Return detached type metadata; no Model or remote connection is needed.

```python
get_parameter_options(type)
```

## `auto_modeling.pin_definition_checks.check_pin_definitions`

Return official-style ``pinDefinitions`` problems.

```python
check_pin_definitions(document)
```

## `auto_modeling.plot_results.plot_figure`

Pure figure construction, independently testable against official JS.

```python
plot_figure(messages)
```

## `auto_modeling.plot_results.plot_response`

```python
plot_response(messages, plot_layout=None, *, renderer=None)
```

## `auto_modeling.project_check.IncompleteCheckError`

The MCP-shaped result cannot represent missing checker inputs.

## `auto_modeling.project_check.check_project_stages`

Run parameter then topology stages; no implicit network/save/job.

```python
check_project_stages(model, *, definitions, functions=None, policies=None, runtime=None)
```

## `auto_modeling.project_check.run_check`

Return rich local diagnostics with MCP-like group/level filtering.

```python
run_check(model, *, definitions, functions=None, policies=None, runtime=None, groups=None, levels=None)
```

## `auto_modeling.project_check.run_check_mcp`

Return the business payload of the CloudPSS ``run_check`` tool.

```python
run_check_mcp(model, *, definitions, functions=None, policies=None, runtime=None, groups=None, levels=None)
```

## `auto_modeling.project_edit.update_metadata`

Omission preserves values; empty strings work; null fails before writes.

```python
update_metadata(model, name=_OMITTED, description=_OMITTED, documentation=_OMITTED)
```

## `auto_modeling.project_hooks.clean_diagram`

```python
clean_diagram(document)
```

## `auto_modeling.project_hooks.open_document`

Default, migrate and clean a detached model before SDK construction.

```python
open_document(document)
```

## `auto_modeling.project_hooks.default_graphic`

Exact default rectangular builder from module 84555, including ports.

```python
default_graphic(document)
```

## `auto_modeling.project_hooks.save_document`

Return detached wire JSON; default/local x6 generation or explicit builder.

```python
save_document(document, *, author, graphic_builder=None)
```

## `auto_modeling.project_migration.ProjectMigrationError`

Migration failed without changing caller data or session state.

## `auto_modeling.project_migration.migrate_project_document`

Return normalized/migrated detached document for known versions 1..5.

```python
migrate_project_document(document)
```

## `auto_modeling.project_persistence.project_exists`

Only the exact resource-lookup 406 observed on this deployment means absent.

```python
project_exists(rid, *, requester=None)
```

## `auto_modeling.project_persistence.ProjectSaveError`

A failed save may leave a revision, or have an unknown mutation outcome.

```python
ProjectSaveError.__init__(self, message, *, revision_hash=None, outcome_unknown=False)
```

## `auto_modeling.project_persistence.save_project`

Save current in-memory contents; return RID and commit identity on success.

```python
save_project(model, rid=None, *, requester=None, graphic_builder=None)
```

## `auto_modeling.project_reads.get_metadata`

Project metadata projection; does not mutate the SDK model.

```python
get_metadata(model)
```

## `auto_modeling.project_reads.list_jobs`

```python
list_jobs(model)
```

## `auto_modeling.project_reads.get_job`

```python
get_job(model, index=None)
```

## `auto_modeling.project_reads.list_parameter_groups`

Historical schema projection; populated live group still needs comparison.

```python
list_parameter_groups(model)
```

## `auto_modeling.project_reads.get_parameter_group`

```python
get_parameter_group(model, group)
```

## `auto_modeling.project_reads.list_parameters`

```python
list_parameters(model, group)
```

## `auto_modeling.project_reads.get_parameter`

```python
get_parameter(model, param)
```

## `auto_modeling.project_session.ProjectError`

```python
ProjectError.__init__(self, message, graphql_errors=None)
```

## `auto_modeling.project_session.build_project_model`

Return a fresh SDK Model: empty document or detached template copy.

```python
build_project_model(rid=None, *, requester=None)
```

## `auto_modeling.project_session.new_project`

Construct a model with observed Chinese standard SimStudio open defaults.

```python
new_project(rid=_OMITTED, *, requester=None)
```

## `auto_modeling.project_session.open_project`

Fetch into a detached SDK Model, retaining resource identity/metadata.

```python
open_project(rid, *, requester=None)
```

## `auto_modeling.project_session.ProjectSession`

Explicit Python session; construction failure preserves the old model.

```python
ProjectSession.run_job(self, configIndex, jobIndex, *, requester=None)
ProjectSession.close(self)
ProjectSession.new_project(self, rid=_OMITTED, *, requester=None)
ProjectSession.open_project(self, rid, *, requester=None)
ProjectSession.save_project(self, rid=None, *, requester=None, graphic_builder=None)
```

## `auto_modeling.remote_reads.RemoteReadError`

```python
RemoteReadError.__init__(self, message, graphql_errors=None)
```

## `auto_modeling.remote_reads.get_account`

```python
get_account(*, requester=None)
```

## `auto_modeling.remote_reads.list_accounts`

Self, owned groups, moderated groups, member groups in source order.

```python
list_accounts(*, requester=None)
```

## `auto_modeling.remote_reads.list_projects`

Official personal/shared/public/template filters and transparent cursor.

```python
list_projects(filter, *, limit=25, cursor=None, requester=None)
```

## `auto_modeling.remote_reads.find_component_models`

Weighted official multi-keyword search over a detached model catalogue.

```python
find_component_models(keywords, *, subscribedOnly=False, official=None, model=None, requester=None, catalogue=None)
```

## `auto_modeling.result_records.receiver_records`

Assign stable identities, retaining an unchanged replay prefix.

```python
receiver_records(messages, received_at=None, *, previous_raw=None, previous_records=None)
```

## `auto_modeling.result_stream.ResultStreamError`

Transport/decode failure; no partial result is reported as success.

## `auto_modeling.result_stream.ResultStreamUnavailable`

The service does not expose the requested output stream.

## `auto_modeling.result_stream.ResultStreamStopped`

SDK reception was stopped locally; the cloud task was not aborted.

## `auto_modeling.result_stream.remaining`

```python
remaining(deadline)
```

## `auto_modeling.result_stream.stream_url`

```python
stream_url(stream_id)
```

## `auto_modeling.result_stream.decode_frame`

Decode outer UBJSON plus *all* concatenated inner UBJSON messages.

```python
decode_frame(payload)
```

## `auto_modeling.result_stream.MessageTemplates`

Template declarations/invocations from official modules 42308/25563.

```python
MessageTemplates.__init__(self)
MessageTemplates.accept(self, value)
```

## `auto_modeling.result_stream.StreamSnapshot`

## `auto_modeling.result_stream.read_stream`

Collect a complete stream or a nonblocking snapshot after 700ms quiet.

```python
read_stream(stream_id, *, block, deadline, kind=None, keys=None, on_open=None, on_message=None, stop_event=None, connect_timeout=None)
```

## `auto_modeling.result_stream.read_job_results`

Get metadata and output directly from CloudPSS under one deadline.

```python
read_job_results(job_id, *, block, deadline, kind=None, keys=None)
```

## `auto_modeling.runtime_checks.parse_tres`

```python
parse_tres(value)
```

## `auto_modeling.runtime_checks.format_tres`

```python
format_tres(value)
```

## `auto_modeling.runtime_checks.validate_runtime`

```python
validate_runtime(runtime)
```

## `auto_modeling.runtime_checks.resolve_runtime_field`

Replace only recognized serialized callbacks; report other missing code.

```python
resolve_runtime_field(field, *, runtime, rid, args, value)
```

## `auto_modeling.scenarios.ScenarioSet`

Build independent SDK models from one immutable baseline snapshot.

```python
ScenarioSet.__init__(self, model, *, definition_resolver=None)
ScenarioSet.build(self, patches)
ScenarioSet.build_batch(self, specifications)
```

## `auto_modeling.scheme_args.default_args`

Detached JSON-visible defaultArgs; preserve expressions unevaluated.

```python
default_args(parameters, args)
```

## `auto_modeling.scheme_args.fill_args`

Validate supplied keys/types, convert values, preserve unspecified keys.

```python
fill_args(original, updating, parameters)
```

## `auto_modeling.scheme_indices.numeric_index`

```python
numeric_index(index)
```

## `auto_modeling.scheme_indices.read_index`

```python
read_index(items, index, kind)
```

## `auto_modeling.scheme_indices.write_index`

```python
write_index(items, index, value)
```

## `auto_modeling.storage.StorageError`

```python
StorageError.__init__(self, message, status_code=None)
```

## `auto_modeling.storage.put_storage`

Upload URL/data-URL bytes and return a relative storage link.

```python
put_storage(payload, filename=None, *, requester=None, token=None, base_url=None)
```

## `auto_modeling.storage.check_storage`

Return False only for HTTP 404; auth/network/server failures raise.

```python
check_storage(url, *, requester=None, token=None, base_url=None)
```
