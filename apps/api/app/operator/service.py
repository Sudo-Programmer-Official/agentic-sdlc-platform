from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.operator.intents import OperatorIntent, classify_intent, extract_uuid
from app.operator.response_formatter import build_response, compose_answer
from app.operator.schemas import OperatorAction, OperatorReference, OperatorRequest, OperatorResponse
from app.operator import tools


def _route(project_id: uuid.UUID, suffix: str = "") -> str:
    return f"/projects/{project_id}{suffix}"


def _run_ref(project_id: uuid.UUID, run_id: str) -> OperatorReference:
    return OperatorReference(type="run", label=f"Run {run_id[:8]}", id=run_id, path=_route(project_id, "/run"))


def _artifact_ref(project_id: uuid.UUID, artifact_id: str) -> OperatorReference:
    return OperatorReference(type="artifact", label=f"Artifact {artifact_id[:8]}", id=artifact_id, path=_route(project_id, "/run"))


def _file_ref(project_id: uuid.UUID, file_path: str) -> OperatorReference:
    return OperatorReference(
        type="file",
        label=file_path,
        id=file_path,
        path=_route(project_id, "/map"),
        meta={"file_path": file_path},
    )


def _action(label: str, action_type: str, *, target_id: str | None = None, path: str | None = None, prompt: str | None = None) -> OperatorAction:
    return OperatorAction(label=label, type=action_type, target_id=target_id, path=path, prompt=prompt)


async def handle_operator_request(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    request: OperatorRequest,
) -> OperatorResponse:
    intent = classify_intent(request)
    project_id = request.project_id

    if intent == OperatorIntent.PROJECT_STATUS:
        result = await tools.get_current_project(session, tenant_id=tenant_id, project_id=project_id)
        facts = [
            f"Project {result['name']} is in {result['status']}.",
            (
                f"Repository is {result['repository']['repo_full_name']} on {result['repository']['default_branch']}."
                if result.get("repository")
                else "No repository is connected."
            ),
            f"Work intake items: {result['work_intake_count']}.",
            f"Recent runs: {result['recent_run_count']}.",
        ]
        if result.get("latest_run"):
            facts.append(
                f"Latest run {result['latest_run']['id'][:8]} is {result['latest_run']['status'].lower()} via {result['latest_run']['executor']}."
            )
        answer = compose_answer(facts=facts, suggestion="Open Mission Control or ask for project health next.")
        return build_response(
            answer=answer,
            intent=intent.value,
            references=[
                OperatorReference(type="project", label=result["name"], id=result["project_id"], path=_route(project_id)),
                OperatorReference(type="page", label="Mission Control", path=_route(project_id, "/run")),
            ],
            actions=[
                _action("Open Project", "open_project", target_id=result["project_id"], path=_route(project_id)),
                _action("Show Project Health", "prompt_project_health", prompt="Show project health"),
                _action("Open Mission Control", "open_run_board", path=_route(project_id, "/run")),
            ],
            grounding_tools=["get_current_project"],
            facts=facts,
            tool_results={"get_current_project": result},
        )

    if intent == OperatorIntent.CONTENT_UPDATE:
        facts = [
            "This request appears to be content-only.",
            "Content updates can be routed without DAG generation or PR creation.",
        ]
        return build_response(
            answer=compose_answer(
                facts=facts,
                suggestion="Use the Content Editor panel or call change routing with a content key/value.",
            ),
            intent=intent.value,
            actions=[
                _action("Open Project Overview", "open_project", path=_route(project_id)),
                _action("Open Content Editor", "open_project", path=_route(project_id)),
            ],
            facts=facts,
            grounding_tools=["deterministic_content_classifier"],
            tool_results={"classification": "CONTENT"},
        )

    if intent == OperatorIntent.STRUCTURAL_CHANGE:
        facts = [
            "This request appears structural.",
            "Structural updates should route through governed runtime generation and PR flow.",
        ]
        return build_response(
            answer=compose_answer(
                facts=facts,
                suggestion="Launch a structural run from Project Overview or Mission Control.",
            ),
            intent=intent.value,
            actions=[
                _action("Open Mission Control", "open_run_board", path=_route(project_id, "/run")),
            ],
            facts=facts,
            grounding_tools=["deterministic_content_classifier"],
            tool_results={"classification": "STRUCTURAL"},
        )

    if intent == OperatorIntent.PROJECT_HEALTH:
        result = await tools.get_project_health_summary(session, project_id=project_id)
        issues = []
        if result.get("orphan_tasks"):
            issues.append(f"orphan tasks: {result['counts']['orphan_tasks']}")
        if result.get("docs_without_tasks"):
            issues.append(f"docs without tasks: {result['counts']['docs_without_tasks']}")
        if result.get("tasks_without_trace"):
            issues.append(f"tasks without trace: {result['counts']['tasks_without_trace']}")
        if result.get("deprecated_without_supersede"):
            issues.append(
                f"deprecated without supersede: {result['counts']['deprecated_without_supersede']}"
            )
        if result.get("graph_cycles_detected"):
            issues.append(f"cycles detected: {result['counts']['cycles']}")
        facts = [
            "Project health was evaluated from graph and task consistency checks.",
            f"Longest chain length: {result['counts']['longest_chain']}.",
        ]
        if issues:
            facts.append("Issues found: " + ", ".join(issues) + ".")
            suggestion = "Open Project Overview or Requirements to resolve the flagged graph issues."
        else:
            facts.append("No major structural issues were found.")
            suggestion = "Project health is stable. You can move to Mission Control for execution details."
        return build_response(
            answer=compose_answer(facts=facts, suggestion=suggestion),
            intent=intent.value,
            references=[
                OperatorReference(type="page", label="Project Overview", path=_route(project_id)),
                OperatorReference(type="page", label="Requirements", path=_route(project_id, "/requirements")),
            ],
            actions=[
                _action("Open Project Overview", "open_project", path=_route(project_id)),
                _action("Open Requirements", "open_requirements", path=_route(project_id, "/requirements")),
            ],
            grounding_tools=["get_project_health"],
            facts=facts,
            tool_results={"get_project_health": result},
        )

    if intent == OperatorIntent.RUN_DEBUG:
        explicit_run_id = request.context.run_id or extract_uuid(request.message)
        failure_mode = "fail" in request.message.lower() or "failure" in request.message.lower()
        if explicit_run_id:
            result = await tools.get_run_by_id(
                session, tenant_id=tenant_id, project_id=project_id, run_id=explicit_run_id
            )
            used_tool = "get_run_by_id"
        else:
            result = await tools.get_latest_run(session, tenant_id=tenant_id, project_id=project_id)
            used_tool = "get_latest_run"
        facts = [
            f"Run {result['run_id'][:8]} is {result['status'].lower()} via {result['executor']}.",
            f"Workspace is {result['workspace_status'].lower()} on branch {result['branch_name'] or '—'}.",
            f"Recovery count: {result['recovery_count']}.",
        ]
        if result.get("primary_error"):
            facts.append(f"Primary error: {result['primary_error']}.")
        if result.get("changed_files"):
            facts.append(f"Changed files: {', '.join(result['changed_files'][:5])}.")
        suggestion = (
            "Open the run timeline or compare it against the previous run."
            if failure_mode or result.get("primary_error")
            else "Open the run timeline or ask for workspace status."
        )
        return build_response(
            answer=compose_answer(facts=facts, suggestion=suggestion),
            intent=intent.value,
            references=[
                _run_ref(project_id, result["run_id"]),
                OperatorReference(type="page", label="Run Replay", path=_route(project_id, f"/runs/{result['run_id']}/debug")),
            ],
            actions=[
                _action("Open Run", "open_run", target_id=result["run_id"], path=_route(project_id, "/run")),
                _action("View Replay", "open_run_replay", target_id=result["run_id"], path=_route(project_id, f"/runs/{result['run_id']}/debug")),
                _action("View Workspace", "prompt_workspace", prompt=f"Show workspace status for run {result['run_id']}"),
            ],
            grounding_tools=[used_tool],
            facts=facts,
            tool_results={used_tool: result},
        )

    if intent == OperatorIntent.ARTIFACT_EXPLAIN:
        artifact_id = request.context.artifact_id or extract_uuid(request.message)
        result = await tools.get_artifact_explanation(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            artifact_id=artifact_id,
        )
        facts = [
            f"Artifact {result['artifact_id'][:8]} is a {result['type']}.",
            f"Changed files: {result['file_count']} with +{result['additions']} / -{result['deletions']}.",
            f"Approval status: {result['approval_status']}.",
        ]
        if result.get("changed_files"):
            facts.append(f"Files: {', '.join(result['changed_files'][:5])}.")
        return build_response(
            answer=compose_answer(facts=facts, suggestion="Open the artifact or ask for the latest run if you want the execution context."),
            intent=intent.value,
            references=[
                _artifact_ref(project_id, result["artifact_id"]),
                OperatorReference(type="page", label="Automation Map", path=_route(project_id, "/map")),
            ],
            actions=[
                _action("Open Artifact", "open_artifact", target_id=result["artifact_id"], path=_route(project_id, "/run")),
                _action("Open Automation Map", "open_map", path=_route(project_id, "/map")),
                _action("Open Approvals", "open_approvals", path=_route(project_id, "/approvals")),
            ],
            grounding_tools=["explain_artifact"],
            facts=facts,
            tool_results={"explain_artifact": result},
        )

    if intent == OperatorIntent.RUN_COMPARISON:
        result = await tools.compare_runs(session, tenant_id=tenant_id, project_id=project_id)
        faster_text = (
            f"Run {result['faster_run_id'][:8]} was faster by {result['faster_by_seconds']:.1f}s."
            if result.get("faster_run_id") and result.get("faster_by_seconds") is not None
            else "Neither run has a clear speed advantage."
        )
        facts = [
            f"Run {result['run_a_id'][:8]} is {result['run_a_status'].lower()} with {result['run_a_recovery_count']} recoveries.",
            f"Run {result['run_b_id'][:8]} is {result['run_b_status'].lower()} with {result['run_b_recovery_count']} recoveries.",
            faster_text,
        ]
        if result.get("pull_request_run_id"):
            facts.append(f"Run {result['pull_request_run_id'][:8]} produced the PR-ready result.")
        return build_response(
            answer=compose_answer(facts=facts, suggestion="Use Compare Runs in Mission Control for a side-by-side review."),
            intent=intent.value,
            references=[
                _run_ref(project_id, result["run_a_id"]),
                _run_ref(project_id, result["run_b_id"]),
            ],
            actions=[
                _action("Open Run A", "open_run", target_id=result["run_a_id"], path=_route(project_id, "/run")),
                _action("Open Run B", "open_run", target_id=result["run_b_id"], path=_route(project_id, "/run")),
                _action("Compare in Mission Control", "open_run_compare", path=_route(project_id, "/run")),
            ],
            grounding_tools=["compare_runs"],
            facts=facts,
            tool_results={"compare_runs": result},
        )

    if intent == OperatorIntent.WORKSPACE_STATUS:
        run_id = request.context.run_id or extract_uuid(request.message)
        result = await tools.get_workspace_status(
            session, tenant_id=tenant_id, project_id=project_id, run_id=run_id
        )
        facts = [
            f"Workspace for run {result['run_id'][:8]} is {result['workspace_status'].lower()}.",
            f"Branch: {result['branch_name'] or '—'}.",
            f"Repo path: {result['repo_path'] or 'unavailable'}.",
        ]
        if result.get("workspace_error"):
            facts.append(f"Workspace error: {result['workspace_error']}.")
        return build_response(
            answer=compose_answer(facts=facts, suggestion="Open the run if you want the full execution view."),
            intent=intent.value,
            references=[_run_ref(project_id, result["run_id"])],
            actions=[
                _action("Open Run", "open_run", target_id=result["run_id"], path=_route(project_id, "/run")),
                _action("Open Replay", "open_run_replay", target_id=result["run_id"], path=_route(project_id, f"/runs/{result['run_id']}/debug")),
            ],
            grounding_tools=["get_workspace_status"],
            facts=facts,
            tool_results={"get_workspace_status": result},
        )

    if intent == OperatorIntent.REPO_CONTEXT:
        lowered = request.message.lower()
        if "repo map" in lowered or "repository map" in lowered or "codebase" in lowered:
            try:
                repo_map = await tools.get_repo_map(session, tenant_id=tenant_id, project_id=project_id)
            except ValueError as exc:
                return build_response(
                    answer=str(exc),
                    intent=intent.value,
                    status="blocked",
                    actions=[
                        _action("Open Mission Control", "open_run_board", path=_route(project_id, "/run")),
                        _action("Show workspace status", "prompt", prompt="Show workspace status"),
                    ],
                )
            sample_paths = [entry["path"] for entry in repo_map.get("files", [])[:4]]
            facts = [
                f"Repo map indexed {repo_map['total_files']} files from {repo_map['source_type']}.",
                f"Branch: {repo_map.get('branch_name') or '—'}.",
            ]
            if repo_map.get("top_features"):
                facts.append(f"Top features: {', '.join(repo_map['top_features'][:5])}.")
            if sample_paths:
                facts.append(f"Representative files: {', '.join(sample_paths)}.")
            return build_response(
                answer=compose_answer(
                    facts=facts,
                    suggestion="Ask me to find a specific component, page, service, or button next.",
                ),
                intent=intent.value,
                references=[
                    OperatorReference(type="page", label="Automation Map", path=_route(project_id, "/map")),
                    *[_file_ref(project_id, path) for path in sample_paths[:3]],
                ],
                actions=[
                    _action("Open Automation Map", "open_map", path=_route(project_id, "/map")),
                    _action("Find login component", "prompt", prompt="Find the login component"),
                    _action("Show workspace status", "prompt", prompt="Show workspace status"),
                ],
                grounding_tools=["get_repo_map"],
                facts=facts,
                tool_results={"get_repo_map": repo_map},
            )

        try:
            result = await tools.search_repo_map(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                query=request.message,
            )
        except ValueError as exc:
            return build_response(
                answer=str(exc),
                intent=intent.value,
                status="blocked",
                actions=[
                    _action("Open Mission Control", "open_run_board", path=_route(project_id, "/run")),
                    _action("Show workspace status", "prompt", prompt="Show workspace status"),
                ],
            )
        matches = result.get("matches") or []
        facts = [
            f"Repo search ran against {result['total_files']} indexed files from {result['source_type']}.",
        ]
        if matches:
            top = matches[0]
            facts.append(f"Best match: {top['path']} ({top['kind']}).")
            if top.get("summary"):
                facts.append(top["summary"])
            if len(matches) > 1:
                facts.append(
                    "Other candidates: " + ", ".join(match["path"] for match in matches[1:4]) + "."
                )
            suggestion = "Use the top files as the initial targeted read set for a governed repo-change run."
        else:
            facts.append("No strong file matches were found for that query.")
            suggestion = "Try a more specific feature, component, route, or service name."
        return build_response(
            answer=compose_answer(facts=facts, suggestion=suggestion),
            intent=intent.value,
            references=[_file_ref(project_id, match["path"]) for match in matches[:4]],
            actions=[
                _action("Open Automation Map", "open_map", path=_route(project_id, "/map")),
                _action("Show repo map", "prompt", prompt="Show repo map"),
                _action("Show workspace status", "prompt", prompt="Show workspace status"),
            ],
            grounding_tools=["search_repo_map"],
            facts=facts,
            tool_results={"search_repo_map": result},
        )

    return build_response(
        answer="I can help with project status, run debugging, artifact explanation, run comparison, workspace status, project health, and repo map search right now.",
        intent=OperatorIntent.UNKNOWN.value,
        status="unsupported",
        actions=[
            _action("Why did the latest run fail?", "prompt", prompt="Why did the latest run fail?"),
            _action("Explain the latest patch", "prompt", prompt="Explain the latest patch"),
            _action("Show project health", "prompt", prompt="Show project health"),
            _action("Show repo map", "prompt", prompt="Show repo map"),
        ],
    )
