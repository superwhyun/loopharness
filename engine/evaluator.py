"""Evaluator: phase 결과 → done / continue / stagnated 판정."""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .backends.base import AgentBackend


@dataclass
class EvalResult:
    status: str                    # "done" | "continue" | "stagnated"
    reason: str
    suggestions: list[str] = field(default_factory=list)


_SYSTEM = """당신은 소프트웨어 프로젝트 품질 평가자입니다.
주어진 목표, 성공 기준, 현재 프로젝트 상태를 종합하여 아래 형식으로만 응답하세요.

<evaluation status="done|continue|stagnated">
<reason>판정 이유 한 줄</reason>
<suggestions>
- 다음에 해야 할 것 또는 개선 방향
</suggestions>
</evaluation>

status 기준:
- done: 모든 성공 기준을 충족했다
- continue: 아직 부족하지만 진전이 있다, 계속해야 한다
- stagnated: 최근 phase에서 실질적인 진전이 없었다 (같은 문제 반복, 파일 변화 없음 등)
"""


class Evaluator:
    def __init__(self, backend: AgentBackend, project_root: Path):
        self._backend = backend
        self._root = project_root

    def evaluate(self, goal: dict, project_state: str) -> EvalResult:
        auto_section, all_checks_passed = self._run_auto_checks(goal)
        prompt = self._build_prompt(goal, project_state, auto_section)
        text = self._backend.query(prompt, cwd=str(self._root), timeout=180)
        result = self._parse(text)

        # auto_checks가 하나라도 있는데 전부 실패하면 done 차단
        if result.status == "done" and not all_checks_passed and goal.get("auto_checks"):
            result = EvalResult(
                status="continue",
                reason=f"auto_checks 실패로 done 차단 — {result.reason}",
                suggestions=result.suggestions,
            )

        return result

    def _run_auto_checks(self, goal: dict) -> tuple[str, bool]:
        """자동 검증 실행. (섹션 텍스트, 전체 통과 여부) 반환."""
        checks = goal.get("auto_checks", [])
        if not checks:
            return "", True

        lines = ["## 자동 검증 결과"]
        all_passed = True
        for cmd in checks:
            try:
                res = subprocess.run(
                    cmd, shell=True, cwd=self._root,
                    capture_output=True, text=True, timeout=60,
                )
                icon = "✓" if res.returncode == 0 else "✗"
                if res.returncode != 0:
                    all_passed = False
                lines.append(f"- `{cmd}`: {icon}")
                if res.returncode != 0 and (res.stdout or res.stderr):
                    output = (res.stdout or res.stderr).strip()[:300]
                    lines.append(f"  ```\n  {output}\n  ```")
            except Exception as exc:  # noqa: BLE001
                all_passed = False
                lines.append(f"- `{cmd}`: 오류 — {exc}")
        return "\n".join(lines) + "\n\n", all_passed

    def _build_prompt(self, goal: dict, project_state: str, auto_section: str) -> str:
        criteria = "\n".join(f"- {c}" for c in goal.get("success_criteria", []))
        return (
            f"{_SYSTEM}\n\n"
            f"## 목표\n{goal['goal']}\n\n"
            f"## 성공 기준\n{criteria}\n\n"
            f"{auto_section}"
            f"## 현재 프로젝트 상태\n{project_state}\n\n"
            "위 내용을 종합하여 평가하세요."
        )

    @staticmethod
    def _parse(text: str) -> EvalResult:
        m = re.search(
            r'<evaluation\s+status="([^"]+)">(.*?)</evaluation>',
            text, re.DOTALL,
        )
        if not m:
            return EvalResult(status="continue", reason="응답 파싱 실패 — 계속 진행")

        status = m.group(1).strip()
        body = m.group(2)

        reason_m = re.search(r'<reason>(.*?)</reason>', body, re.DOTALL)
        reason = reason_m.group(1).strip() if reason_m else ""

        suggestions: list[str] = []
        sugg_m = re.search(r'<suggestions>(.*?)</suggestions>', body, re.DOTALL)
        if sugg_m:
            for line in sugg_m.group(1).splitlines():
                line = line.strip().lstrip("- ").strip()
                if line:
                    suggestions.append(line)

        return EvalResult(status=status, reason=reason, suggestions=suggestions)
