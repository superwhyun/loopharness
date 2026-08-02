# 아키텍처: Loop Harness Framework

## 사용 방식

프레임워크는 **한 곳에 설치**해두고, 여러 대상 프로젝트에서 스킬로 재사용한다.
프레임워크 저장소를 대상 프로젝트마다 클론하지 않는다.

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/superwhyun/skill-harness.git ~/.agents/skills/harness
cd ~/.agents/skills/harness
bash install.sh
# ~/.claude/skills/harness, ~/.kimi/skills/harness, ~/.codex/skills/harness 가
# 이 클론의 skills/harness/ 를 가리키는 심볼릭 링크로 생성된다.

cd ~/아무-프로젝트
# 여기서 하네스 스킬이 자동 로드된 상태로 /harness 또는 /loop 시작
```

업데이트는 `~/.agents/skills/harness`에서 `git pull` 한 번이면 된다. 심볼릭 링크로 연결돼 있으므로 설치된 스킬도 즉시 최신 상태가 된다. **이 클론 디렉터리는 지우면 안 된다** — symlink가 가리키는 실제 원본이다.

## 디렉토리 구조

```text
~/.agents/skills/harness/              ← 이 저장소 (프레임워크 소스, 프로젝트 인스턴스 아님)
├── skills/harness/
│   ├── SKILL.md                      # 스킬 진입점 (Claude Code / Kimi 공용 포맷)
│   └── framework/                    # 번들 프레임워크 — 실제 배포되는 원본
│       ├── engine/                   # Python 엔진 (executor, backends, loop 컴포넌트)
│       ├── scripts/                  # CLI 진입점
│       │   ├── execute.py            # 단일 phase 실행
│       │   ├── scaffold_phase.py     # phase/step 파일 생성
│       │   ├── loop.py               # 배치 헤드리스 루프
│       │   └── validate_phase.py     # phase 정합성 검증
│       ├── templates/                # step.md, module-map 템플릿
│       ├── docs/                     # 프레임워크 문서 (이 문서 포함)
│       ├── tests/                    # 엔진 테스트
│       └── config.json               # 백엔드 정의 (claude/codex/kimi 등)
├── install.sh                        # 각 툴(claude/kimi/codex)의 skills/harness 를
│                                      # 이 클론의 skills/harness/ 로 symlink
├── AGENTS.md, CLAUDE.md, GEMINI.md   # 이 저장소(프레임워크 개발) 자체를 위한 진입점
└── .claude/commands/                 # 이 저장소를 직접 열었을 때를 위한 로컬 진입점 (Claude Code)

대상-프로젝트/                          ← 하네스 스킬로 작업하는 실제 프로젝트 (별도 디렉터리)
├── phases/                           # 프로젝트 진행 상태 SSOT (git ignored by default)
│   ├── index.json
│   ├── baselines/
│   │   └── {phase-dir}.json
│   └── {task}/
│       ├── index.json
│       ├── module-map.json
│       └── stepN.md
├── goal.json                         # 루프 목표 명세 (loop 모드)
├── docs/                             # 이 프로젝트 자체의 PRD/ARCHITECTURE/ADR (선택)
└── src/                              # 실제 프로덕트 소스코드
```

`skills/harness/framework/scripts/*.py`는 항상 `--root {대상 프로젝트 경로}`로 대상 프로젝트를 가리켜 실행한다. 대상 프로젝트에 자체 `config.json`이 없으면 번들의 `skills/harness/framework/config.json`을 fallback으로 사용한다.

## 패턴

### 1. 단계별 분해 (Step-based Decomposition)
복잡한 작업을 원자 단위 Step으로 분해한다. AI 에이전트가 각 단계의 Acceptance Criteria에만 집중하게 해 오류를 최소화한다.

### 2. 계약 우선 모듈 경계 (Contract-first Module Boundary)
각 phase는 `module-map.json`으로 모듈, 소유 step, `owned_paths`, public contract, dependency를 기록한다. 후속 step은 이전 구현 전체를 다시 읽지 않고 baseline과 public contract를 먼저 읽는다.

### 3. 백엔드 추상화 (Backend Abstraction)
`AgentBackend` 인터페이스로 Claude CLI, Codex, Gemini, 로컬 LLM(OpenAI-compatible HTTP) 등을 교체 가능하게 한다.

### 4. 루프 오케스트레이션 (Loop Engineering)
AI 에이전트(`/loop`)가 Plan→Execute→Evaluate 싸이클을 자율 반복한다.
배치 모드에서는 `skills/harness/framework/scripts/loop.py`가 오케스트레이션한다.

### 5. 프레임워크/프로젝트 분리 (Framework-Project Separation)
프레임워크(엔진·스크립트·문서)와 대상 프로젝트(phases·goal.json·소스코드)는 서로 다른 디렉터리에 산다. `engine/project_context.resolve_project_root`가 `--root` 유무로 이를 구분하고, `PromptBuilder.load_guardrails`는 `framework_root`와 `root`(대상 프로젝트) 양쪽의 가드레일 파일을 각각 "프레임워크 규칙"/"프로젝트 규칙" 섹션으로 병합한다.

## 데이터 흐름

```text
1. 대상 프로젝트에서 /loop 또는 /harness 스킬 실행
2. phases/index.json 탐색 (진행 중인 phase 확인)
3. phases/{task}/index.json 탐색 (첫 pending step 확인)
4. 이전 phase baseline + 현재 phase module-map 로드
5. stepN.md 로드 (목표, 모듈 경계, AC)
6. AI 에이전트 실행 (작업 수행 및 파일 수정)
7. 검증 (AC 실행)
8. index.json 상태 업데이트 및 커밋
9. phase 완료 시 baseline artifact 생성
10. [loop 모드] Evaluator 판정 → 다음 phase 결정 또는 종료
```

## 상태 관리

- **전역 상태:** `phases/index.json`
- **phase 상태:** `phases/{task}/index.json`
- **모듈 경계:** `phases/{task}/module-map.json`
- **phase 기준선:** `phases/baselines/{phase-dir}.json`
- **루프 목표:** `goal.json`
- **전이 규칙:** `pending` → `completed` (성공) / `error` (실패) / `blocked` (중단)

## 로컬 LLM 연결

`config.json`(대상 프로젝트 우선, 없으면 `skills/harness/framework/config.json`)에 `local_api` 타입 백엔드를 추가한다.

```json
"my-llm": {
  "type": "local_api",
  "endpoint": "http://192.168.0.10:11434/v1/chat/completions",
  "model": "qwen2.5-coder:32b",
  "api_key": "local"
}
```

OpenCode, Cursor 등 에이전트 IDE에 로컬 LLM을 연결하면 `/loop` 커맨드를 그대로 사용할 수 있다.
에이전트 없이 자동 실행할 때는 `python3 skills/harness/framework/scripts/loop.py --backend my-llm --root {대상 프로젝트 경로}`를 사용한다.
