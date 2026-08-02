#!/usr/bin/env bash
# harness 스킬을 유저 레벨 스킬 디렉터리에 symlink 로 설치한다.
# 이 클론 디렉터리에서 `git pull` 만 하면 설치된 스킬도 즉시 최신화된다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/skills/harness"

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "ERROR: $SKILL_SRC/SKILL.md 를 찾을 수 없습니다. 저장소 루트에서 실행하세요." >&2
  exit 1
fi

link_skill() {
  local base="$1"
  local link="$base/harness"

  mkdir -p "$base"

  if [ -L "$link" ]; then
    if [ "$(readlink "$link")" = "$SKILL_SRC" ]; then
      echo "OK   $link (이미 연결됨)"
    else
      echo "SKIP $link (다른 경로로 이미 연결됨: $(readlink "$link")) — 직접 확인하세요."
    fi
    return
  fi

  if [ -e "$link" ]; then
    echo "SKIP $link (심볼릭 링크가 아닌 기존 파일/디렉터리가 있음) — 직접 확인하세요."
    return
  fi

  ln -s "$SKILL_SRC" "$link"
  echo "OK   $link -> $SKILL_SRC"
}

link_skill "$HOME/.claude/skills"
link_skill "$HOME/.kimi/skills"

cat <<EOF

설치 완료. 이제 어떤 프로젝트 디렉터리에서 열어도 harness 스킬이 자동 로드됩니다.
업데이트: $SCRIPT_DIR 에서 'git pull' 실행 (심볼릭 링크라 재설치 불필요).
EOF
