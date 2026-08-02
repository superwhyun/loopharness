from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, List, Optional

@dataclass(frozen=True)
class BackendResult:
    backend: str
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str

class AgentBackend(Protocol):
    name: str
    guardrail_files: List[str]

    def invoke(
        self,
        prompt: str,
        *,
        cwd: str,
        timeout: int,
        index_file: Optional[Path] = None,
    ) -> BackendResult:
        ...

    def query(
        self,
        prompt: str,
        *,
        cwd: str,
        timeout: int,
    ) -> str:
        """읽기 전용 LLM 호출. Planner/Evaluator 등 side-effect 없이 텍스트만 받을 때 사용."""
        ...
