import uuid

from app.operator.intents import OperatorIntent, classify_intent
from app.operator.schemas import OperatorContext, OperatorRequest


def _request(message: str) -> OperatorRequest:
    return OperatorRequest(project_id=uuid.uuid4(), message=message, context=OperatorContext())


def test_classify_intent_routes_known_queries():
    assert classify_intent(_request("Why did the latest run fail?")) == OperatorIntent.RUN_DEBUG
    assert classify_intent(_request("Explain the latest patch")) == OperatorIntent.ARTIFACT_EXPLAIN
    assert classify_intent(_request("Compare the last two runs")) == OperatorIntent.RUN_COMPARISON
    assert classify_intent(_request("Show workspace status")) == OperatorIntent.WORKSPACE_STATUS
    assert classify_intent(_request("Show project health")) == OperatorIntent.PROJECT_HEALTH
    assert classify_intent(_request("Show repo map")) == OperatorIntent.REPO_CONTEXT
    assert classify_intent(_request("Find the login component")) == OperatorIntent.REPO_CONTEXT
    assert classify_intent(_request("What is going on in this project?")) == OperatorIntent.PROJECT_STATUS
