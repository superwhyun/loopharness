# 아키텍처: Loop Harness Framework

## 사용 방식

프레임워크를 **프로젝트마다 클론**해서 사용한다.
클론 루트가 곧 프로젝트 루트다.

```bash
gh repo clone looped_harness my-project
cd my-project
# 여기서 /loop 또는 /harness 시작
```

## 디렉토리 구조

```text
my-project/               ← 클론 루트 = 프로젝트 루트
├── engine/               # Python 엔진 (executor, backends, loop 컴포넌트)
├── scripts/              # CLI 진입점
│   ├── execute.py        # 단일 phase 실행
│   ├── scaffold_phase.py # phase/step 파일 생성
│   ├── loop.py           # 배치 헤드리스 루프
│   └── validate_phase.py # phase 정합성 검증
├── templates/            # step.md, module-map 템플릿
├── docs/                 # 프레임워크 문서
├── .claude/commands/     # /harness, /loop, /review 슬래시 커맨드
├── phases/               # 프로젝트 진행 상태 SSOT (git ignored by default)
│   ├── index.json
│   ├── baselines/
│   │   └── {phase-dir}.json
│   └── {task}/
│       ├── index.json
│       ├── module-map.json
│       └── stepN.md
├── goal.json             # 루프 목표 명세 (loop 모드)
└── src/                  # 실제 프로덕 소스코드
```

## 패턴

### 1. 단계별 분해 (Step-based Decomposition)
복잡한 작업을 원자 단위 Step으로 분해한다. AI 에이전트가 각 단계의 Acceptance Criteria에만 집중하게 해 오류를 최소화한다.

### 2. 계약 우선 모듈 경계 (Contract-first Module Boundary)
각 phase는 `module-map.json`으로 모듈, 소유 step, `owned_paths`, public contract, dependency를 기록한다. 후속 step은 이전 구현 전체를 다시 읽지 않고 baseline과 public contract를 먼저 읽는다.

### 3. 백엔드 추상화 (Backend Abstraction)
`AgentBackend` 인터페이스로 Claude CLI, Codex, Gemini, 로컬 LLM(OpenAI-compatible HTTP) 등을 교체 가능하게 한다.

### 4. 루프 오케스트레이션 (Loop Engineering)
AI 에이전트(`/loop`)가 Plan→Execute→Evaluate 싸이클을 자율 반복한다.
배치 모드에서는 `scripts/loop.py`가 오케스트레이션한다.

## 데이터 흐름

```text
1. /loop 또는 /harness 커맨드 실행
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

`config.json`에 `local_api` 타입 백엔드를 추가한다.

```json
"my-llm": {
  "type": "local_api",
  "endpoint": "http://192.168.0.10:11434/v1/chat/completions",
  "model": "qwen2.5-coder:32b",
  "api_key": "local"
}
```

OpenCode, Cursor 등 에이전트 IDE에 로컬 LLM을 연결하면 `/loop` 커맨드를 그대로 사용할 수 있다.
에이전트 없이 자동 실행할 때는 `python3 scripts/loop.py --backend my-llm`을 사용한다.
