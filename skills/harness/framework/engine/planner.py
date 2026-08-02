"""Planner: goal + 현재 상태 → 다음 phase 설계 + stepN.md 자동 생성."""

import json
import re
from pathlib import Path
from typing import Optional

from .backends.base import AgentBackend


_SYSTEM = """당신은 Harness 프레임워크 프로젝트 플래너입니다.
주어진 목표와 현재 프로젝트 상태를 바탕으로 다음 phase를 설계합니다.

응답은 반드시 아래 XML 형식으로만 작성하세요 (태그 밖 설명 최소화):

<phase_plan dir="{N}-{slug}" name="{phase-name}" description="{한 줄 설명}">
<step num="0" name="{step-name}" summary="{한 줄 요약}">
# Step 0: {step-name}

## 목표
...

## 작업 범위
- owned_paths: [파일 또는 디렉터리 목록]
- read_contracts: [읽어야 할 계약/인터페이스]
- forbidden_paths: [수정 금지 경로]

## Acceptance Criteria
- [ ] 실행 가능한 검증 명령 또는 조건
</step>
<step num="1" name="{step-name}" summary="{한 줄 요약}">
...
</step>
</phase_plan>

규칙:
- dir 값은 숫자-슬러그 형식 (예: 0-setup, 1-core-api)
- step은 최소 1개, 최대 6개
- 이미 완료된 phase와 중복되는 작업은 설계하지 않는다
- step 0은 가능하면 module-map.json과 public contract 초안을 만든다
"""

_REVIEW_QUESTIONS = (
    "빠진 것 없어? 누락된 요구사항, 엣지 케이스, 모듈/의존성이 없는지 점검하고 채워라.",
    "완벽한 것 같아? AC가 측정 가능한 명령으로 구체화됐는지, owned_paths/read_contracts/forbidden_paths가 정합적인지 점검하고 다듬어라.",
    "이대로 구현 바로 하면 돼? 독립 세션에서도 바로 실행 가능한지, 검증 절차와 범위가 실행 가능한 수준인지 최종 점검하라.",
)


class Planner:
    def __init__(self, backend: AgentBackend, phases_dir: Path, review_count: int = 3):
        self._backend = backend
        self._phases_dir = phases_dir
        self._review_count = max(0, review_count)

    def plan_next_phase(self, goal: dict, project_state: str) -> Optional[str]:
        """초안과 자기검토를 거쳐 다음 phase를 설계하고 생성한다."""
        prompt = self._build_prompt(goal, project_state)
        text = self._backend.query(prompt, cwd=str(self._phases_dir.parent), timeout=300)
        if not self._is_valid_plan(text):
            return None

        for review_number in range(1, self._review_count + 1):
            reviewed = self._backend.query(
                self._build_review_prompt(text, review_number),
                cwd=str(self._phases_dir.parent),
                timeout=300,
            )
            if self._is_valid_plan(reviewed):
                text = reviewed

        return self._apply_plan(text)

    def _build_prompt(self, goal: dict, project_state: str) -> str:
        criteria = "\n".join(f"- {c}" for c in goal.get("success_criteria", []))
        return (
            f"{_SYSTEM}\n\n"
            f"## 목표\n{goal['goal']}\n\n"
            f"## 성공 기준\n{criteria}\n\n"
            f"## 현재 프로젝트 상태\n{project_state}\n\n"
            "위 상태를 바탕으로 목표 달성에 필요한 **다음 한 개의 phase**를 설계하세요."
        )

    def _build_review_prompt(self, plan: str, review_number: int) -> str:
        question = _REVIEW_QUESTIONS[(review_number - 1) % len(_REVIEW_QUESTIONS)]
        return (
            f"당신이 만든 아래 phase/step 설계 초안을 다시 검토하라. "
            f"이것은 {review_number}/{self._review_count}번째 자기검토다.\n\n"
            f"질문: {question}\n\n"
            "문제가 있으면 수정하고, 문제가 없어도 검토 결과를 반영한 완전한 계획을 다시 작성하라. "
            "설명만 하지 말고 반드시 <phase_plan>...</phase_plan> 전체를 반환하라.\n\n"
            f"## 현재 초안\n{plan}"
        )

    def _is_valid_plan(self, text: str) -> bool:
        m = re.search(
            r'<phase_plan\s+dir="([^"]+)"\s+name="([^"]+)"\s+description="([^"]*)">'
            r'(.*?)</phase_plan>',
            text, re.DOTALL,
        )
        return bool(m and self._parse_steps(m.group(4)))

    def _apply_plan(self, text: str) -> Optional[str]:
        m = re.search(
            r'<phase_plan\s+dir="([^"]+)"\s+name="([^"]+)"\s+description="([^"]*)">'
            r'(.*?)</phase_plan>',
            text, re.DOTALL,
        )
        if not m:
            return None

        phase_dir_name = m.group(1)
        phase_name = m.group(2)
        description = m.group(3)
        steps = self._parse_steps(m.group(4))
        if not steps:
            return None

        phase_dir = self._phases_dir / phase_dir_name
        if (phase_dir / "index.json").exists():
            print(f"  WARN: phase '{phase_dir_name}' 이미 존재합니다 — 생성 건너뜀")
            return phase_dir_name
        phase_dir.mkdir(parents=True, exist_ok=True)

        project_name = self._phases_dir.parent.name
        index = {
            "project": project_name,
            "phase": phase_name,
            "description": description,
            "steps": [
                {
                    "step": s["num"],
                    "name": s["name"],
                    "summary": s["summary"],
                    "status": "pending",
                }
                for s in steps
            ],
        }
        (phase_dir / "index.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        for s in steps:
            (phase_dir / f"step{s['num']}.md").write_text(
                s["content"], encoding="utf-8"
            )

        self._register_phase(phase_dir_name, phase_name, description)
        return phase_dir_name

    @staticmethod
    def _parse_steps(text: str) -> list[dict]:
        steps = []
        for m in re.finditer(
            r'<step\s+num="(\d+)"\s+name="([^"]+)"\s+summary="([^"]*)">(.*?)</step>',
            text, re.DOTALL,
        ):
            steps.append(
                {
                    "num": int(m.group(1)),
                    "name": m.group(2),
                    "summary": m.group(3),
                    "content": m.group(4).strip(),
                }
            )
        return steps

    def _register_phase(self, dir_name: str, name: str, description: str) -> None:
        top_path = self._phases_dir / "index.json"
        data: dict = {"phases": []}
        if top_path.exists():
            try:
                data = json.loads(top_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        phases = data.setdefault("phases", [])
        if not any(p.get("dir") == dir_name for p in phases):
            phases.append(
                {
                    "dir": dir_name,
                    "name": name,
                    "description": description,
                    "status": "pending",
                }
            )
        top_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Blocking-fix 자동 복구
    # 배치 루프에서 step이 blocked가 되면 기존 step 번호를 재배열하지 않고
    # blocking-fix step을 append해 해소한 뒤 원 step을 재개한다.
    # ------------------------------------------------------------------

    @staticmethod
    def _pending_blocking_fix(index: dict) -> Optional[dict]:
        for s in index.get("steps", []):
            if s.get("status") == "pending" and s.get("kind") == "blocking-fix":
                return s
        return None

    def append_blocking_fix(self, phase_dir_name: str, blocked_step: dict) -> Optional[int]:
        """blocked step을 해소할 blocking-fix step을 해당 phase에 append한다.

        반환: append된 step 번호. 이미 실행 가능한 blocking-fix가 있으면 None.
        """
        index_path = self._phases_dir / phase_dir_name / "index.json"
        if not index_path.exists():
            return None
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if self._pending_blocking_fix(index) is not None:
            return None

        steps = index.setdefault("steps", [])
        next_num = max((s.get("step", -1) for s in steps), default=-1) + 1
        blocked_num = blocked_step.get("step")
        reason = (blocked_step.get("blocked_reason") or "").strip()

        steps.append({
            "step": next_num,
            "name": "blocking-fix",
            "summary": f"Resolve blocker for step {blocked_num}",
            "status": "pending",
            "kind": "blocking-fix",
            "unblocks": [blocked_num],
        })
        index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        reason_section = reason or "(blocked_reason 미기록 — 원 step의 지시서를 읽어 원인 파악)"
        step_md = (
            f"# Step {next_num}: blocking-fix — unblocks step {blocked_num}\n\n"
            f"## 목표\n\n원래 step {blocked_num}을 막는 문제를 해소한다.\n\n"
            f"## 원인\n\n{reason_section}\n\n"
            f"## 작업\n\n"
            f"1. step {blocked_num}이 재개될 수 있도록 막는 contract/모듈 문제를 해결한다.\n"
            f"2. 해결 후 `phases/{phase_dir_name}/index.json`에서 이 blocking-fix step을 `completed`로 기록한다.\n"
            "3. 커밋한다.\n\n"
            "## Acceptance Criteria\n\n"
            f"- [ ] step {blocked_num}을 다시 진행할 수 있게 되었다\n"
        )
        (self._phases_dir / phase_dir_name / f"step{next_num}.md").write_text(
            step_md, encoding="utf-8"
        )
        return next_num
