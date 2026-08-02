#!/usr/bin/env python3
"""Loop Harness — 자율 개발 루프 진입점.

사용법:
    python3 scripts/loop.py --backend my-llm
    python3 scripts/loop.py --goal goal.json --backend claude --max-phases 5
    python3 scripts/loop.py --root projects/my-project --backend my-llm

중단:
    phases/STOP 파일을 생성하면 현재 phase 완료 후 루프가 종료됩니다.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from engine.executor import StepExecutor
from engine.goal_builder import GoalBuilder
from engine.loop_controller import LoopController
from engine.project_context import resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Loop Harness — 자율 개발 루프",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--goal", default="goal.json", help="목표 명세 파일 (기본: goal.json)")
    parser.add_argument("--root", help="대상 프로젝트 루트 (기본: repo 루트)")
    parser.add_argument("--backend", help="사용할 백엔드 이름 (config.json 참조)")
    parser.add_argument("--max-phases", type=int, default=10, help="최대 phase 수 (기본: 10)")
    parser.add_argument("--push", action="store_true", help="각 phase 완료 후 git push")
    args = parser.parse_args()

    # 대상 프로젝트 결정
    try:
        project_root = resolve_project_root(ROOT, args.root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # backend 인스턴스 생성 (goal 대화에도 필요하므로 먼저)
    try:
        backend = StepExecutor.build_backend(project_root, ROOT, args.backend)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # goal.json 로드 — 없으면 대화로 생성
    goal_path = project_root / args.goal
    if not goal_path.exists():
        print(f"  goal.json 없음 — 목표 설정 대화를 시작합니다.")
        builder = GoalBuilder(backend, project_root)
        goal = builder.run()
        if goal is None:
            print("목표 설정이 취소됐습니다.", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            goal = json.loads(goal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: goal.json 파싱 실패 — {exc}", file=sys.stderr)
            sys.exit(1)

    # 루프 실행
    controller = LoopController(
        project_root=project_root,
        framework_root=ROOT,
        backend=backend,
        goal=goal,
        max_phases=args.max_phases,
        auto_push=args.push,
    )
    controller.run()


if __name__ == "__main__":
    main()
