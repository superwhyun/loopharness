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

---

# Space Network — 차세대 메타버스 아키텍처

## 개요

차세대 메타버스는 하나의 거대한 가상세계가 아니라, **목적별로 생성된 공간들이 연결된 네트워크**다.
사용자는 교육·협업·전시·시뮬레이션 등 각 목적에 맞는 공간으로 이동하며,
이전 공간의 작업 상태, 객체 정보, 참여자 관계, 진행 상황을 그대로 이어갈 수 있다.

## 시스템 구조

```text
┌─────────────────────────────────────────────────────────────────┐
│                   Hybrid Runtime Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐      │
│  │ Web Adapter  │  │ Unity Adapter│  │ Unreal Adapter   │      │
│  │ (Three.js/   │  │ (C# Script)  │  │ (C++/Blueprint)  │      │
│  │  WebGPU)     │  │              │  │                  │      │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘      │
│         │                 │                    │               │
│         └─────────────────┼────────────────────┘               │
│                           │ IHybridBridge                       │
├───────────────────────────┼─────────────────────────────────────┤
│                Core Engine Layer                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Context Continuity Engine                  │   │
│  │  (IContextStore, IContextMigrator, ISessionManager)     │   │
│  └───────────────────────┬─────────────────────────────────┘   │
│                          │                                     │
│  ┌───────────────────────┼─────────────────────────────────┐   │
│  │         State Sync Protocol              │              │   │
│  │  (ISyncProtocol, CRDT, Conflict Resolver)│              │   │
│  └───────────────────────┼─────────────────────────────────┘   │
│                          │                                     │
│  ┌───────────────────────┼─────────────────────────────────┐   │
│  │     Space Spec Layer (SSL)            │                 │   │
│  │  (ISpaceSpec, IObjectSpec, IEnvironmentSpec)            │   │
│  └───────────────────────┼─────────────────────────────────┘   │
│                          │                                     │
├──────────────────────────┼─────────────────────────────────────┤
│              Service Layer (Backend)                            │
│  ┌────────────────┐ ┌──────────────┐ ┌────────────────────┐   │
│  │ Space Registry │ │ Auth Context │ │ Generative AI      │   │
│  │ (ISpaceRegistry│ │ (IAuthContext)│ │ (ISpaceGenerator,  │   │
│  │  + Metadata)   │ │              │ │  IObjectGenerator)  │   │
│  └────────────────┘ └──────────────┘ └────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 모듈 계층 구조

| 계층 | 모듈 | 역할 | 의존성 |
|------|------|------|--------|
| **Runtime** | Web Adapter | Three.js/WebGPU 렌더링 | space-spec, state-sync |
| **Runtime** | Unity Adapter | Unity C# 렌더링 | space-spec, state-sync |
| **Runtime** | Unreal Adapter | Unreal C++ 렌더링 | space-spec, state-sync |
| **Core** | Context Engine | 공간 간 맥락 지속성 | space-spec, state-sync |
| **Core** | State Sync | 실시간 상태 동기화 | space-spec |
| **Core** | Space Spec (SSL) | 공간/객체 명세 언어 | 없음 |
| **Service** | Generative AI | AI 기반 자동 생성 | space-spec, context-engine |

## 데이터 흐름

### 1. 공간 로딩 흐름
```text
사용자 → Space Registry.getSpace(id)
       → ISpaceSpec (SSL 파싱)
       → IHybridBridge.loadSpace(spec)
       → IRenderer.render(spec)
```

### 2. 상태 동기화 흐름 (실시간)
```text
참여자 A 조작 → Change 감지
       → StateDelta 생성
       → ISyncProtocol.publish(delta)
       → (네트워크 전파)
       → ISyncProtocol.subscribe (참여자 B~Z)
       → IHybridBridge.applyDelta(delta)
       → IRenderer.update(delta)
```

### 3. 컨텍스트 연속성 흐름 (공간 간 이동)
```text
사용자: Space A → Space B 이동
       1. IContextStore.save(sessionId, snapshot)  ← Space A의 현재 상태 저장
       2. snapshot = {
            objects: { objectId: ObjectState },
            users: { userId: UserState },
            progress: ProgressState
          }
       3. ISessionManager.switchSpace(sessionId, targetSpaceId)
       4. Space B 로딩
       5. IContextMigrator.migrate(A, B, snapshot)
       6. IContextMigrator.resolve(B, snapshot)
       7. Space B에서 맥락 복원 (객체 선택 상태, UI 상태, 진행 상황 등)
```

### 4. 생성형 AI 파이프라인
```text
사용자 → "과학 실험실 공간 만들어줘" (자연어)
       → ISpaceGenerator.generateSpace(prompt)
       → (LLM이 공간 구조 설계)
       → ISpaceSpec 출력 (객체, 환경, 상호작용 규칙 포함)
       → IHybridBridge.loadSpace(spec)
```

## 공유 계약 (Shared Contracts)

| Contract | 제공 모듈 | 소비 모듈 | 설명 |
|----------|-----------|-----------|------|
| ISpaceSpec | space-spec | 전체 | 공간 명세 read/write |
| IObjectSpec | space-spec | 전체 | 객체 명세 read/write |
| ISyncProtocol | state-sync | runtime 전체 | 상태 동기화 진입점 |
| IStateDelta | state-sync | runtime 전체 | 변경 델타 데이터 |
| IContextStore | context-engine | service/gen-ai | 컨텍스트 저장/복원 |
| IContextMigrator | context-engine | service/gen-ai | 맥락 마이그레이션 |
| IHybridBridge | runtime 전체 | core | 크로스 플랫폼 브리지 |
| ISpaceGenerator | gen-ai | service | AI 공간 생성 |
| ISpaceRegistry | service | runtime | 공간 메타데이터 저장소 |
| IAuthContext | service | runtime | 인증/권한 |

## 핵심 설계 원칙

1. **SSL 우선 (Spec-first)**: 모든 런타임은 동일한 Space Spec을 해석하므로, Spec이 진실 공급원(SSOT)이다.
2. **CRDT 기반 동기화**: 충돌 없는 데이터 타입으로 네트워크 지연과 오프라인 변경을 안전하게 병합한다.
3. **Snapshot 기반 컨텍스트 전이**: 공간 간 이동 시 전체 상태의 스냅샷을 떠서 목적지에서 복원한다.
4. **Plugin 런타임 아키텍처**: 각 런타임 어댑터는 동일한 IHybridBridge contract을 구현한다.
5. **AI-native 생성**: 모든 공간과 객체는 생성형 AI가 SSL 포맷으로 출력하여, 사람이 직접 모델링하지 않아도 된다.
