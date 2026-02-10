projecFINAL PROJECT SCOPE
Agentic AI for Autonomous Task Planning and Execution in Real-World Software Projects

1. What We Are Building (One-Sentence Version)
An agentic AI system that can take a high-level software task, autonomously plan, execute, monitor, and self-correct its actions using tools, with minimal human intervention.
This is not a chatbot.
This is a goal-driven autonomous system.

2. Core Problem We Are Solving
Most LLM-based tools:
Respond to single prompts


Cannot plan long tasks


Cannot recover from failure


Require constant human steering


We solve this by introducing:
Explicit planning


Task decomposition


Tool execution


Reflection + retry



3. System Boundaries (VERY IMPORTANT)
 What IS in scope
Autonomous planning


Multi-step execution


Tool usage


Self-reflection


Measurable evaluation


What is NOT in scope
Training new LLMs


Reinforcement learning from scratch


Large-scale production deployment


Security / cybersecurity concerns


UI polish (CLI or simple UI is enough)


This keeps the project doable in one semester.

4. Target Use Case (Concrete & Defensible)
Chosen Domain: 
Software Project Tasks
The system will handle tasks like:
“Set up a backend API project”


“Create a REST endpoint with validation”


“Refactor code to follow a design pattern”


“Generate tests and run them”


“Fix a failing build”


This aligns perfectly with:
SWE-Agent


AutoGen


Real-world relevance


Your future work



5. High-Level Architecture (Conceptual)
The system will consist of 
5 core components
1️ Task Interpreter Agent
Takes user’s high-level goal


Converts it into a structured objective


2️Planner Agent
Breaks the goal into ordered sub-tasks


Produces a task graph or step list


3️ Executor Agent
Executes steps using tools:


File system


Code editor


Shell commands


APIs (simulated or real)


4️⃣ Critic / Reflection Agent
Evaluates execution results


Detects failures or inconsistencies


Suggests corrections


5️ Memory Module
Stores:


Past steps


Errors


Decisions


Used to avoid repeating mistakes


This architecture directly maps to agentic AI literature.

6. Tooling Scope (What the Agent Can Do)
The agent will be allowed to use:
Read/write files


Execute shell commands (sandboxed)


Run tests or linters


Call predefined helper scripts


Use documentation files as context


Tools are restricted on purpose to ensure safety and reproducibility.

7. Baseline for Comparison (Critical for Grade A)
We will compare against:
🔹 Baseline System
Single-prompt LLM


No planning


No reflection


No retries


🔹 Proposed System
Multi-step planning


Tool execution


Reflection + retry loop


This comparison is mandatory and makes the project “research-grade.”

8. Evaluation Metrics (Professor-Approved)
We will evaluate using:
Task Completion Rate


% of tasks completed successfully


Number of Human Interventions


Lower = better autonomy


Error Recovery Rate


% of failures fixed autonomously


Execution Steps Efficiency


Planned vs actual steps


Time to Completion


Optional but useful


These are quantitative, not hand-wavy.

9. Expected Deliverables
By the end of the semester:
📦 Technical
Working agentic AI system


Modular agent architecture


Reproducible experiments


Logged execution traces


📄 Academic
UML diagrams


Architecture diagrams


Evaluation tables


Comparison plots


Final report


🎥 Demo
Live or recorded demo of:


Task → Plan → Execute → Reflect → Finish



10. Why This Scope Is Perfect
✔ Not too big
✔ Not too small
✔ Clear novelty
✔ Easy to explain
✔ Easy to evaluate
✔ Reusable in real life
✔ Matches top papers
✔ Survives oral defense

NEXT STEP (Choose One)
Now that scope is locked, the next highest-value step is:
1️ Define exact task types (5–10 tasks for experiments)
2️ Draw system architecture diagram
3️ Assign team responsibilities
4️ Draft Part 1: Introduction & Related Work
5️ Design evaluation experiment table
Tell me the number(s), and we’ll move forward cleanly.

