"""Planner self-review contract tests.

Planning must be deliberately iterative: a draft is produced first, then the
backend is asked to reconsider it a configurable number of times.  Each review
response is a replacement plan, so only the final reviewed plan is persisted.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.planner import Planner


def _plan(phase_dir: str, phase_name: str, step_name: str) -> str:
    return f'''<phase_plan dir="{phase_dir}" name="{phase_name}" description="description">
<step num="0" name="{step_name}" summary="summary">
# Step 0: {step_name}

## Acceptance Criteria
- [ ] echo ok
</step>
</phase_plan>'''


def _goal() -> dict:
    return {"goal": "Build the feature", "success_criteria": ["It works"]}


def test_planner_runs_five_default_self_review_passes_and_applies_final_plan(tmp_path):
    """The default is an initial draft followed by five distinct review prompts."""
    backend = MagicMock()
    backend.query.side_effect = [
        _plan("0-draft", "Draft", "draft-step"),
        _plan("0-review-1", "Review 1", "review-1"),
        _plan("0-review-2", "Review 2", "review-2"),
        _plan("0-review-3", "Review 3", "review-3"),
        _plan("0-review-4", "Review 4", "review-4"),
        _plan("0-final", "Final", "final-step"),
    ]
    phases_dir = tmp_path / "phases"
    phases_dir.mkdir()

    result = Planner(backend, phases_dir).plan_next_phase(_goal(), "no prior phases")

    assert result == "0-final"
    assert backend.query.call_count == 6
    review_prompts = [call.args[0] for call in backend.query.call_args_list[1:]]
    assert len(review_prompts) == 5
    assert any("빠진" in prompt for prompt in review_prompts)
    assert any("확실" in prompt for prompt in review_prompts)
    assert any("완전히" in prompt or "완전" in prompt for prompt in review_prompts)

    index = json.loads((phases_dir / "0-final" / "index.json").read_text(encoding="utf-8"))
    assert index["phase"] == "Final"
    assert index["steps"] == [
        {"step": 0, "name": "final-step", "summary": "summary", "status": "pending"}
    ]
    assert not (phases_dir / "0-draft").exists()


def test_planner_review_count_is_configurable(tmp_path):
    """Callers can reduce or increase the number of review passes explicitly."""
    backend = MagicMock()
    backend.query.side_effect = [
        _plan("0-draft", "Draft", "draft-step"),
        _plan("0-final", "Final", "final-step"),
        _plan("0-reviewed", "Reviewed", "reviewed-step"),
    ]
    phases_dir = tmp_path / "phases"
    phases_dir.mkdir()

    result = Planner(backend, phases_dir, review_count=2).plan_next_phase(
        _goal(), "no prior phases"
    )

    assert result == "0-reviewed"
    assert backend.query.call_count == 3
    assert (phases_dir / "0-reviewed" / "step0.md").read_text(encoding="utf-8").startswith(
        "# Step 0: reviewed-step"
    )
