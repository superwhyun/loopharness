"""LoopController: Plan → Execute → Evaluate 자율 루프 오케스트레이터."""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .backends.base import AgentBackend
from .evaluator import EvalResult, Evaluator
from .planner import Planner
from .prompt_builder import PromptBuilder


TZ = timezone(timedelta(hours=9))
_STOP_FILE = "STOP"
_STATE_FILE = "loop-state.json"


class LoopController:
    def __init__(
        self,
        project_root: Path,
        framework_root: Path,
        backend: AgentBackend,
        goal: dict,
        *,
        max_phases: int = 10,
        stagnation_limit: int = 3,
        auto_push: bool = False,
    ):
        self._root = project_root
        self._framework_root = framework_root
        self._backend = backend
        self._goal = goal
        self._max_phases = goal.get("max_phases", max_phases)
        self._stagnation_limit = goal.get("stagnation_limit", stagnation_limit)
        self._recovery_limit = goal.get("recovery_limit", 3)
        self._auto_push = auto_push
        self._phases_dir = project_root / "phases"
        self._phases_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._print_header()
        self._ensure_git_repo()

        state = self._load_state()
        planner = Planner(self._backend, self._phases_dir)
        evaluator = Evaluator(self._backend, self._root)

        while True:
            if self._should_stop(state):
                break

            print(f"\n[Loop {state['iterations'] + 1}/{self._max_phases}]")

            # 1. 다음 phase 결정
            phase_dir_name = self._next_pending_phase()
            if phase_dir_name is None:
                print("  → Planner: 다음 phase 설계 중...")
                state_summary = self._build_state_summary()
                phase_dir_name = planner.plan_next_phase(self._goal, state_summary)
                if phase_dir_name is None:
                    print("  ✗ Planner가 phase를 생성하지 못했습니다 — 루프 종료")
                    break
                print(f"  → 새 phase 생성: {phase_dir_name}")

            # 2. Executor로 phase 실행 (blocked step은 blocking-fix로 자동 복구)
            print(f"  → Executor: {phase_dir_name} 실행 중...")
            recovery_count = 0
            success = False
            while not success:
                success = self._run_phase(phase_dir_name)
                if success:
                    break
                if not self._recover_if_blocked(phase_dir_name, planner):
                    print("  ✗ Executor 실패 & 복구 불가 — 루프 종료")
                    break
                recovery_count += 1
                if recovery_count >= self._recovery_limit:
                    print(f"  ✗ {self._recovery_limit}회 복구 시도에도 실패 — 루프 종료")
                    break
                print(f"  → blocking-fix 추가 후 재시도 ({recovery_count}/{self._recovery_limit})")
            state["iterations"] += 1

            if not success:
                print("  ✗ Executor 실패 — 루프 종료")
                self._save_state(state)
                break

            # 3. Evaluator로 결과 평가
            print("  → Evaluator: 결과 평가 중...")
            state_summary = self._build_state_summary()
            eval_result = evaluator.evaluate(self._goal, state_summary)
            print(f"  → 판정: [{eval_result.status}] {eval_result.reason}")
            if eval_result.suggestions:
                for s in eval_result.suggestions:
                    print(f"     • {s}")

            self._record(state, phase_dir_name, eval_result)
            self._save_state(state)

            if eval_result.status == "done":
                print("\n  ✓ 목표 달성! 루프 종료")
                break

            if eval_result.status == "stagnated":
                state["stagnation_count"] += 1
                print(f"  ⚠ 정체 감지 ({state['stagnation_count']}/{self._stagnation_limit})")
            else:
                state["stagnation_count"] = 0

        self._print_summary(state)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_stop(self, state: dict) -> bool:
        stop_path = self._phases_dir / _STOP_FILE
        if stop_path.exists():
            print("  STOP 파일 감지 — 루프 종료")
            return True
        if state["iterations"] >= self._max_phases:
            print(f"  최대 phase 수({self._max_phases}) 도달 — 루프 종료")
            return True
        if state["stagnation_count"] >= self._stagnation_limit:
            print(f"  {self._stagnation_limit}회 연속 정체 — 루프 종료")
            return True
        return False

    def _ensure_git_repo(self) -> None:
        git_dir = self._root / ".git"
        if not git_dir.exists():
            print("  git repo 없음 — git init 실행")
            subprocess.run(["git", "init"], cwd=self._root, capture_output=True)
            gitignore = self._root / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "node_modules/\n.venv/\n__pycache__/\n*.pyc\n"
                    "dist/\nbuild/\n.env\n.DS_Store\n",
                    encoding="utf-8",
                )
                subprocess.run(
                    ["git", "add", ".gitignore"],
                    cwd=self._root, capture_output=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", "chore: init repo"],
                    cwd=self._root, capture_output=True,
                )

    def _next_pending_phase(self) -> Optional[str]:
        top_path = self._phases_dir / "index.json"
        if not top_path.exists():
            return None
        try:
            data = json.loads(top_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for phase in data.get("phases", []):
            if phase.get("status") == "pending":
                return phase["dir"]
        return None

    def _recover_if_blocked(self, phase_dir_name: str, planner: Planner) -> bool:
        """phase에 blocked step이 있으면 blocking-fix를 append하고 재실행 가능하게 한다.

        반환: 복구 경로를 만들었으면 True(재실행 가능), 아니면 False.
        """
        index_path = self._phases_dir / phase_dir_name / "index.json"
        if not index_path.exists():
            return False
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        blocked = [s for s in index.get("steps", []) if s.get("status") == "blocked"]
        if not blocked:
            return False

        if planner._pending_blocking_fix(index) is None:
            planner.append_blocking_fix(phase_dir_name, blocked[0])
        print(f"  → 블록된 step {blocked[0]['step']} 복구를 위해 blocking-fix 배치")
        return True

    def _run_phase(self, phase_dir_name: str) -> bool:
        # 지연 import — executor가 sys.exit 를 호출할 수 있으므로 catch
        from .executor import StepExecutor  # noqa: PLC0415

        try:
            executor = StepExecutor(
                self._root,
                phase_dir_name,
                backend_name=self._backend.name,
                auto_push=self._auto_push,
                framework_root=self._framework_root,
            )
            executor.run()
            return True
        except SystemExit as exc:
            return exc.code == 0

    def _build_state_summary(self) -> str:
        pb = PromptBuilder()
        manifest = pb.load_project_manifest(self._phases_dir)

        top_path = self._phases_dir / "index.json"
        if not top_path.exists():
            return manifest or "프로젝트 시작 전"

        try:
            data = json.loads(top_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return manifest or ""

        lines = ["### Phase 현황"]
        for p in data.get("phases", []):
            icon = "✓" if p.get("status") == "completed" else "…"
            desc = p.get("description", "")
            lines.append(f"  {icon} {p.get('dir')} — {desc}")

        return (manifest or "") + "\n".join(lines)

    def _load_state(self) -> dict:
        state_path = self._phases_dir / _STATE_FILE
        if state_path.exists():
            try:
                return json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"iterations": 0, "stagnation_count": 0, "history": []}

    def _save_state(self, state: dict) -> None:
        (self._phases_dir / _STATE_FILE).write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _record(state: dict, phase_dir: str, result: EvalResult) -> None:
        state.setdefault("history", []).append(
            {
                "phase": phase_dir,
                "eval": result.status,
                "reason": result.reason,
                "suggestions": result.suggestions,
                "at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )

    def _print_header(self) -> None:
        print(f"\n{'=' * 60}")
        print(f"  Loop Harness — 자율 개발 루프")
        print(f"  목표: {self._goal['goal']}")
        print(f"  최대 phase: {self._max_phases} | 정체 한도: {self._stagnation_limit}")
        print(f"  중단하려면: phases/STOP 파일 생성")
        print(f"{'=' * 60}")

    @staticmethod
    def _print_summary(state: dict) -> None:
        print(f"\n{'=' * 60}")
        print(f"  총 실행 phase: {state['iterations']}")
        history = state.get("history", [])
        if history:
            print("  이력:")
            for h in history:
                print(f"    [{h['eval']:>10}] {h['phase']} — {h['reason']}")
        print(f"{'=' * 60}")
