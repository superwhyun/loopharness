from __future__ import annotations

from pathlib import Path


def resolve_project_root(
    framework_root: Path,
    explicit_root: str | None = None,
) -> Path:
    """프로젝트 루트를 반환한다.

    explicit_root가 주어지면 그 경로를 사용한다.
    없으면 framework_root 자체가 프로젝트 루트다 (clone-per-project 구조).
    """
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()
    return framework_root.resolve()
