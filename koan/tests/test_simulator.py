"""Tests for simulator — event construction, scenario loading, replay."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


SCENARIOS_YAML = """
scenarios:
  commit_citizen:
    name: "Test commit"
    event_template:
      type: push
      platform: github
      repo: test-repo
      author: test-user
      author_type: citizen
      author_name: Test
      branch: main
      summary: "test commit message"
      source: simulation
  credential_leak:
    name: "Test credential"
    event_template:
      type: push
      platform: github
      repo: fetching
      author: art236
      author_type: citizen
      summary: "credential leak test"
      source: simulation
"""


@pytest.fixture(autouse=True)
def env_setup(tmp_path, monkeypatch):
    """Set up minimal KOAN_ROOT environment."""
    koan_root = tmp_path / "koan"
    koan_root.mkdir()
    instance = koan_root / "instance"
    instance.mkdir()
    (instance / "config.yaml").write_text(
        "advisor:\n  enabled: false\n  scan_on_event: false\n"
    )

    # Create simulate dir with scenarios
    sim_dir = instance / "simulate"
    sim_dir.mkdir()
    scenarios_path = sim_dir / "scenarios.yaml"
    scenarios_path.write_text(SCENARIOS_YAML)

    # Create watcher events dir
    events_dir = instance / "watcher" / "events"
    events_dir.mkdir(parents=True)

    monkeypatch.setenv("KOAN_ROOT", str(koan_root))

    # Patch module-level SCENARIOS_FILE to use tmp_path
    import app.simulator as sim_mod
    monkeypatch.setattr(sim_mod, "SCENARIOS_FILE", scenarios_path)
    monkeypatch.setattr(sim_mod, "INSTANCE_DIR", instance)


class TestLoadScenarios:
    """Test scenario YAML loading."""

    def test_load_scenarios(self):
        from app.simulator import _load_scenarios
        scenarios = _load_scenarios()
        assert "commit_citizen" in scenarios
        assert "credential_leak" in scenarios

    def test_scenario_has_template(self):
        from app.simulator import _load_scenarios
        scenarios = _load_scenarios()
        template = scenarios["commit_citizen"]["event_template"]
        assert template["type"] == "push"
        assert template["platform"] == "github"


class TestBuildEvent:
    """Test WatcherEvent construction from scenarios."""

    def test_build_from_scenario(self):
        from app.simulator import build_event
        event = build_event("commit_citizen")
        assert event.platform == "github"
        assert event.type == "push"
        assert event.repo == "test-repo"
        assert event.author == "test-user"
        assert event.id.startswith("evt-")

    def test_build_with_overrides(self):
        from app.simulator import build_event
        event = build_event("commit_citizen", {"author": "custom-user", "repo": "custom-repo"})
        assert event.author == "custom-user"
        assert event.repo == "custom-repo"

    def test_build_unknown_scenario(self):
        from app.simulator import build_event
        event = build_event("nonexistent", {"repo": "test", "author": "user"})
        assert event.repo == "test"

    def test_auto_timestamp(self):
        from app.simulator import build_event
        event = build_event("commit_citizen")
        assert event.timestamp  # Should be auto-filled
        assert "T" in event.timestamp  # ISO format


class TestSimulateCommit:
    """Test simulate_commit function."""

    def test_simulate_commit_dry_run(self):
        from app.simulator import simulate_commit
        result = simulate_commit(
            author="test-user",
            repo="test-repo",
            message="test message",
            dry_run=True,
        )
        assert "[DRY RUN]" in result
        assert "test-user" in result
        assert "test-repo" in result

    def test_simulate_commit_creates_journal_entry(self):
        from app.simulator import simulate_commit, INSTANCE_DIR
        result = simulate_commit(
            author="test-user",
            repo="test-repo",
            message="test message",
            dry_run=True,
        )
        # Check journal file exists (use patched INSTANCE_DIR)
        events_dir = INSTANCE_DIR / "watcher" / "events"
        journal_files = list(events_dir.glob("*.jsonl"))
        assert len(journal_files) > 0

        # Check event was written
        with open(journal_files[0]) as f:
            lines = f.readlines()
        assert len(lines) > 0
        event = json.loads(lines[-1])
        assert event["author"] == "test-user"
        assert event["repo"] == "test-repo"


class TestSimulateCredential:
    """Test simulate_credential function."""

    def test_simulate_credential_dry_run(self):
        from app.simulator import simulate_credential
        result = simulate_credential(repo="fetching", file=".env", dry_run=True)
        assert "[DRY RUN]" in result
        assert "fetching" in result


class TestSimulateReplay:
    """Test replay from journal."""

    def test_replay_no_journal(self):
        from app.simulator import simulate_replay
        result = simulate_replay("2020-01-01", dry_run=True)
        assert "Pas de journal" in result

    def test_replay_with_events(self):
        from app.simulator import simulate_replay, INSTANCE_DIR

        # Create a journal file for today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events_dir = INSTANCE_DIR / "watcher" / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        journal_file = events_dir / f"{today}.jsonl"

        event = {
            "id": "evt-test-001",
            "platform": "github",
            "type": "push",
            "repo": "test-repo",
            "author": "test-user",
            "author_type": "citizen",
            "author_name": "Test",
            "branch": "main",
            "summary": "test event for replay",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(journal_file, "w") as f:
            f.write(json.dumps(event) + "\n")

        result = simulate_replay(today, dry_run=True)
        assert "1 événements" in result or "1 rejoués" in result


class TestHandleSimulate:
    """Test CLI entry point for simulate commands."""

    def test_help(self):
        from app.simulator import handle_simulate
        flags = MagicMock(dry_run=False, output_json=False, notify=False)
        code = handle_simulate("", "", flags)
        assert code == 0

    def test_missing_args(self, capsys):
        from app.simulator import handle_simulate
        flags = MagicMock(dry_run=True, output_json=False, notify=False)
        code = handle_simulate("commit", "", flags)
        assert code == 1  # Missing required args

    def test_unknown_action(self, capsys):
        from app.simulator import handle_simulate
        flags = MagicMock(dry_run=True, output_json=False, notify=False)
        code = handle_simulate("unknown", "", flags)
        assert code == 1
