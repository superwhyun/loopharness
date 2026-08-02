"""GoalBuilder: 사용자와 대화하며 goal.json을 만든다.

LocalAPIBackend → 진짜 멀티턴 chat (messages 히스토리 전달)
GenericCommandBackend → 히스토리를 프롬프트에 평문으로 포함
"""

import json
import re
from pathlib import Path
from typing import Optional

from .backends.base import AgentBackend
from .backends.local_llm import LocalAPIBackend


_SYSTEM = """당신은 소프트웨어 개발 목표를 정의해 주는 어시스턴트입니다.
사용자와 자연스러운 대화를 나누며 아래 정보를 파악하세요.

1. goal — 무엇을 만들 것인가 (한 문장)
2. success_criteria — 언제 "완성"이라고 할 수 있는가 (체크리스트)
3. auto_checks — 자동으로 실행할 수 있는 검증 명령 (예: pytest, curl)
4. max_phases — 최대 개발 사이클 수 (기본 10)
5. stagnation_limit — 연속 정체 허용 횟수 (기본 3)

정보가 충분히 모이면 아래 형식으로 초안을 제시하세요:

<goal_draft>
{
  "goal": "...",
  "success_criteria": ["...", "..."],
  "auto_checks": ["..."],
  "max_phases": 10,
  "stagnation_limit": 3
}
</goal_draft>

초안을 보여준 뒤 수정 사항이 있으면 반영하고, 사용자가 확인하면 대화를 마칩니다.
질문은 한 번에 하나만 하고, 간결하게 유지하세요.
"""

_CONFIRM_WORDS = {"응", "네", "예", "ㅇ", "ok", "yes", "y", "좋아", "저장", "확인", "맞아"}


class GoalBuilder:
    def __init__(self, backend: AgentBackend, project_root: Path):
        self._backend = backend
        self._root = project_root
        self._is_local = isinstance(backend, LocalAPIBackend)
        # LocalAPIBackend: messages 리스트 유지
        # GenericCommandBackend: 평문 히스토리 유지
        self._messages: list[dict] = []
        self._flat_history: list[str] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> Optional[dict]:
        """대화를 진행해 goal dict를 반환. 취소 시 None."""
        print("\n" + "=" * 50)
        print("  목표 설정 대화를 시작합니다.")
        print("  종료: Ctrl+C")
        print("=" * 50 + "\n")

        # 첫 질문을 AI가 먼저 시작
        first = self._ask_ai("사용자가 새 프로젝트를 시작하려 합니다. 첫 질문을 해주세요.")
        print(f"AI: {first}\n")

        while True:
            try:
                user_input = input("나: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n취소됨")
                return None

            if not user_input:
                continue

            response = self._ask_ai(user_input, user_turn=True)
            print(f"\nAI: {response}\n")

            draft = self._extract_draft(response)
            if draft is None:
                continue

            # 초안이 나왔을 때 사용자 확인
            try:
                confirm = input("나: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n취소됨")
                return None

            if self._is_confirmed(confirm):
                self._save(draft)
                print(f"\n✓ goal.json 저장: {self._root / 'goal.json'}\n")
                return draft

            # 거절 → 수정 요청 대화 계속
            follow = self._ask_ai(confirm, user_turn=True)
            print(f"\nAI: {follow}\n")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ask_ai(self, content: str, *, user_turn: bool = False) -> str:
        if self._is_local:
            return self._ask_local(content, user_turn=user_turn)
        return self._ask_cli(content, user_turn=user_turn)

    def _ask_local(self, content: str, *, user_turn: bool) -> str:
        """LocalAPIBackend: 실제 멀티턴 messages 전달."""
        backend: LocalAPIBackend = self._backend  # type: ignore[assignment]
        if user_turn:
            self._messages.append({"role": "user", "content": content})
        else:
            # AI가 먼저 시작하는 경우 — system 지시로 처리
            self._messages.append({"role": "user", "content": content})

        messages = [{"role": "system", "content": _SYSTEM}] + self._messages
        text, err = backend.chat(messages, timeout=60)
        if err or not text:
            text = "(응답 없음)"
        self._messages.append({"role": "assistant", "content": text})
        return text

    def _ask_cli(self, content: str, *, user_turn: bool) -> str:
        """GenericCommandBackend: 히스토리를 평문으로 프롬프트에 포함."""
        if user_turn:
            self._flat_history.append(f"사용자: {content}")

        prompt = _SYSTEM + "\n\n" + "\n".join(self._flat_history) + "\nAI:"
        result = self._backend.invoke(prompt, cwd=str(self._root), timeout=60)
        text = (result.stdout or result.stderr).strip() or "(응답 없음)"
        self._flat_history.append(f"AI: {text}")
        return text

    @staticmethod
    def _extract_draft(text: str) -> Optional[dict]:
        m = re.search(r'<goal_draft>(.*?)</goal_draft>', text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _is_confirmed(text: str) -> bool:
        return any(w in text.lower() for w in _CONFIRM_WORDS)

    def _save(self, goal: dict) -> None:
        path = self._root / "goal.json"
        path.write_text(json.dumps(goal, indent=2, ensure_ascii=False), encoding="utf-8")
