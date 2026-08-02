# Claude Supplement

이 저장소의 canonical 프로젝트 지침은 `AGENTS.md` 이다.

Claude Code에서는 아래 순서로 사용한다.

1. `AGENTS.md`
2. `skills/harness/framework/docs/HARNESS.md`
3. 필요하면 `.claude/commands/harness.md`, `.claude/commands/review.md`

대상 프로젝트에서 사용할 때는 `install.sh`로 설치된 `~/.claude/skills/harness` 스킬(`skills/harness/SKILL.md`)이 우선 진입점이다.

프로젝트 명령:

- `/harness`
- `/review`

배치 실행기 `skills/harness/framework/scripts/execute.py` 는 선택 사항이다.
기본 사용 방식은 Claude Code가 설치된 harness 스킬을 자동 로드한 상태에서 인터랙티브하게 작업하는 것이다.
