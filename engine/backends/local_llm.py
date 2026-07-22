"""LocalAPIBackend: OpenAI-compatible HTTP 엔드포인트 (Ollama / LM Studio / vLLM 등)를
원격 IP로 호출하고, 구조화된 응답을 파싱해 파일 변경과 상태 업데이트를 직접 적용한다."""

import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional
import urllib.error
import urllib.request

from .base import BackendResult
from ..safety import SafetyFilter


# LLM에게 주입하는 시스템 프롬프트 — 응답 포맷을 강제한다
_SYSTEM_PROMPT = """당신은 Harness 프레임워크 개발자입니다. 주어진 step을 구현하고,
아래 XML 태그로만 변경사항을 표현하세요. 태그 밖 자연어 설명은 간결하게 유지하세요.

파일 작성/수정:
<file_write path="상대/경로/파일.py">
파일 전체 내용
</file_write>

셸 명령 실행 (선택):
<shell_run>
명령어 한 줄
</shell_run>

Step 상태 업데이트 (필수 — 반드시 마지막에):
<step_update step="N" status="completed" summary="한 줄 요약"/>

완료하지 못한 경우:
<step_update step="N" status="pending" summary="실패 이유"/>
"""


class ChangeApplicator:
    """LLM 응답 텍스트를 파싱해 파일 쓰기·셸 실행·index.json 업데이트를 적용한다."""

    _FILE_WRITE_RE = re.compile(
        r'<file_write\s+path="([^"]+)">(.*?)</file_write>', re.DOTALL
    )
    _SHELL_RUN_RE = re.compile(r'<shell_run>(.*?)</shell_run>', re.DOTALL)
    _STEP_UPDATE_RE = re.compile(
        r'<step_update\s+step="(\d+)"\s+status="([^"]+)"'
        r'(?:\s+summary="([^"]*)")?'
    )

    def __init__(self, cwd: str, index_path: Optional[Path] = None):
        self._cwd = Path(cwd).resolve()
        self._index_path = index_path

    def _safe_path(self, rel: str) -> Optional[Path]:
        """cwd 범위 밖 쓰기를 차단한다. 문제가 있으면 None 반환."""
        # 절대경로 시도 차단
        if Path(rel).is_absolute():
            return None
        target = (self._cwd / rel).resolve()
        # cwd 밖 이탈 차단 (path traversal)
        try:
            target.relative_to(self._cwd)
        except ValueError:
            return None
        # phases/ 디렉터리 보호 — SSOT이므로 LLM이 직접 쓸 수 없음
        phases = (self._cwd / "phases").resolve()
        try:
            target.relative_to(phases)
            return None  # phases/ 내부 경로
        except ValueError:
            pass
        return target

    def apply(self, text: str) -> tuple[bool, list[str], Optional[str]]:
        """Returns (completed, action_log, error_message)."""
        actions: list[str] = []

        for m in self._FILE_WRITE_RE.finditer(text):
            rel, content = m.group(1), m.group(2).lstrip("\n")
            target = self._safe_path(rel)
            if target is None:
                actions.append(f"BLOCKED 파일 쓰기 (경로 이탈 또는 보호 경로): {rel}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            actions.append(f"wrote: {rel}")

        for m in self._SHELL_RUN_RE.finditer(text):
            cmd = m.group(1).strip()
            blocked = SafetyFilter.check_command(cmd.split())
            if blocked:
                actions.append(f"BLOCKED: {cmd[:80]}")
                continue
            res = subprocess.run(
                cmd, shell=True, cwd=self._cwd,
                capture_output=True, text=True, timeout=120,
            )
            if res.returncode != 0:
                actions.append(f"shell FAILED [{res.returncode}]: {cmd[:60]}\n{res.stderr[:200]}")
            else:
                actions.append(f"ran: {cmd[:60]}")

        m = self._STEP_UPDATE_RE.search(text)
        if not m:
            return False, actions, "<step_update> 태그가 응답에 없습니다."

        step_num, status, summary = int(m.group(1)), m.group(2), m.group(3) or ""
        if self._index_path and self._index_path.exists():
            self._update_index(self._index_path, step_num, status, summary)
            actions.append(f"step {step_num} → {status}")

        return status == "completed", actions, None

    @staticmethod
    def _update_index(index_path: Path, step_num: int, status: str, summary: str) -> None:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        for step in data.get("steps", []):
            if step.get("step") == step_num:
                step["status"] = status
                if summary:
                    step["summary"] = summary
                break
        index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class LocalAPIBackend:
    """OpenAI-compatible HTTP 엔드포인트를 호출하는 백엔드.

    config.json 설정 예시::

        "my-llm": {
            "type": "local_api",
            "endpoint": "http://192.168.0.10:11434/v1/chat/completions",
            "model": "qwen2.5-coder:32b",
            "api_key": "local",
            "temperature": 0.1,
            "max_tokens": 8192,
            "guardrail_files": []
        }
    """

    def __init__(
        self,
        name: str,
        endpoint: str,
        model: str,
        guardrail_files: List[str],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8192,
        api_key: str = "local",
    ):
        self.name = name
        self.guardrail_files = guardrail_files
        self._endpoint = endpoint
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._api_key = api_key

    # ------------------------------------------------------------------
    # AgentBackend protocol
    # ------------------------------------------------------------------

    def invoke(
        self,
        prompt: str,
        *,
        cwd: str,
        timeout: int,
        index_file: Optional[Path] = None,
    ) -> BackendResult:
        content, err = self._call_api(prompt, timeout)
        if err:
            return BackendResult(
                backend=self.name, command=[self._endpoint],
                exit_code=1, stdout="", stderr=err,
            )

        applicator = ChangeApplicator(cwd, index_file)
        completed, actions, apply_err = applicator.apply(content)

        failed_actions = [a for a in actions if "FAILED" in a or "BLOCKED" in a]
        stderr_parts = failed_actions[:]
        if apply_err:
            stderr_parts.append(apply_err)

        return BackendResult(
            backend=self.name,
            command=[self._endpoint],
            exit_code=0 if completed else 1,
            stdout=content,
            stderr="\n".join(stderr_parts),
        )

    def query(self, prompt: str, *, cwd: str, timeout: int) -> str:
        """ChangeApplicator 없이 LLM 텍스트 응답만 반환. Planner/Evaluator 전용."""
        content, _err = self._call_api(prompt, timeout)
        return content

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def chat(self, messages: List[dict], *, timeout: int = 60) -> tuple[str, Optional[str]]:
        """멀티턴 대화용: 미리 구성한 messages 리스트를 그대로 전송한다."""
        return self._call_api_with_messages(messages, timeout)

    def _call_api(self, prompt: str, timeout: int) -> tuple[str, Optional[str]]:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        return self._call_api_with_messages(messages, timeout)

    def _call_api_with_messages(
        self, messages: List[dict], timeout: int
    ) -> tuple[str, Optional[str]]:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return "", f"HTTP 오류: {exc}"
        except TimeoutError:
            return "", f"타임아웃 ({timeout}s)"
        except Exception as exc:  # noqa: BLE001
            return "", f"예외: {exc}"

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            snippet = str(data)[:300]
            return "", f"응답 파싱 오류: {exc} — {snippet}"

        return content, None
