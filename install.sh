#!/usr/bin/env bash
# 각 AI 에이전트 툴(claude/kimi/codex/agy)의 skills/harness 를 이 클론의
# skills/harness/ 로 심볼릭 링크한다. 권장 clone 위치는 ~/.agents/skills/harness.
# git pull 만 하면 설치된 스킬도 즉시 최신화된다 (symlink라 재설치 불필요).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/skills/harness"
TOOLS=(claude kimi codex)
# Antigravity(agy/AGY CLI/AGY IDE)는 ~/.<tool>/skills/ 컨벤션이 아니라
# ~/.gemini/config/skills/ 를 전역 스킬 경로로 공통 인식한다 (실측 확인됨).
AGY_SKILLS_DIR="$HOME/.gemini/config/skills"

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "ERROR: $SKILL_SRC/SKILL.md 를 찾을 수 없습니다. 저장소 루트에서 실행하세요." >&2
  exit 1
fi

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

for tool in "${TOOLS[@]}"; do
  link "$HOME/.$tool/skills/harness" "$SKILL_SRC"
done
link "$AGY_SKILLS_DIR/harness" "$SKILL_SRC"

cat <<EOF

설치 완료. 이제 어떤 프로젝트 디렉터리에서 열어도 harness 스킬이 자동 로드됩니다.
  ~/.claude/skills/harness, ~/.kimi/skills/harness, ~/.codex/skills/harness -> $SKILL_SRC
  $AGY_SKILLS_DIR/harness -> $SKILL_SRC  (Antigravity: agy/AGY CLI/AGY IDE 공통)

업데이트: $SCRIPT_DIR 에서 'git pull' 실행 (심볼릭 링크라 재설치 불필요).
EOF
