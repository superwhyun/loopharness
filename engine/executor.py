import json
import re
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List
import contextlib

from .backends.base import AgentBackend, BackendResult
from .backends.generic import GenericCommandBackend
from .backends.local_llm import LocalAPIBackend
from .git_manager import GitManager
from .loop_engine import LoopConfig, build_iter_context
from .prompt_builder import PromptBuilder
from .manifest import update_project_manifest
from .workspace import WorkspaceSnapshot


@contextlib.contextmanager
def progress_indicator(label: str):
    frames = "◐◓◑◒"
    stop = threading.Event()
    t0 = time.monotonic()

    def _animate():
        idx = 0
        while not stop.wait(0.12):
            sec = int(time.monotonic() - t0)
            sys.stderr.write(f"\r{frames[idx % len(frames)]} {label} [{sec}s]")
            sys.stderr.flush()
            idx += 1
        sys.stderr.write("\r" + " " * (len(label) + 20) + "\r")
        sys.stderr.flush()

    th = threading.Thread(target=_animate, daemon=True)
    th.start()
    info = types.SimpleNamespace(elapsed=0.0)
    try:
        yield info
    finally:
        stop.set()
        th.join()
        info.elapsed = time.monotonic() - t0


_FALLBACK_CONFIG: dict = {
    "default_backend": "claude",
    "dangerous_mode": False,
    "backends": {
        "claude": {
            "command": ["claude", "-p", "--output-format", "json", "{prompt}"],
            "dangerous_command": ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "json", "{prompt}"],
            "guardrail_files": ["CLAUDE.md"],
        }
    },
    "context": {"common_files": ["AGENTS.md", "docs/HARNESS.md", "docs/ARCHITECTURE.md"]},
}


class StepExecutor:
    MAX_RETRIES = 3
    COMMAND_TIMEOUT = 1800
    FEAT_MSG = "feat({project}/step{num}): {name}"
    TZ = timezone(timedelta(hours=9))
    DEFAULT_BACKEND = "claude"

    def __init__(
        self,
        root: Path,
        phase_dir_name: str,
        *,
        backend_name: Optional[str] = None,
        auto_push: bool = False,
        framework_root: Optional[Path] = None,
    ):
        self._root = str(root)
        self._framework_root = str(framework_root or root)
        self._phases_dir = root / "phases"
        self._phase_dir = self._phases_dir / phase_dir_name
        self._phase_dir_name = phase_dir_name
        self._top_index_file = self._phases_dir / "index.json"
        self._auto_push = auto_push
        self._harness_settings = self._load_harness_settings()
        self._backend = self._resolve_backend(backend_name)
        self._git = GitManager(self._root)
        self._prompt = PromptBuilder()

        if not self._phase_dir.is_dir():
            print(f"ERROR: {self._phase_dir} not found")
            sys.exit(1)

        self._index_file = self._phase_dir / "index.json"
        if not self._index_file.exists():
            print(f"ERROR: {self._index_file} not found")
            sys.exit(1)

        idx = self._read_json(self._index_file)
        self._project = idx.get("project", "project")
        self._phase_name = idx.get("phase", phase_dir_name)
        self._total = len(idx["steps"])

    def run(self):
        self._print_header()
        self._check_blockers()
        self._git.checkout(f"feat-{self._phase_name}")
        common_files = self._harness_settings.get("context", {}).get("common_files")
        guardrails = self._prompt.load_guardrails(
            Path(self._root), Path(self._framework_root), self._backend.guardrail_files,
            common_files=common_files,
        )
        manifest_context = self._prompt.load_project_manifest(self._phases_dir)
        self._ensure_created_at()
        self._execute_all_steps(guardrails, manifest_context)
        self._finalize()

    @staticmethod
    def _read_json(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(p: Path, data: dict):
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _stamp(self) -> str:
        return datetime.now(self.TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

    def _load_harness_settings(self) -> dict:
        config_file = Path(self._root) / "config.json"
        if not config_file.exists():
            framework_config = Path(self._framework_root) / "config.json"
            if framework_config.exists():
                config_file = framework_config
        if not config_file.exists():
            return {}
        try:
            return self._read_json(config_file)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: config.json 을 읽을 수 없습니다: {exc}")
            sys.exit(1)

    @classmethod
    def build_backend(
        cls,
        project_root: Path,
        framework_root: Path,
        backend_name: Optional[str] = None,
    ) -> AgentBackend:
        """config.json 을 읽어 backend 인스턴스를 생성한다. loop.py 등 외부에서도 사용."""
        config_file = project_root / "config.json"
        if not config_file.exists():
            config_file = framework_root / "config.json"
        settings: dict = _FALLBACK_CONFIG
        if config_file.exists():
            try:
                settings = json.loads(config_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        dangerous = settings.get("dangerous_mode", False)
        backends = {k: v for k, v in settings.get("backends", {}).items() if not k.startswith("_")}

        target = backend_name or settings.get("default_backend", cls.DEFAULT_BACKEND)
        config_data = backends.get(target)
        if config_data is None:
            available = ", ".join(sorted(backends)) if backends else "none configured"
            raise ValueError(f"backend '{target}' 가 정의되지 않았습니다. 사용 가능: {available}")

        guardrail_files = config_data.get("guardrail_files", [])

        if config_data.get("type") == "local_api":
            endpoint = config_data.get("endpoint", "")
            if not endpoint:
                raise ValueError(f"backend '{target}' 에 endpoint 가 없습니다.")
            return LocalAPIBackend(
                name=target,
                endpoint=endpoint,
                model=config_data.get("model", ""),
                guardrail_files=guardrail_files,
                temperature=float(config_data.get("temperature", 0.1)),
                max_tokens=int(config_data.get("max_tokens", 8192)),
                api_key=config_data.get("api_key", "local"),
            )

        if dangerous and "dangerous_command" in config_data:
            command = config_data["dangerous_command"]
        else:
            command = config_data.get("command")
        if not command:
            raise ValueError(f"backend '{target}' 에 command 가 없습니다.")

        return GenericCommandBackend(
            name=target,
            command_template=command,
            guardrail_files=guardrail_files,
        )

    def _resolve_backend(self, backend_name: Optional[str]) -> AgentBackend:
        try:
            return self.build_backend(
                Path(self._root), Path(self._framework_root), backend_name
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Objective completion gating
    #
    # "completed" 상태는 원칙적으로 step의 실행 가능한 검증(AC bash 블록 +
    # goal.json의 auto_checks)을 실제로 통과해야 인정한다. LLM이 완료로
    # 기록했더라도 실행 가능한 검증이 실패하면 재작성 반복으로 돌려보낸다.
    # 실행 가능한 검증이 하나도 없으면(체크박스만 있는 step 등) 기존대로
    # LLM self-report를 신뢰한다(no-op).
    # ------------------------------------------------------------------

    _AC_HEADING = re.compile(r"##\s+Acceptance Criteria", re.IGNORECASE)
    _NEXT_HEADING = re.compile(r"^##\s+", re.MULTILINE)
    _FENCE = re.compile(r"```(?:bash|sh)?\s*\n(.*?)\n```", re.DOTALL)

    def _extract_ac_commands(self, step_text: str) -> List[str]:
        m = self._AC_HEADING.search(step_text)
        if not m:
            return []
        section = step_text[m.end():]
        nxt = self._NEXT_HEADING.search(section)
        if nxt:
            section = section[: nxt.start()]
        commands: List[str] = []
        for fence in self._FENCE.findall(section):
            for raw in fence.splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    commands.append(line)
        return commands

    def _load_auto_checks(self) -> List[str]:
        goal_path = Path(self._root) / "goal.json"
        if not goal_path.exists():
            return []
        try:
            goal = self._read_json(goal_path)
        except (OSError, json.JSONDecodeError):
            return []
        checks = goal.get("auto_checks", [])
        return [c for c in checks if isinstance(c, str) and c.strip()]

    def _run_checks(self, commands: List[str]) -> List[str]:
        """각 검증 명령을 실행하고 실패한 항목의 설명을 반환한다."""
        failures: List[str] = []
        for cmd in commands:
            try:
                res = subprocess.run(
                    cmd, shell=True, cwd=self._root,
                    capture_output=True, text=True, timeout=600,
                )
                if res.returncode != 0:
                    out = (res.stdout or res.stderr).strip()[:400]
                    line = f"`{cmd}` — 실패 (exit {res.returncode})"
                    if out:
                        line += f"\n  {out}"
                    failures.append(line)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"`{cmd}` — 실행 오류: {exc}")
        return failures

    def _verify_runnable_checks(self, step_text: str) -> List[str]:
        commands = self._extract_ac_commands(step_text) + self._load_auto_checks()
        commands = [c for c in commands if c.strip()]
        if not commands:
            return []
        return self._run_checks([c for c in dict.fromkeys(commands)])

    def _execute_single_step(self, step: dict, guardrails: str, manifest_context: str):
        step_num, step_name = step["step"], step["name"]
        loop_cfg = LoopConfig.from_step(step, default_max=self.MAX_RETRIES)
        iter_context: Optional[str] = None
        step_file = self._phase_dir / f"step{step_num}.md"
        step_text = step_file.read_text(encoding="utf-8")

        # Computed once — completed steps and their summaries don't change during retries
        index = self._read_json(self._index_file)
        done = sum(1 for s in index["steps"] if s["status"] == "completed")
        step_context = self._prompt.build_step_context(index)

        for iteration in range(1, loop_cfg.max_iterations + 1):
            preamble = self._prompt.build_preamble(
                project=self._project,
                phase_name=self._phase_name,
                phase_dir_name=self._phase_dir_name,
                backend_name=self._backend.name,
                guardrails=guardrails,
                manifest_context=manifest_context,
                step_context=step_context,
                prev_error=iter_context,
                feat_msg_template=self.FEAT_MSG,
            )

            tag = f"Step {step_num}/{self._total - 1} ({done} done): {step_name}"
            if iteration > 1:
                tag += f" [{loop_cfg.label} {iteration}/{loop_cfg.max_iterations}]"

            with progress_indicator(tag) as pi:
                before = WorkspaceSnapshot(self._root).capture()
                prompt = preamble + step_text
                result = self._backend.invoke(
                    prompt,
                    cwd=self._root,
                    timeout=self.COMMAND_TIMEOUT,
                    index_file=self._index_file,
                )
                after = WorkspaceSnapshot(self._root).capture()
                changed_files = WorkspaceSnapshot.diff(before, after)
                elapsed = int(pi.elapsed)

            index = self._read_json(self._index_file)
            status = next((s["status"] for s in index["steps"] if s["step"] == step_num), "pending")

            ac_failures: List[str] = []
            if status == "completed":
                # "completed" self-report를 실행 가능한 검증으로 교차 확인.
                ac_failures = self._verify_runnable_checks(step_text)
                if not ac_failures:
                    print(f"  ✓ Step {step_num}: {step_name} [{elapsed}s]")
                    current_step = next((s for s in index["steps"] if s["step"] == step_num), step)
                    released_steps = self._release_blocked_steps(index, current_step)
                    if released_steps:
                        current_step["unblocked_steps"] = released_steps
                        self._write_json(self._index_file, index)
                    if not self._git.commit_all(self.FEAT_MSG.format(project=self._project, num=step_num, name=step_name)):
                        print(f"  ✗ Step {step_num} commit 실패 — 중단")
                        sys.exit(1)
                    return True
                # LLM이 완료로 기록했지만 실행 가능한 검증이 실패 — 완료로 인정하지
                # 않고 재작성 반복으로 보낸다.
                print(f"  ✗ Step {step_num} claimed completed but verification failed — retrying")
                if iteration == loop_cfg.max_iterations:
                    print(f"  ✗ Step {step_num} failed after {loop_cfg.max_iterations} {loop_cfg.label} iteration(s). Verification still failing:")
                    for f in ac_failures:
                        print(f"     - {f}")
                    sys.exit(1)

            if status == "blocked":
                print(f"  ✗ Step {step_num} set itself to blocked. Append a blocking-fix step to index.json and re-run.")
                sys.exit(1)

            if iteration == loop_cfg.max_iterations:
                print(f"  ✗ Step {step_num} failed after {loop_cfg.max_iterations} {loop_cfg.label} iteration(s).")
                sys.exit(1)

            def _reflect_invoker(reflect_prompt: str) -> str:
                r = self._backend.invoke(reflect_prompt, cwd=self._root, timeout=300)
                return r.stdout or r.stderr

            iter_context = build_iter_context(
                loop_cfg,
                result_stdout=result.stdout,
                result_stderr=result.stderr,
                result_exit_code=result.exit_code,
                iteration=iteration,
                reflect_invoker=_reflect_invoker if loop_cfg.type == "reflect" else None,
                changed_files=changed_files,
                ac_failures=ac_failures,
            )

    def _execute_all_steps(self, guardrails: str, manifest_context: str):
        while True:
            index = self._read_json(self._index_file)
            pending = self._select_next_step(index)
            if pending is None:
                break
            self._execute_single_step(pending, guardrails, manifest_context)

    def _print_header(self):
        print(f"\n{'=' * 60}\n  Harness Step Executor (Refactored)\n  Phase: {self._phase_name}\n  Backend: {self._backend.name}\n{'=' * 60}")

    def _check_blockers(self):
        index = self._read_json(self._index_file)
        if any(s.get("status") == "error" for s in index["steps"]):
            errored = next(s for s in index["steps"] if s.get("status") == "error")
            print(f"  ✗ Phase is in error state at Step {errored['step']}.")
            sys.exit(1)

        blocked = [s for s in index["steps"] if s.get("status") == "blocked"]
        if blocked and self._pending_blocking_fix(index) is None:
            first_blocked = blocked[0]
            print(f"  ✗ Phase is blocked at Step {first_blocked['step']} and has no pending blocking-fix step.")
            sys.exit(1)

    @staticmethod
    def _pending_blocking_fix(index: dict) -> Optional[dict]:
        for s in index["steps"]:
            if s.get("status") == "pending" and s.get("kind") == "blocking-fix":
                return s
        return None

    @classmethod
    def _select_next_step(cls, index: dict) -> Optional[dict]:
        blocking_fix = cls._pending_blocking_fix(index)
        if blocking_fix is not None:
            return blocking_fix
        return next((s for s in index["steps"] if s.get("status") == "pending"), None)

    @staticmethod
    def _normalize_step_refs(value) -> List[int]:
        if value is None:
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, int)]
        return []

    def _release_blocked_steps(self, index: dict, fixer_step: dict) -> List[int]:
        if fixer_step.get("kind") != "blocking-fix":
            return []

        targets = self._normalize_step_refs(fixer_step.get("unblocks"))
        targets += self._normalize_step_refs(fixer_step.get("unblocks_step"))
        if not targets:
            return []

        released: List[int] = []
        for step in index["steps"]:
            if step.get("step") in targets and step.get("status") == "blocked":
                step["status"] = "pending"
                step["unblocked_by_step"] = fixer_step["step"]
                step.pop("blocked_by_step", None)
                released.append(step["step"])
        return released

    def _ensure_created_at(self):
        index = self._read_json(self._index_file)
        if "created_at" not in index:
            index["created_at"] = self._stamp()
            self._write_json(self._index_file, index)

    def _finalize(self):
        index = self._read_json(self._index_file)
        index["completed_at"] = self._stamp()
        self._write_json(self._index_file, index)
        baseline = self._write_phase_baseline(index)
        if baseline:
            update_project_manifest(self._phases_dir, self._phase_dir_name, baseline)
        self._update_top_index()
        _m = re.match(r'^(\d+)', self._phase_dir_name)
        _phase_num = _m.group(1) if _m else self._phase_dir_name
        tag_name = f"{self._project}-phase{_phase_num}-done"
        self._git.tag(tag_name)
        print(f"\n  ✓ Phase '{self._phase_name}' completed! (tag: {tag_name})")
        if self._auto_push:
            self._git.push(f"feat-{self._phase_name}")

    def _write_phase_baseline(self, index: dict) -> Optional[dict]:
        baseline_dir = self._phases_dir / "baselines"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baseline_dir / f"{self._phase_dir_name}.json"
        if baseline_path.exists():
            return None

        module_map_path = self._phase_dir / "module-map.json"
        module_map = {}
        if module_map_path.exists():
            try:
                module_map = self._read_json(module_map_path)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  WARN: could not read module-map for baseline: {exc}")

        source_module_map = None
        if module_map_path.exists():
            source_module_map = f"phases/{self._phase_dir_name}/module-map.json"

        _m = re.match(r'^(\d+)', self._phase_dir_name)
        _phase_num = _m.group(1) if _m else self._phase_dir_name
        baseline = {
            "schema_version": 1,
            "project": self._project,
            "phase": self._phase_dir_name,
            "phase_name": self._phase_name,
            "tag": f"{self._project}-phase{_phase_num}-done",
            "source_module_map": source_module_map,
            "modules": module_map.get("modules", []),
            "routes": [],
            "shared_contracts": module_map.get("shared_contracts", []),
            "integration_points": module_map.get("integration_points", []),
            "known_issues": [],
            "completed_steps": [
                {"step": step.get("step"), "name": step.get("name"), "summary": step.get("summary")}
                for step in index.get("steps", [])
                if step.get("status") == "completed"
            ],
            "completed_at": index.get("completed_at"),
            "written_at": self._stamp(),
        }
        self._write_json(baseline_path, baseline)
        return baseline

    def _update_top_index(self):
        top_path = self._top_index_file
        if not top_path.exists():
            return
        try:
            top_index = self._read_json(top_path)
            phases = top_index.get("phases", [])
            for item in phases:
                if item.get("dir") == self._phase_dir_name:
                    item["status"] = "completed"
                    break
            self._write_json(top_path, top_index)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  WARN: could not update top index: {exc}")
