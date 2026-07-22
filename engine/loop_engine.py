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


def build_iter_context(
    loop_cfg: LoopConfig,
    result_stdout: str,
    result_stderr: str,
    result_exit_code: int,
    iteration: int,
    *,
    reflect_invoker=None,
) -> Optional[str]:
    """다음 반복에 주입할 컨텍스트 문자열을 반환한다.

    Args:
        reflect_invoker: reflect 타입에서 자기 반성 프롬프트를 실행하는 callable.
                         signature: (prompt: str) -> str (반성 텍스트)
    """
    if loop_cfg.type == "fixed":
        prev = (result_stdout or result_stderr).strip()[:800]
        return f"## 이전 반복 {iteration} 출력\n\n{prev}" if prev else None

    if loop_cfg.type == "reflect":
        prev = (result_stdout or result_stderr).strip()[:800]
        reflection = ""
        if reflect_invoker and prev:
            suffix = loop_cfg.eval_prompt_suffix or "구현을 검토하고 개선해야 할 점을 찾아라."
            reflect_prompt = (
                f"아래는 이전 구현 시도의 출력이다. {suffix}\n\n"
                f"### 이전 출력\n{prev}"
            )
            try:
                reflection = reflect_invoker(reflect_prompt)[:500]
            except Exception:
                pass
        parts = []
        if prev:
            parts.append(f"### 이전 출력\n{prev}")
        if reflection:
            parts.append(f"### 자기 반성\n{reflection}")
        return "## 이전 시도 컨텍스트\n\n" + "\n\n".join(parts) if parts else None

    # retry (default)
    err = result_stderr.strip()[:500]
    out = result_stdout.strip()[:500]
    if err:
        return err
    if out:
        return out
    return f"반복 {iteration}: step이 완료 상태로 기록되지 않았습니다 (exit {result_exit_code})."
