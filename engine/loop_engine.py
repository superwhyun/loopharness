from dataclasses import dataclass
from typing import Optional


@dataclass
class LoopConfig:
    """step 하나의 반복 전략."""
    type: str = "retry"        # retry | reflect | fixed
    max_iterations: int = 3
    eval_prompt_suffix: str = ""  # reflect 타입에서 자기 반성 프롬프트 추가 지시

    @classmethod
    def from_step(cls, step: dict, default_max: int = 3) -> "LoopConfig":
        raw = step.get("loop", {})
        if not raw:
            return cls(max_iterations=default_max)
        return cls(
            type=raw.get("type", "retry"),
            max_iterations=max(1, int(raw.get("max_iterations", default_max))),
            eval_prompt_suffix=raw.get("eval_prompt_suffix", ""),
        )

    @property
    def label(self) -> str:
        labels = {"retry": "retry", "reflect": "reflect", "fixed": "iter"}
        return labels.get(self.type, self.type)


def _format_enrichment(ac_failures, changed_files) -> list[str]:
    """재작성을 '결함 지점'으로 유도하기 위한 구조화 피드백 블록."""
    parts = []
    if ac_failures:
        lines = ["### 통과하지 못한 Acceptance Criteria / 검증 명령"]
        lines += [f"- {f}" for f in ac_failures]
        parts.append("\n".join(lines))
    if changed_files:
        lines = ["### 이전 시도에서 변경/추가된 파일"]
        lines += [f"- {p}" for p in changed_files]
        parts.append("\n".join(lines))
    return parts


def build_iter_context(
    loop_cfg: LoopConfig,
    result_stdout: str,
    result_stderr: str,
    result_exit_code: int,
    iteration: int,
    *,
    reflect_invoker=None,
    changed_files: Optional[list[str]] = None,
    ac_failures: Optional[list[str]] = None,
) -> Optional[str]:
    """다음 반복에 주입할 컨텍스트 문자열을 반환한다.

    Args:
        reflect_invoker: reflect 타입에서 자기 반성 프롬프트를 실행하는 callable.
                         signature: (prompt: str) -> str (반성 텍스트)
        changed_files: 이전 시도에서 실제로 변경된 파일 경로 목록.
                       재작성이 처음부터 다시 생성하지 않고 이전 작업 위에서
                       결함만 고치도록 유도하는 핵심 신호다.
        ac_failures: 실행해 본 결과 실패한 AC/검증 명령 설명 목록.
    """
    enrichment = _format_enrichment(ac_failures, changed_files)

    if loop_cfg.type == "fixed":
        prev = (result_stdout or result_stderr).strip()[:800]
        parts = list(enrichment)
        if prev:
            parts.append(f"### 이전 반복 {iteration} 출력\n{prev}")
        return "\n\n".join(parts) if parts else None

    if loop_cfg.type == "reflect":
        prev = (result_stdout or result_stderr).strip()[:800]
        reflection = ""
        suffix = loop_cfg.eval_prompt_suffix or "구현을 검토하고 개선해야 할 점을 찾아라."
        if reflect_invoker and prev:
            reflect_prompt = (
                f"아래는 이전 구현 시도의 출력이다. {suffix}\n\n"
                f"### 이전 출력\n{prev}"
            )
            try:
                reflection = reflect_invoker(reflect_prompt)[:500]
            except Exception:
                pass
        parts = list(enrichment)
        if prev:
            parts.append(f"### 이전 출력\n{prev}")
        if reflection:
            parts.append(f"### 자기 반성\n{reflection}")
        return "## 이전 시도 컨텍스트\n\n" + "\n\n".join(parts) if parts else None

    # retry (default) — 기존 호출과의 호환성을 위해, AC 실패/변경 파일이
    # 전달되지 않았을 때는 기존의 단순 출력 반환 동작을 유지한다.
    err = result_stderr.strip()[:500]
    out = result_stdout.strip()[:500]
    if enrichment:
        block = "\n\n".join(enrichment)
        if err:
            block += "\n\n### 오류 출력\n" + err
        elif out:
            block += "\n\n### 표준 출력\n" + out
        return block
    if err:
        return err
    if out:
        return out
    return f"반복 {iteration}: step이 완료 상태로 기록되지 않았습니다 (exit {result_exit_code})."
