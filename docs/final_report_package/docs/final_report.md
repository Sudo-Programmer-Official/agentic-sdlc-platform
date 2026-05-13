# final report: agentic sdlc platform

## 1. introduction
This project delivers an autonomous, governed software delivery platform with persistent engineering memory and bounded execution. The platform combines requirement-aware planning, multi-agent execution, runtime recovery, and safety gates to produce code and validation outputs while preserving traceability across the delivery lifecycle.

## 2. problem statement
Traditional CI/CD executes predefined pipelines but does not autonomously reason about failures, prioritize context, or maintain requirement lineage through dynamic repair loops. Generic AI coding assistants generate code but commonly lack bounded execution controls, explicit governance gates, and durable engineering memory linked to runs, tasks, and artifacts.

The target problem is to build a system that can:
- translate requirements into governed execution plans,
- perform autonomous implementation and validation,
- recover from runtime failures with bounded retries and policy,
- persist lineage across requirements, runs, recoveries, and outputs,
- surface operational observability for human supervision.

## 3. related work
This platform is positioned between:
- CI/CD orchestration systems (deterministic automation, limited adaptive reasoning),
- coding copilots/assistants (adaptive generation, weaker runtime governance), and
- experimental multi-agent engineering runtimes (higher autonomy, often insufficient control-plane safety).

The proposed system integrates these into one governed execution plane.

## 4. proposed architecture
Core architecture layers:
- frontend mission control and requirements governance views (Vue 3 + Element Plus),
- API/control plane (FastAPI) for lifecycle, memory, governance, and run services,
- scheduler + orchestrator + worker runtime services for DAG execution,
- agent executors for planning/coding/testing/review,
- recovery policy + recovery memory services for autonomous repair,
- persistent storage for runs, work items, artifacts, events, requirement memory, and recovery attempts.

The orchestration path starts from requirement/work intake, bootstraps a DAG, claims executable work items with lease control, performs stage execution, records events/artifacts, applies recovery policy when failures occur, and publishes delivery outputs when governance and validation conditions are satisfied.

## 5. multi-agent execution model
Execution is modeled as a run-level DAG containing typed work items (e.g., `WRITE_TESTS`, `CODE_BACKEND`/`CODE_FRONTEND`, `RUN_TESTS`, `REVIEW_DIFF`, `FIX_TEST_FAILURE`).

Key properties:
- dependency-aware scheduling and capability matching,
- per-work-item lease/heartbeat protection,
- agent-attributed event logging,
- checkpoint capture and resumability,
- run summary/timeline synthesis for operator replay.

Governed mutation behavior is enforced through bounded writable scope, patch verification, and project-contract-aware prechecks before code mutation actions are accepted.

## 6. runtime governance and recovery
Governance is implemented by combining policy, contract, and recovery controls:
- execution contract and budget tracking,
- patch guard and allowed-file derivation,
- validation-aware stage transitions,
- deterministic event emissions for auditability,
- bounded recovery attempts by work-item, failure-type, run, runtime duration, and cost envelope.

Recovery pipeline includes:
- failure classification,
- strategy selection,
- recovery attempt recording,
- optional recovery-memory override when historical success confidence is high,
- escalation/stop when safety or budget limits are reached.

## 7. context ranking and memory
The context system builds bounded context packs from graph context, requirement-linked artifacts, and external references. Ranking includes:
- relevance score,
- trust score,
- freshness score,
- historical success weight.

Selection is top-k bounded and includes a decision trace with context efficiency ratio (`selected/loaded`).

Engineering memory is persisted across:
- requirement memories and relationships,
- run checkpoints/events/timelines,
- recovery attempts and learned recovery profiles,
- artifacts and summaries for replay/explanation.

## 8. experimental evaluation
Evaluation in this project is runtime-observability-centric and safety-centric. Primary metrics include patch success rate, recovery success rate, time-to-green, validation pass rate, retries, context efficiency, safe-change success rate, and budget utilization.

The platform also computes governance KPIs including context-pack usage and deterministic topology replay indicators.

## 9. limitations
Current limitations include:
- runtime metrics are highly deployment-data dependent and may require longer production windows for stable statistical significance,
- autonomous behavior still requires strong repository contracts and high-quality tests for best outcomes,
- screenshot evidence of live UI states depends on local runtime capture process.

## 10. future work
- adaptive strategy routing by historical module-level success,
- deeper semantic context compression and retrieval quality auditing,
- richer human override policies with explainable intervention previews,
- deployment-aware rollback simulation and risk scoring expansion.

## 11. conclusion
The implemented platform demonstrates that autonomous software delivery can be executed with bounded control, persistent memory, and explicit governance. It is not only a code generator; it is a runtime-governed engineering system that links requirements to execution and recovery outcomes through durable lineage.

## diagram and table index
- diagrams: `../diagrams/*.svg`
- tables: `../tables/*.md`
- appendices: `../appendix/*.md`
