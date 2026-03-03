"""Tests for app.report_generator — periodic report generation for governors."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_events_dir(tmp_path):
    """Create instance/watcher/events/ structure and return the events dir."""
    events_dir = tmp_path / "instance" / "watcher" / "events"
    events_dir.mkdir(parents=True)
    return events_dir


def _write_jsonl(path: Path, lines: list[dict]):
    """Write a list of dicts as JSONL to a file."""
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def _make_detections_file(tmp_path, detections: list[dict]):
    """Create instance/advisor/detections.yaml with given detection entries."""
    advisor_dir = tmp_path / "instance" / "advisor"
    advisor_dir.mkdir(parents=True, exist_ok=True)
    detections_path = advisor_dir / "detections.yaml"
    with open(detections_path, "w") as f:
        yaml.dump({"detections": detections}, f)
    return detections_path


# ---------------------------------------------------------------------------
# test_empty_report — no data files, all zeros
# ---------------------------------------------------------------------------

class TestEmptyReport:
    def test_empty_report(self, tmp_path):
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["events_count"] == 0
        assert report["detections_count"] == 0
        assert report["false_positive_rate"] == 0.0
        assert report["budget_spent"] == {}
        assert report["budget_total"] == 0.0
        assert report["credential_alerts"] == 0
        assert report["top_citizens"] == []
        assert report["period_start"] == "2026-03-01"
        assert report["period_end"] == "2026-03-01"
        assert "generated_at" in report


# ---------------------------------------------------------------------------
# test_count_watcher_events — JSONL files, events_count matches
# ---------------------------------------------------------------------------

class TestCountWatcherEvents:
    def test_count_watcher_events(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany-yourart", "author_type": "citizen", "type": "push"},
            {"author": "alex-tech", "author_type": "tech", "type": "push"},
            {"author": "dany-yourart", "author_type": "citizen", "type": "issue_opened"},
        ])
        _write_jsonl(events_dir / "2026-03-02.jsonl", [
            {"author": "paolalevy", "author_type": "citizen", "type": "push"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 2))

        assert report["events_count"] == 4

    def test_only_counts_events_in_period(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany", "author_type": "citizen", "type": "push"},
        ])
        _write_jsonl(events_dir / "2026-03-03.jsonl", [
            {"author": "dany", "author_type": "citizen", "type": "push"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["events_count"] == 1

    def test_skips_blank_lines(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        (events_dir / "2026-03-01.jsonl").write_text(
            json.dumps({"author": "a", "author_type": "citizen", "type": "push"}) + "\n"
            "\n"
            "\n"
            + json.dumps({"author": "b", "author_type": "tech", "type": "push"}) + "\n"
        )

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["events_count"] == 2


# ---------------------------------------------------------------------------
# test_top_citizens — citizen events counted, sorted by count
# ---------------------------------------------------------------------------

class TestTopCitizens:
    def test_top_citizens(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany-yourart", "author_type": "citizen", "type": "push"},
            {"author": "dany-yourart", "author_type": "citizen", "type": "push"},
            {"author": "dany-yourart", "author_type": "citizen", "type": "push"},
            {"author": "paolalevy", "author_type": "citizen", "type": "push"},
            {"author": "paolalevy", "author_type": "citizen", "type": "issue_opened"},
            {"author": "alex-tech", "author_type": "tech", "type": "push"},
            {"author": "vbLBB", "author_type": "citizen", "type": "push"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        top = report["top_citizens"]
        assert len(top) == 3
        assert top[0] == {"login": "dany-yourart", "events": 3}
        assert top[1] == {"login": "paolalevy", "events": 2}
        assert top[2] == {"login": "vbLBB", "events": 1}

    def test_tech_users_excluded_from_top_citizens(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "alex-tech", "author_type": "tech", "type": "push"},
            {"author": "alex-tech", "author_type": "tech", "type": "push"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["top_citizens"] == []

    def test_top_citizens_limited_to_10(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        lines = [
            {"author": f"citizen-{i:02d}", "author_type": "citizen", "type": "push"}
            for i in range(15)
        ]
        _write_jsonl(events_dir / "2026-03-01.jsonl", lines)

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert len(report["top_citizens"]) == 10


# ---------------------------------------------------------------------------
# test_count_detections — detections.yaml, verify count
# ---------------------------------------------------------------------------

class TestCountDetections:
    def test_count_detections(self, tmp_path):
        _make_events_dir(tmp_path)
        _make_detections_file(tmp_path, [
            {"id": "det-001", "created_at": "2026-03-01T10:00:00Z", "status": "confirmed", "type": "duplication"},
            {"id": "det-002", "created_at": "2026-03-01T14:30:00Z", "status": "confirmed", "type": "duplication"},
            {"id": "det-003", "created_at": "2026-03-02T09:00:00Z", "status": "confirmed", "type": "convergence"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 2))

        assert report["detections_count"] == 3

    def test_detections_outside_period_excluded(self, tmp_path):
        _make_events_dir(tmp_path)
        _make_detections_file(tmp_path, [
            {"id": "det-001", "created_at": "2026-03-01T10:00:00Z", "status": "confirmed", "type": "duplication"},
            {"id": "det-002", "created_at": "2026-02-28T14:30:00Z", "status": "confirmed", "type": "duplication"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["detections_count"] == 1

    def test_no_detections_file(self, tmp_path):
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["detections_count"] == 0
        assert report["false_positive_rate"] == 0.0


# ---------------------------------------------------------------------------
# test_false_positive_rate — detections with status "false_positive"
# ---------------------------------------------------------------------------

class TestFalsePositiveRate:
    def test_false_positive_rate(self, tmp_path):
        _make_events_dir(tmp_path)
        _make_detections_file(tmp_path, [
            {"id": "det-001", "created_at": "2026-03-01T10:00:00Z", "status": "confirmed", "type": "duplication"},
            {"id": "det-002", "created_at": "2026-03-01T11:00:00Z", "status": "false_positive", "type": "duplication"},
            {"id": "det-003", "created_at": "2026-03-01T12:00:00Z", "status": "confirmed", "type": "convergence"},
            {"id": "det-004", "created_at": "2026-03-01T13:00:00Z", "status": "false_positive", "type": "duplication"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["detections_count"] == 4
        assert report["false_positive_rate"] == pytest.approx(0.5)

    def test_false_positive_rate_zero_when_none(self, tmp_path):
        _make_events_dir(tmp_path)
        _make_detections_file(tmp_path, [
            {"id": "det-001", "created_at": "2026-03-01T10:00:00Z", "status": "confirmed", "type": "duplication"},
            {"id": "det-002", "created_at": "2026-03-01T11:00:00Z", "status": "confirmed", "type": "duplication"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["false_positive_rate"] == 0.0

    def test_false_positive_rate_all_fp(self, tmp_path):
        _make_events_dir(tmp_path)
        _make_detections_file(tmp_path, [
            {"id": "det-001", "created_at": "2026-03-01T10:00:00Z", "status": "false_positive", "type": "duplication"},
            {"id": "det-002", "created_at": "2026-03-01T11:00:00Z", "status": "false_positive", "type": "duplication"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["false_positive_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# test_credential_alerts — lines with "credential_detected"
# ---------------------------------------------------------------------------

class TestCredentialAlerts:
    def test_credential_alerts(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany", "author_type": "citizen", "type": "push"},
            {"author": "dany", "author_type": "citizen", "type": "credential_detected", "detail": "API key found"},
            {"author": "alex", "author_type": "tech", "type": "push"},
            {"author": "paola", "author_type": "citizen", "type": "credential_detected", "detail": "token leaked"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["credential_alerts"] == 2

    def test_credential_alerts_zero(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany", "author_type": "citizen", "type": "push"},
            {"author": "alex", "author_type": "tech", "type": "push"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 1))

        assert report["credential_alerts"] == 0

    def test_credential_alerts_multiday(self, tmp_path):
        events_dir = _make_events_dir(tmp_path)

        _write_jsonl(events_dir / "2026-03-01.jsonl", [
            {"author": "dany", "author_type": "citizen", "type": "credential_detected"},
        ])
        _write_jsonl(events_dir / "2026-03-02.jsonl", [
            {"author": "paola", "author_type": "citizen", "type": "credential_detected"},
            {"author": "vbLBB", "author_type": "citizen", "type": "credential_detected"},
        ])

        instance_dir = tmp_path / "instance"

        with patch("app.report_generator.INSTANCE_DIR", instance_dir), \
             patch("app.report_generator.load_config", return_value={}):
            from app.report_generator import generate_report
            report = generate_report(date(2026, 3, 1), date(2026, 3, 2))

        assert report["credential_alerts"] == 3
