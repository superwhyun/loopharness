#!/usr/bin/env bash
# harness 스킬을 ~/.agents/skills/harness 에 설치(symlink)하고,
# 각 툴의 스킬 디렉터리(~/.claude, ~/.kimi, ~/.codex)에서 그곳으로 다시 symlink 한다.
# 이 클론 디렉터리에서 `git pull` 만 하면 설치된 스킬도 즉시 최신화된다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/skills/harness"
AGENTS_BASE="$HOME/.agents/skills/harness"
TOOLS=(claude kimi codex)

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "ERROR: $SKILL_SRC/SKILL.md 를 찾을 수 없습니다. 저장소 루트에서 실행하세요." >&2
  exit 1
fi

# link <link_path> <target>
# target 은 실제 symlink 대상이자, readlink 비교에도 그대로 쓰인다
# (호출부에서 항상 ln에 넘길 문자열과 동일한 문자열을 넘긴다).
link() {
  local link_path="$1"
  local target="$2"

  mkdir -p "$(dirname "$link_path")"

  if [ -L "$link_path" ]; then
    if [ "$(readlink "$link_path")" = "$target" ]; then
      echo "OK   $link_path (이미 연결됨)"
    else
      echo "SKIP $link_path (다른 경로로 이미 연결됨: $(readlink "$link_path")) — 직접 확인하세요."
    fi
    return
  fi

  if [ -e "$link_path" ]; then
    echo "SKIP $link_path (심볼릭 링크가 아닌 기존 파일/디렉터리가 있음) — 직접 확인하세요."
    return
  fi

  ln -s "$target" "$link_path"
  echo "OK   $link_path -> $target"
}

# 1) ~/.agents/skills/harness -> 이 클론의 skills/harness (실제 원본)
link "$AGENTS_BASE" "$SKILL_SRC"

# 2) 각 툴의 skills/harness -> ../../.agents/skills/harness (상대경로, 기존 컨벤션과 동일)
for tool in "${TOOLS[@]}"; do
  link "$HOME/.$tool/skills/harness" "../../.agents/skills/harness"
done

cat <<EOF

설치 완료. 이제 어떤 프로젝트 디렉터리에서 열어도 harness 스킬이 자동 로드됩니다.
  실제 원본:  $AGENTS_BASE -> $SKILL_SRC
  툴별 링크:  ~/.claude/skills/harness, ~/.kimi/skills/harness, ~/.codex/skills/harness

업데이트: $SCRIPT_DIR 에서 'git pull' 실행 (심볼릭 링크라 재설치 불필요).
EOF
