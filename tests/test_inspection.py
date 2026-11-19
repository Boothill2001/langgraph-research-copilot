from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from copilot.inspection import current_execution


def test_new_execution_replaces_stale_first_node_in_live_view():
    events = [{"id": 803, "node": "understand"}, {"id": 804, "node": "planner"}]
    assert current_execution(events, follow_latest=True, node="understand", event_id=803)["id"] == 804
    events.append({"id": 805, "node": "tools"})
    assert current_execution(events, follow_latest=True, node="understand", event_id=803)["id"] == 805


def test_explicit_history_is_preserved_while_new_nodes_run():
    events = [{"id": 803, "node": "understand"}, {"id": 804, "node": "planner"}, {"id": 805, "node": "tools"}]
    assert current_execution(events, follow_latest=False, node="understand", event_id=803)["id"] == 803
    assert current_execution(events, follow_latest=False, node="save") is None
