"""Blocking-fix 자동 복구 로직 테스트 (planner + loop_controller)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.planner import Planner
from engine.loop_controller import LoopController


def _phase(tmp_path, steps):
    phases_dir = tmp_path / "phases"
    phase_dir = phases_dir / "0-x"
    phase_dir.mkdir(parents=True)
    index = {"project": "p", "phase": "x", "steps": steps}
    (phase_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return phases_dir, phase_dir


def test_append_blocking_fix_appends_and_does_not_duplicate(tmp_path):
    steps = [
        {"step": 0, "name": "a", "status": "blocked", "blocked_reason": "contract mismatch"},
        {"step": 1, "name": "b", "status": "pending"},
    ]
    phases_dir, phase_dir = _phase(tmp_path, steps)
    planner = Planner(MagicMock(), phases_dir)

    n = planner.append_blocking_fix("0-x", steps[0])
    assert n == 2

    upd = json.loads((phase_dir / "index.json").read_text(encoding="utf-8"))
    fixer = upd["steps"][2]
    assert fixer["kind"] == "blocking-fix"
    assert fixer["unblocks"] == [0]
    assert fixer["status"] == "pending"
    assert (phase_dir / "step2.md").exists()
    assert "contract mismatch" in (phase_dir / "step2.md").read_text(encoding="utf-8")

    # 이미 실행 가능한 blocking-fix가 있으면 중복 append하지 않는다
    assert planner.append_blocking_fix("0-x", steps[0]) is None
    assert len(upd["steps"]) == 3


def test_recover_if_blocked_appends_blocking_fix(tmp_path):
    steps = [
        {"step": 0, "name": "a", "status": "blocked", "blocked_reason": "r"},
        {"step": 1, "name": "b", "status": "pending"},
    ]
    phases_dir, phase_dir = _phase(tmp_path, steps)

    ctrl = LoopController(tmp_path, tmp_path, MagicMock(), {"goal": "g"})
    planner = Planner(MagicMock(), phases_dir)

    assert ctrl._recover_if_blocked("0-x", planner) is True
    upd = json.loads((phase_dir / "index.json").read_text(encoding="utf-8"))
    assert upd["steps"][2]["kind"] == "blocking-fix"
    assert upd["steps"][2]["unblocks"] == [0]


def test_recover_if_blocked_false_when_no_blocked_step(tmp_path):
    steps = [
        {"step": 0, "name": "a", "status": "pending"},
        {"step": 1, "name": "b", "status": "completed", "summary": "done"},
    ]
    phases_dir, phase_dir = _phase(tmp_path, steps)

    ctrl = LoopController(tmp_path, tmp_path, MagicMock(), {"goal": "g"})
    planner = Planner(MagicMock(), phases_dir)

    assert ctrl._recover_if_blocked("0-x", planner) is False
    assert len(json.loads((phase_dir / "index.json").read_text(encoding="utf-8"))["steps"]) == 2


def test_recover_if_blocked_refuses_missing_phase(tmp_path):
    ctrl = LoopController(tmp_path, tmp_path, MagicMock(), {"goal": "g"})
    planner = Planner(MagicMock(), tmp_path / "phases")
    assert ctrl._recover_if_blocked("0-nope", planner) is False
