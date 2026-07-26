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
    "빠진 요구사항, 사용자 흐름, 예외 상황은 없는가?",
    "확실한가? 목표와 성공 기준을 모두 충족하도록 phase와 step이 나뉘어 있는가?",
    "완전히 고려했는가? 모듈 경계, public contract, 의존성, 기존 baseline과의 연결을 다시 점검하라.",
    "각 step의 owned_paths와 금지 경로가 겹치지 않고, Acceptance Criteria가 실제로 검증 가능한가?",
    "범위가 과도하거나 누락된 부분은 없는가? 다음 세션의 에이전트가 이 계획만으로 안전하게 이어갈 수 있는가?",
)


class Planner:
    def __init__(self, backend: AgentBackend, phases_dir: Path, review_count: int = 5):
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
