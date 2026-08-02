"""LocalAPIBackend + ChangeApplicator + LoopConfig 단위 테스트."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.backends.local_llm import ChangeApplicator, LocalAPIBackend
from engine.loop_engine import LoopConfig, build_iter_context


# ---------------------------------------------------------------------------
# ChangeApplicator
# ---------------------------------------------------------------------------

class TestChangeApplicator:
    def test_writes_file(self, tmp_path):
        appl = ChangeApplicator(str(tmp_path))
        text = '<file_write path="src/hello.py">\nprint("hi")\n</file_write>\n<step_update step="1" status="completed" summary="done"/>'
        completed, actions, err = appl.apply(text)
        assert completed
        assert (tmp_path / "src" / "hello.py").read_text() == 'print("hi")\n'
        assert err is None

    def test_creates_parent_dirs(self, tmp_path):
        appl = ChangeApplicator(str(tmp_path))
        text = '<file_write path="a/b/c/file.txt">\ncontent\n</file_write>\n<step_update step="1" status="completed"/>'
        appl.apply(text)
        assert (tmp_path / "a" / "b" / "c" / "file.txt").exists()

    def test_missing_step_update_returns_error(self, tmp_path):
        appl = ChangeApplicator(str(tmp_path))
        text = "<file_write path=\"x.py\">\npass\n</file_write>"
        completed, _, err = appl.apply(text)
        assert not completed
        assert err and "<step_update>" in err

    def test_updates_index_json(self, tmp_path):
        index_path = tmp_path / "index.json"
        index = {"steps": [{"step": 2, "name": "impl", "status": "pending"}]}
        index_path.write_text(json.dumps(index))
        appl = ChangeApplicator(str(tmp_path), index_path)
        text = '<step_update step="2" status="completed" summary="구현 완료"/>'
        appl.apply(text)
        updated = json.loads(index_path.read_text())
        step = updated["steps"][0]
        assert step["status"] == "completed"
        assert step["summary"] == "구현 완료"

    def test_pending_status_not_completed(self, tmp_path):
        index_path = tmp_path / "index.json"
        index = {"steps": [{"step": 1, "status": "pending"}]}
        index_path.write_text(json.dumps(index))
        appl = ChangeApplicator(str(tmp_path), index_path)
        text = '<step_update step="1" status="pending" summary="실패"/>'
        completed, _, _ = appl.apply(text)
        assert not completed

    def test_blocks_dangerous_shell(self, tmp_path):
        appl = ChangeApplicator(str(tmp_path))
        text = '<shell_run>\nrm -rf /\n</shell_run>\n<step_update step="1" status="completed"/>'
        _, actions, _ = appl.apply(text)
        assert any("BLOCKED" in a for a in actions)


# ---------------------------------------------------------------------------
# LoopConfig
# ---------------------------------------------------------------------------

class TestLoopConfig:
    def test_defaults(self):
        cfg = LoopConfig.from_step({}, default_max=3)
        assert cfg.type == "retry"
        assert cfg.max_iterations == 3

    def test_from_step_reflect(self):
        step = {"step": 1, "loop": {"type": "reflect", "max_iterations": 5}}
        cfg = LoopConfig.from_step(step)
        assert cfg.type == "reflect"
        assert cfg.max_iterations == 5

    def test_label_retry(self):
        assert LoopConfig(type="retry").label == "retry"

    def test_label_fixed(self):
        assert LoopConfig(type="fixed").label == "iter"


# ---------------------------------------------------------------------------
# build_iter_context
# ---------------------------------------------------------------------------

class TestBuildIterContext:
    def test_retry_uses_stderr(self):
        cfg = LoopConfig(type="retry")
        ctx = build_iter_context(cfg, "", "some error", 1, 1)
        assert ctx == "some error"

    def test_retry_uses_stdout_if_no_stderr(self):
        cfg = LoopConfig(type="retry")
        ctx = build_iter_context(cfg, "output text", "", 0, 1)
        assert ctx == "output text"

    def test_retry_includes_ac_failures_and_changed_files(self):
        cfg = LoopConfig(type="retry")
        ctx = build_iter_context(
            cfg, "some stdout", "", 0, 1,
            ac_failures=["`npm test` — 실패 (exit 1)"],
            changed_files=["src/space-spec/parser.ts"],
        )
        assert "npm test" in ctx
        assert "src/space-spec/parser.ts" in ctx

    def test_retry_plain_behavior_preserved_without_enrichment(self):
        cfg = LoopConfig(type="retry")
        ctx = build_iter_context(cfg, "", "some error", 1, 1)
        assert ctx == "some error"

    def test_fixed_includes_output(self):
        cfg = LoopConfig(type="fixed")
        ctx = build_iter_context(cfg, "prev output", "", 0, 2)
        assert "prev output" in ctx
        assert "2" in ctx

    def test_reflect_calls_invoker(self):
        cfg = LoopConfig(type="reflect", eval_prompt_suffix="검토하라")
        invoker = MagicMock(return_value="개선 필요: X를 고쳐라")
        ctx = build_iter_context(cfg, "my output", "", 0, 1, reflect_invoker=invoker)
        assert invoker.called
        assert "개선 필요" in ctx

    def test_reflect_no_invoker_still_returns_context(self):
        cfg = LoopConfig(type="reflect")
        ctx = build_iter_context(cfg, "output", "", 0, 1, reflect_invoker=None)
        assert "output" in ctx


# ---------------------------------------------------------------------------
# LocalAPIBackend (mocked HTTP)
# ---------------------------------------------------------------------------

class TestLocalAPIBackend:
    def _make_backend(self):
        return LocalAPIBackend(
            name="test-llm",
            endpoint="http://192.168.0.10:11434/v1/chat/completions",
            model="qwen2.5-coder:32b",
            guardrail_files=[],
        )

    def _api_response(self, content: str) -> bytes:
        return json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")

    def test_completed_step_returns_exit_0(self, tmp_path):
        index_path = tmp_path / "index.json"
        index_path.write_text(json.dumps({"steps": [{"step": 1, "status": "pending"}]}))
        content = '<step_update step="1" status="completed" summary="done"/>'
        backend = self._make_backend()

        mock_resp = MagicMock()
        mock_resp.read.return_value = self._api_response(content)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = backend.invoke("do step", cwd=str(tmp_path), timeout=60, index_file=index_path)

        assert result.exit_code == 0
        assert result.backend == "test-llm"

    def test_http_error_returns_exit_1(self, tmp_path):
        import urllib.error
        backend = self._make_backend()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = backend.invoke("do step", cwd=str(tmp_path), timeout=60)
        assert result.exit_code == 1
        assert "HTTP 오류" in result.stderr

    def test_missing_step_update_returns_exit_1(self, tmp_path):
        content = '<file_write path="x.py">\npass\n</file_write>'
        backend = self._make_backend()

        mock_resp = MagicMock()
        mock_resp.read.return_value = self._api_response(content)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = backend.invoke("do step", cwd=str(tmp_path), timeout=60)

        assert result.exit_code == 1
        assert "<step_update>" in result.stderr
