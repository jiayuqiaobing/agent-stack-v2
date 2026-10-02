from runtime.planner.coverage import coverage_for
from runtime.planner.templates import TEMPLATES


def test_every_registered_type_has_a_matrix_entry():
    for name in TEMPLATES:
        found = coverage_for(name)
        assert "task_facts" in found["core"]
        assert "hidden_details" in found["core"]
        assert "acceptance" in found["core"]
        assert "resource_requests" in found["core"]


def test_unmatched_has_no_specialized_checks():
    assert coverage_for("unmatched")["specialized"] == []
