"""Human closure must fail closed without mutating preserved evidence."""
import json

import pytest

from src.closure import ResearchClosedError, require_open, require_real_money_allowed


def test_closed_track_requires_new_auditable_human_decision(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps({"tracks": {
        "H8": "CLOSED_BY_HUMAN_DECISION", "H2H": "CLOSED_BY_HUMAN_DECISION"}}), encoding="utf-8")
    with pytest.raises(ResearchClosedError, match="H8 is CLOSED_BY_HUMAN_DECISION"):
        require_open("H8", root=tmp_path)
    with pytest.raises(ResearchClosedError, match="H2H is CLOSED_BY_HUMAN_DECISION"):
        require_open("H2H", root=tmp_path)


def test_missing_closure_artifact_fails_closed(tmp_path):
    with pytest.raises(ResearchClosedError, match="fail-closed"):
        require_open("H8", root=tmp_path)


@pytest.mark.parametrize("operation", ["track", "money"])
def test_closure_with_invalid_json_structure_fails_closed(tmp_path, operation):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ResearchClosedError, match="invalid structure"):
        if operation == "track":
            require_open("H2H", root=tmp_path)
        else:
            require_real_money_allowed(root=tmp_path)


def test_human_closure_blocks_real_money(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps({
        "real_money_operation": "PERMANENTLY_BLOCKED"}), encoding="utf-8")
    with pytest.raises(PermissionError, match="PERMANENTLY_BLOCKED"):
        require_real_money_allowed(root=tmp_path)


@pytest.mark.parametrize("payload", [
    {},
    {"real_money_operation": None},
    {"real_money_operation": "UNKNOWN"},
])
def test_real_money_requires_explicit_allow_marker(tmp_path, payload):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PermissionError, match="not explicitly allowed"):
        require_real_money_allowed(root=tmp_path)


def test_explicit_human_allow_marker_is_the_only_open_state(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "authorized_closure.json").write_text(json.dumps({
        "real_money_operation": "ALLOWED_BY_HUMAN_DECISION",
    }), encoding="utf-8")
    require_real_money_allowed(root=tmp_path)
