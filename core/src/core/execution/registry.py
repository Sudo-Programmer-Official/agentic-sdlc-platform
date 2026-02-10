from __future__ import annotations

from typing import Dict, Tuple

from core.execution.agents import AgentInterface, AgentType
from core.models import Stage


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: Dict[Tuple[AgentType, Stage], AgentInterface] = {}

    def register(self, agent: AgentInterface) -> None:
        for stage in agent.supported_stages:
            key = (agent.agent_type, stage)
            if key in self._agents:
                raise ValueError(f"Agent already registered for {agent.agent_type} at {stage}")
            self._agents[key] = agent

    def get(self, agent_type: AgentType, stage: Stage) -> AgentInterface:
        key = (agent_type, stage)
        if key not in self._agents:
            raise KeyError(f"No agent registered for {agent_type} at {stage}")
        return self._agents[key]
