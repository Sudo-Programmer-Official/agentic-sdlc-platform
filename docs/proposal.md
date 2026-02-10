Graduate Capstone Project Proposal

Advanced Software Engineering (COSC 6370)
Texas A&M University – Corpus Christi

⸻

Project Title

Agentic AI for Autonomous Task Planning and Execution in Real-World Software Projects

⸻

Team Members

Abhishek Kumar Jha
Alexandra Aliyas
Md. Irshad Ahmed

⸻

1. Introduction and Motivation

Modern software development involves a complex lifecycle including requirements elicitation, system design, implementation, testing, validation, and deployment. Although large language models (LLMs) have recently demonstrated impressive capabilities in code generation and natural language understanding, most existing AI-based developer tools remain reactive, operating on single prompts without long-term planning, structured execution, or controlled iteration.

Additionally, many emerging “AI software builders” lack essential software engineering safeguards such as traceability, approval gates, auditability, and human oversight. This often results in blind execution, increased rework, loss of user trust, and difficulty managing evolving requirements.

This project proposes an agentic artificial intelligence system that mimics the Software Development Life Cycle (SDLC) by combining autonomous agents with human-in-the-loop control, document-level source of truth, and stage-gated execution. The goal is to bridge the gap between traditional software engineering practices and modern AI-driven automation.

⸻

2. Problem Statement

Existing LLM-based systems for software development suffer from the following limitations:
	1.	Lack of long-horizon planning and task decomposition
	2.	Absence of explicit SDLC modeling and lifecycle awareness
	3.	Minimal or no human validation during intermediate stages
	4.	Poor traceability between requirements, design, and code
	5.	Limited control over cost, execution scope, and tool usage

These limitations prevent AI systems from being safely and effectively adopted in real-world software engineering environments.

⸻

3. Project Objectives

The primary objective of this project is to design and implement an agentic AI-driven SDLC orchestration platform that:
	1.	Accepts high-level software requirements through conversational interaction
	2.	Produces structured software artifacts (requirements, design, plans)
	3.	Executes implementation tasks autonomously using specialized agents
	4.	Incorporates human validation at key SDLC stages
	5.	Maintains artifacts as the single source of truth
	6.	Provides full visibility, auditability, and execution control

⸻

4. Proposed Solution Overview

We propose a modular monolithic platform composed of:
	•	A FastAPI-based orchestrator that governs SDLC progression
	•	A set of specialized agent roles (Requirements, Architecture, Planner, Implementation, QA)
	•	Controlled invocation of Amazon Bedrock Agents as execution workers
	•	A document-first workflow where artifacts drive downstream actions
	•	A stage-gated SDLC state machine with explicit approvals

The system supports both non-technical users (guided conversational interface) and advanced technical users (artifact editing, architectural overrides).

⸻

5. System Architecture

5.1 Architectural Style
	•	Modular Monolith (Monorepo)
	•	Clear module boundaries for future scalability
	•	Single deployable unit for simplicity and reliability

5.2 Core Components
	1.	Web Interface (Vue 3)
	•	Guided SDLC workflow
	•	Approval and review controls
	•	Advanced configuration mode
	2.	Orchestrator API (FastAPI)
	•	SDLC state machine
	•	Approval gates
	•	Run and budget management
	•	Agent invocation coordination
	3.	Agent Execution Layer (Amazon Bedrock)
	•	Role-specific agents with scoped permissions
	•	Controlled tool usage
	4.	Workspace & Repository Manager
	•	Branch-based execution
	•	Diff and change tracking
	5.	Artifact Store and Audit Ledger
	•	Persistent documentation
	•	Complete execution traceability

⸻

6. Agent Roles and Responsibilities

Agent	Responsibility
Requirements Agent	Generate PRD, user stories, acceptance criteria
Architecture Agent	Propose architecture and design decisions
Planner Agent	Generate task graph and execution plan
Implementation Agent	Execute tasks in controlled workspace
QA Agent	Generate and validate tests

The orchestrator, not the agents, controls SDLC progression.

⸻

7. Human-in-the-Loop Control

Human validation is enforced at critical SDLC stages:
	•	Requirements approval
	•	Design approval
	•	Final merge and deployment approval

Users can pause, resume, modify, or cancel execution at any stage, ensuring transparency and trust.

⸻

8. Research Foundation

This project builds upon recent advances in agentic AI and autonomous reasoning, including:
	•	ReAct (Reasoning + Acting)
	•	Reflexion (Self-reflection and correction)
	•	Generative Agents (Memory and planning)
	•	SWE-Agent (Software engineering task execution)

Unlike prior work, this project emphasizes software engineering governance, not just task automation.

⸻

9. Evaluation Methodology

The system will be evaluated against a single-prompt LLM baseline using:
	1.	Task completion rate
	2.	Number of human interventions
	3.	Error recovery success rate
	4.	Requirement change handling effectiveness
	5.	Execution transparency and traceability

Experiments will be conducted on predefined software development tasks.

⸻

10. Expected Outcomes

By the end of the project, we expect to deliver:
	•	A working agentic SDLC orchestration platform
	•	Demonstrable reduction in rework through document-level control
	•	Improved task completion and error recovery compared to baseline
	•	Comprehensive documentation and evaluation results

⸻

11. Project Timeline (High-Level)

Phase	Description
Weeks 1–2	Architecture finalization, system skeleton
Weeks 3–5	SDLC state machine and approvals
Weeks 6–8	Agent integration and execution flow
Weeks 9–11	Testing, evaluation, refinements
Weeks 12–14	Final report, demo, and presentation


⸻

12. Significance

This project contributes to the emerging field of agentic software engineering by demonstrating how autonomous AI systems can be safely integrated into real-world development workflows. The proposed architecture balances automation with human oversight, making it suitable for both academic research and future industrial adoption.

⸻

Conclusion

The proposed system represents a principled, research-grounded approach to autonomous software development. By combining agentic AI with traditional software engineering discipline, this project aims to advance the state of the art in AI-assisted development while maintaining trust, control, and scalability.

⸻