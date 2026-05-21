import sys
from pathlib import Path

TEMPLATE_API_ROOT = Path(__file__).resolve().parents[1]
if str(TEMPLATE_API_ROOT) not in sys.path:
    sys.path.insert(0, str(TEMPLATE_API_ROOT))

from app.main import app


def test_health_route_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/leads" in paths
