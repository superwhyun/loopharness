# Harness Workflow

이 문서는 이 저장소의 범용 하네스 워크플로우 원문이다.
Claude Code, Antigravity CLI (agy), Kimi Code CLI, Codex 모두 이 문서를 기준으로 작업해야 한다.

## 목표
- 작업을 step 단위로 분해한다.
- step 상태를 파일로 관리한다.
- 자동 반복은 최대 3회 재시도로 제한한다.
- 후속 step은 이전 구현 전체 대신 baseline, module-map, public contract를 우선 읽어 토큰 사용을 줄인다.
- 코드 품질을 위해 필요한 경우에는 영향 모듈만 targeted read 하고, 수정은 별도 fix/change step으로 분리한다.

## 실행 순서

### 대상 프로젝트 결정

하네스 프레임워크에서 작업할 때는 먼저 대상 프로젝트를 정한다.

1. 사용자가 명시한 프로젝트 경로를 우선 사용한다.
2. 없으면 사용자에게 대상 프로젝트 경로를 물어본다.

이 저장소를 클론한 디렉터리가 곧 프로젝트 루트다.
`phases/`는 클론 루트 바로 아래에 위치한다.

### A. 탐색 (Discovery)

**CRITICAL — 탐색 전 필수 확인:**
대상 프로젝트 디렉터리에 `phases/` 가 존재하면 **진행 중인 프로젝트**다.
`package.json`이나 소스 코드가 없어도 마찬가지다.
이 경우 scaffold를 재실행하거나 디렉터리를 삭제·초기화하지 마라.
반드시 `phases/index.json`을 읽고 첫 `pending` step부터 이어서 진행한다.

먼저 아래를 읽고 현재 상태를 파악한다.
1. `AGENTS.md` (공통 규칙)
2. `docs/ARCHITECTURE.md`, `docs/ADR.md`
3. 대상 프로젝트의 `phases/index.json` 및 `phases/{task}/index.json`
4. `phases/project-manifest.json` (있으면) — 전체 프로젝트 누적 현황
5. 현재 phase의 `phases/{task}/module-map.json` (있으면)
6. 현재 step의 `stepN.md`
7. 직전 step output은 복구가 필요할 때만 읽는다.

### B. 논의 (Discussion)
구현 전에 결정이 더 필요한 사항이 있으면 사용자와 먼저 정리한다.

새 기능 요청이 들어왔을 때 아래 조건 중 하나라도 해당하면 **반드시 새 phase를 설계하고 사용자 승인을 받은 뒤 실행한다**:
- 현재 모든 phase가 `completed` 상태인 경우
- 요청이 기존 phase 범위를 벗어난 새 기능인 경우

사용자가 명시적으로 "phase 설계"를 언급하지 않아도 위 조건이 충족되면 AI가 먼저 phase 설계안을 제시한다.

### C. Step 설계 (Planning)
필요 시 `scripts/scaffold_phase.py`를 사용하여 페이즈를 설계한다.

```bash
python3 scripts/scaffold_phase.py {phase-dir} --project {name} --steps step1 step2 ...
```

1. Scope를 최소화한다 (한 번에 한 스텝만).
2. Step 0은 가능하면 `module-map.json`과 public contract 초안을 만든다.
3. 각 step은 독립 세션에서도 이해 가능해야 한다.
4. 각 step은 `owned_paths`, `read_contracts`, `forbidden_paths`를 명시한다.
5. 후속 step은 의존 모듈의 구현 내부가 아니라 public contract를 기본 입력으로 삼는다.
6. AC는 실행 가능한 명령으로 적는다.
7. **AC는 루프 종료 신호로도 쓰이므로 다음을 지킨다:** (a) 각 AC는 `test -f`, `grep -cE`, `validate_phase` 같은 **측정 가능한 명령**으로 쓴다. (b) AC는 **항목별로 분리**해서 쓴다 — 통과하지 못했을 때 "어느 항목이 부족한지" 실행자가 바로 알 수 있어야, 다음 재작성이 그 결함을 고칠 수 있다. (c) 모든 AC 통과 = 이 step 완료의 종료 신호다.
8. 현재 step을 막는 외부 contract/모듈 문제가 발견되면 현재 step을 `blocked`로 기록하고 `blocking-fix` 또는 `contract-change` step을 append한다.
9. 현재 step을 막지 않는 개선사항은 phase 마지막에 `backlog-fix` step으로 append한다.
10. 기존 step 번호는 재정렬하지 않는다. 새 step은 항상 append한다.

### D. 실행 (Execution)
`pending` 상태인 스텝부터 이어서 작업한다.
- `completed`면 다음 스텝으로 이동.
- `blocked`면 이유를 기록한다. 단, pending `blocking-fix` step이 있으면 그 step을 먼저 수행한다.
- `error`면 원인과 재개 힌트 남기고 중단.
- `blocking-fix` step 완료 후에는 `unblocks` 대상 step을 다시 `pending`으로 풀고 원래 흐름으로 돌아간다.

**실행 루프 (step별):**
1. `owned_paths` 산출물을 작성한다.
2. step의 **AC 전체를 검증**한다.
3. **AC를 모두 통과하면** 이 step을 `completed`로 만들고 다음 step으로 간다.
4. **AC를 통과하지 못하면** 단순 재실행이 아니라, **AC가 지목한 결함 항목을 고쳐서 산출물 내용을 재작성**한 뒤 다시 AC를 검증한다.
5. 재작성은 **최대 3회**까지. 3회 내에 AC를 통과하지 못하면 이 step을 `blocked`로 기록한다.
6. `blocked` 후 대응은 기존 규칙을 따른다: 원인이 step 범위 밖의 contract/모듈 문제면 `blocking-fix`/`contract-change` step을 append해 즉시 해소하고, 해소되면 원 step을 다시 `pending`으로 풀어 재개한다. (스코프가 커서 해결이 안 되는 경우에만 작은 step으로 쪼갠다 — 분해를 별도 체계로 만들지 않는다.)

### E. Phase 마감 (Baseline)

phase 종료 시에는 다음 phase가 전체 구현을 다시 읽지 않도록 `phases/baselines/{phase-dir}.json`에 아래를 남긴다. 배치 실행기는 최소 baseline skeleton을 자동 생성하며, 에이전트는 필요한 경우 내용을 더 풍부하게 보강한다.
- 완료 tag
- 모듈 목록과 public surface
- shared contracts
- routes 또는 외부 진입점
- integration points
- known issues

### F. Git 커밋 (Commit)

커밋은 **step 단위**로 한다. phase 단위로 묶지 않는다.

**커밋 위치**: 클론 루트(프로젝트 루트)에서 실행한다.

**`git init` 규칙**:
- `git init`은 프로젝트 최초 생성 시(scaffold step) **딱 한 번만** 실행한다.
- `.git` 디렉터리가 이미 존재하면 `git init`을 절대 재실행하지 마라.
- 커밋 전에는 반드시 `git status`로 repo 존재 여부를 확인한다.
- 이미 repo가 있는데 `git init`을 실행하면 기존 git 설정이 손상될 수 있다.

**`.gitignore` 규칙**:
- `git init` 직후, 첫 `git add` 실행 전에 `.gitignore`를 반드시 작성한다.
- `.gitignore` 없이 `git add .` 또는 `git add -A`를 실행하지 마라.
- 반드시 포함해야 할 항목: `node_modules/`, `dist/`, `build/`, `.env*`, `.DS_Store`, `*.tsbuildinfo`, `.vercel`, `coverage/`, `__pycache__/`, `.venv/`
- 기술 스택에 따라 추가 항목을 포함한다.

**커밋 시점**: AC를 통과한 직후.

**커밋 메시지 형식**:
```
feat({project}/step{N}): {step-name} — {한 줄 요약}
```

예시:
```
feat(debate/step0): project-setup — package skeleton
feat(debate/step2): llm-clients — 5 backends async
feat(debate/step8): web-api — FastAPI routes + output.py
```

**phase 완료 시**: 마지막 step 커밋 후 태그를 단다.
```bash
git tag {project}-phase{N}-done
# 예: git tag debate-phase0-done
```

**이유**:
- step별 AC 통과 = 자연스러운 커밋 경계
- 특정 step 실패 시 해당 step만 revert 가능
- 다른 AI 툴이 이어받을 때 git log에서 진행 상태 파악 가능

## 상태 파일 포맷
- `phases/index.json`: 페이즈 목록 및 최상위 상태.
- `phases/project-manifest.json`: 전체 프로젝트 누적 현황 (모듈, 라우트, 공유 계약, 통합 지점). Phase 완료 시 자동 업데이트.
- `phases/{task}/index.json`: 스텝 목록 및 상태.
- `phases/{task}/module-map.json`: 모듈 경계, 소유 step, owned paths, public contracts, dependencies.
- `phases/{task}/stepN.md`: 실행 지시서.
- `phases/baselines/{phase-dir}.json`: 완료 phase의 압축된 기준선.

## 루프 모드 (Loop Engineering)

`/loop` 커맨드를 사용하면 에이전트가 루프를 직접 오케스트레이션한다.
단일 하네스 실행이 아니라 **Plan → Execute → Evaluate** 사이클을 자율적으로 반복한다.

| 모드 | 진입점 | 사용 상황 |
|------|--------|-----------|
| 인터랙티브 루프 | `/loop` (이 커맨드) | Claude Code, OpenCode, Codex, Gemini 등 AI 에이전트 |
| 배치 헤드리스 루프 | `python3 scripts/loop.py` | 에이전트 없이 로컬 LLM만으로 자동 실행 |
| 단일 phase 실행 | `/harness` 또는 `scripts/execute.py` | 사람이 단계별로 확인하며 진행 |

로컬 LLM(원격 IP) 연결은 `config.json`의 `local_api` 타입 백엔드로 설정한다.
OpenCode, Cursor 등 에이전트 IDE에서 로컬 LLM을 연결하면 `/loop` 커맨드를 그대로 사용할 수 있다.

### 설계 강제 반복 개선 (적용 단위 명확화)

5회 반복 재작성은 **두 계층 모두에 각각 적용**한다.

**A. phase 수준:** 전체 phase 목록(몇 개의 phase, 어떤 순서)을 초안으로 만든 뒤 **판정 없이 무조건 5회 반복 재작성**한다.

**B. step 수준:** phase 목록이 확정된 뒤, **각 phase의 step 구성을 개별적으로** 초안으로 만들고 **그 phase의 step 설계만 5회 반복 재작성**한다. 다음 phase로 넘어가기 전에 현재 phase의 step이 5회 재점검을 마쳐야 한다.

즉, phase 5개면 **각 phase의 step을 5회씩** 재점검해야 한다. step 수준 재작성이 끝나기 전에 해당 phase를 "완료"로 취급하지 않는다.

**⚠️ 5회 재점검의 검증 기준 (CRITICAL):**
- 재점검은 **별도 로그 문서에 "회차 1~5"를 기록하는 것만으로 충분하지 않다.** 반드시 **실제 stepN.md 파일 내용이 각 회차마다 개선되어야** 한다.
- 각 회차에서 step 파일에 **실질적인 개선**(요구사항 명확화, AC 구체화, 차별점 반영, read_contracts/forbidden_paths 정합성, 검증 절차 보강)이 실제로 적용됐는지 확인한다.
- "이번 회차는 유지" 또는 "로그만 기록" 은 재작성이 아니다 — 무조건 파일을 수정해야 한다.
- 회차별 개선 내역을 step 파일 자체 또는 보강 로그에 남기되, **개선이 파일에 실제 반영된 것**을 확인 가능하게 한다.
- 5회차가 끝나면 각 step 파일이 회차 1 대비 더 완성도 높고 실행 가능한 상태여야 한다.

각 회차(phase든 step이든)는 판정 없이 무조건 반복한다.
리뷰어에게 "통과 여부"를 묻거나 자가 판정으로 그치는 대신, 매 회차마다 **이전 버전 전체를 재검토하고 완전한 수정안으로 다시 작성**한다.
매 회차에서 누락된 요구사항, 목표·성공 기준 충족 여부, 모듈 경계와 의존성, 실행 가능한 AC, 범위·세션 연속성을 차례로 다시 점검한다.
5회차 산출물이 최종 설계다. 회차마다 1회차 대비 더 나은 설계를 만들어야 하며, 반복을 건너뛰거나 횟수를 줄이지 않는다.
`scripts/loop.py`의 Planner와 `/loop` 에이전트 워크플로우 모두 이 규칙을 따른다.

## CRITICAL: phases/ 보호 규칙

`phases/` 디렉터리는 프로젝트의 구현 계획과 진행 상태를 담는 SSOT다.
어떤 상황에서도 아래 행동은 금지한다:

- `phases/` 디렉터리 삭제 또는 재생성
- 기존 `stepN.md` 파일 덮어쓰기 (이미 내용이 있는 경우)
- `phases/index.json` 또는 `phases/{task}/index.json` 초기화

**새 세션에서 작업을 시작할 때의 올바른 순서:**
1. `phases/index.json` 읽기 → 전체 phase 상태 파악
2. `phases/project-manifest.json` 읽기 (있으면) → 전체 프로젝트 누적 현황 파악
3. 첫 `pending` phase의 `phases/{task}/index.json` 읽기
4. 첫 `pending` phase의 `module-map.json` 읽기 (있으면)
5. 첫 `pending` step의 `stepN.md` 읽기
6. 작업 시작
