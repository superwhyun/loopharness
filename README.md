# Space Network

**차세대 메타버스 공간 네트워크 플랫폼 SDK**

하나의 거대한 가상세계가 아닌, **목적별로 생성된 공간들이 연결된 네트워크**.
사용자는 교육·협업·전시·시뮬레이션 공간을 이동하며 이전 공간의 작업 상태, 객체 정보, 참여자 관계, 진행 상황을 그대로 이어갈 수 있다.

---

## 빠른 시작

### 1. 설치

```bash
git clone <repo-url> space-network
cd space-network
npm install
npm run build
```

### 2. 샘플 공간 검증

```bash
npx ts-node src/cli/index.ts ssl validate sample-space.json
```

### 3. Web 데모 뷰어 실행

```bash
npx ts-node src/cli/index.ts serve -p 3000
# 또는: npx ts-node src/cli/index.ts ssl serve -p 3000
```

브라우저에서 http://localhost:3000 열기 → 드롭다운에서 템플릿 선택 → "Load" 클릭

### 4. WebSocket 동기화 서버 실행

```bash
npx ts-node src/cli/index.ts sync-server -p 8080
# 또는: npx ts-node src/cli/index.ts ssl sync-server -p 8080
```

### 5. LLM 기반 공간 생성 (선택사항)

```bash
export OPENAI_API_KEY=sk-...
npx ts-node src/cli/index.ts ssl generate "과학 실험실을 만들어줘" --type education
```

---

## CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `ssl validate <file>` | SSL JSON 파일 유효성 검증 |
| `ssl compile <file> --target <platform>` | SSL → Web/Unity/Unreal 설정 컴파일 |
| `ssl generate "<prompt>" --type <type>` | 자연어 → SSL 공간 명세 생성 |
| `ssl templates` | 사용 가능한 13개 프리셋 템플릿 목록 |
| `serve -p <port>` | Three.js 3D 뷰어 서버 실행 (`ssl serve`도 가능) |
| `sync-server -p <port>` | WebSocket 동기화 서버 실행 (`ssl sync-server`도 가능) |

**compile 대상 플랫폼**: `web`, `unity`, `unreal`, `generic`

**generate 공간 유형**: `education`, `collaboration`, `exhibition`, `simulation`, `social`

---

## 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                  Hybrid Runtime Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Web (TS)    │  │  Unity (C#)  │  │ Unreal (C++) │   │
│  │ Three.js/    │  │  IUnitySpace │  │ IUnrealSpace │   │
│  │  WebGPU      │  │  Adapter     │  │ Adapter      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         └─────────────────┼──────────────────┘           │
│                           │ IHybridBridge                 │
├───────────────────────────┼──────────────────────────────┤
│                 Core Engine Layer                         │
│  ┌──────────────────────────────────────────────────┐    │
│  │           Context Continuity Engine               │    │
│  │  ContextStore → ContextMigrator → SessionManager  │    │
│  └───────────────────────┬──────────────────────────┘    │
│  ┌───────────────────────┼──────────────────────────┐    │
│  │       State Sync Protocol          │              │    │
│  │  CRDT → WebSocket → Delta Compress │              │    │
│  └───────────────────────┼──────────────────────────┘    │
│  ┌───────────────────────┼──────────────────────────┐    │
│  │    Space Spec (SSL)               │              │    │
│  │  Parser → Validator → Compiler    │              │    │
│  └─────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                   Service Layer                           │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │  Space   │  │   Auth   │  │   Generative AI        │  │
│  │ Registry │  │  Context │  │  LLMClient → Generator │  │
│  └──────────┘  └──────────┘  └───────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 핵심 개념

| 개념 | 설명 |
|------|------|
| **SSL** | Space Specification Language. JSON 기반 공간·객체·환경 명세 |
| **CRDT** | Conflict-free Replicated Data Types. 충돌 없는 분산 병합 |
| **Context Snapshot** | 공간 간 이동 시 객체 상태, 사용자 위치, 진행 상황을 스냅샷으로 저장 |
| **Context Migrator** | 5×5 공간 타입 매핑 매트릭스로 타입 간 속성 변환 |
| **Hybrid Bridge** | Web/Unity/Unreal 공통 IHybridBridge 인터페이스 |

---

## 프로젝트 구조

```
src/
├── core/
│   ├── models/          # Space, Object, User, Context 타입 정의
│   ├── contracts/       # IHybridBridge, ISyncProtocol, ISpaceRegistry, IAuthContext
│   └── schemas/         # JSON Schema 파일
├── space-spec/
│   ├── parser.ts        # SSL JSON → TypeScript 객체
│   ├── serializer.ts    # TypeScript 객체 → SSL JSON
│   ├── validator.ts     # 공간 명세 유효성 검증
│   ├── templates/       # 13개 프리셋 템플릿 (교육/협업/전시/시뮬레이션/소셜)
│   └── compiler/        # SSL → Web/Unity/Unreal 컴파일러
├── state-sync/
│   ├── sync-protocol.ts # ISyncProtocol 구현
│   ├── crdt/            # LWWRegister, GCounter, PNCounter, ORSet, CRDTMap
│   ├── transport/       # WebSocket 클라이언트/서버, 재연결 전략
│   └── server/          # 실제 WebSocket SyncServer + SyncClient
├── context-engine/
│   ├── context-store.ts     # InMemoryContextStore (save/load/list/delete)
│   ├── context-migrator.ts  # 공간 간 컨텍스트 마이그레이션
│   ├── session-manager.ts   # 세션 생성/전환
│   └── context-resolver.ts  # 5×5 공간 타입 매핑
├── gen-ai/
│   ├── space-generator.ts       # 템플릿 기반 공간 생성
│   ├── object-generator.ts      # 객체 생성
│   ├── interaction-generator.ts # 상호작용 규칙 생성
│   ├── llm-client.ts            # OpenAI API 클라이언트
│   └── llm-space-generator.ts   # LLM 기반 공간 생성 (fallback 지원)
├── runtime/
│   ├── web/         # WebHybridBridge + Express Viewer + Three.js
│   ├── unity/       # UnityHybridBridge (C# interop contract)
│   └── unreal/      # UnrealHybridBridge (C++ interop contract)
└── cli/
    └── index.ts     # Commander 기반 CLI (6개 서브커맨드)
```

---

## 모듈

| 모듈 | 버전 | 설명 |
|------|------|------|
| `core/space-spec` | 0.2.0 | Space Specification Language — 공간/객체 명세, 검증, 컴파일 |
| `core/state-sync` | 0.1.0 | CRDT 기반 실시간 상태 동기화 + WebSocket 서버 |
| `core/context-engine` | 0.1.0 | 공간 간 컨텍스트 연속성 (Store/Migrator/Session/Resolver) |
| `gen-ai/generator` | 0.1.0 | 생성형 AI (템플릿 + OpenAI LLM) 기반 자동 생성 |
| `runtime/web-adapter` | 0.1.0 | Web (Three.js) 런타임 어댑터 + Express 뷰어 |
| `runtime/unity-adapter` | 0.1.0 | Unity 런타임 어댑터 (TypeScript → C# contract) |
| `runtime/unreal-adapter` | 0.1.0 | Unreal Engine 런타임 어댑터 (TypeScript → C++ contract) |

---

## 사용 시나리오

### 시나리오 1: 새 교육 공간 만들기

```javascript
const { SSLParser, SSLValidator, SSLCompiler } = require('space-network');
const fs = require('fs');

// 1. SSL 파일 로드
const json = fs.readFileSync('classroom.json', 'utf-8');
const parser = new SSLParser();
const spec = parser.parseSpaceSpec(json);

// 2. 검증
const validator = new SSLValidator();
const result = validator.validateSpaceSpec(spec);
console.log(result.valid ? 'Valid!' : result.errors);

// 3. Web용으로 컴파일
const compiler = new SSLCompiler();
const webConfig = compiler.compileToWeb(spec);
fs.writeFileSync('classroom.web.json', JSON.stringify(webConfig, null, 2));
```

### 시나리오 2: 공간 간 이동 (컨텍스트 유지)

```javascript
const { SessionManager, ContextMigrator } = require('space-network');

const session = await sessionManager.createSession('user-1', 'classroom-01');
// ... 사용자가 classroom-01에서 작업 ...

// lab-01 으로 이동 (컨텍스트 자동 저장 + 복원)
const result = await sessionManager.switchSpace(session.id, 'lab-01');
console.log(result.migratedObjects); // 마이그레이션된 객체 목록
```

### 시나리오 3: WebSocket 실시간 동기화

```javascript
// 서버
const { SpaceSyncServer } = require('space-network');
const server = new SpaceSyncServer(8080);
server.start();

// 클라이언트
const { SyncClient, createStateDelta, createChange } = require('space-network');
const client = new SyncClient('ws://localhost:8080', 'classroom-01');
client.connect();
client.onDelta((delta) => console.log('Sync received:', delta));
client.sendDelta(createStateDelta('classroom-01', [createChange('object_modified', 'client-1', { objectId: 'desk_01' })], 'client-1'));
```

### 시나리오 4: AI로 공간 생성

```javascript
const { SpaceGenerator } = require('space-network');
const generator = new SpaceGenerator();
const result = await generator.generateSpace({
  prompt: '해양 생물 연구소, 수족관이 있고 관찰 데크가 있는',
  spaceType: 'education',
});
console.log(result.spec);

// LLM 사용 (OPENAI_API_KEY 필요)
const { LLMSpaceGenerator } = require('space-network');
const llmGen = new LLMSpaceGenerator(process.env.OPENAI_API_KEY);
const llmResult = await llmGen.generateSpace({
  prompt: '화성 기지 내부, 6명 거주용, hydroponic farm 포함',
  spaceType: 'simulation',
});
```

---

## 빌드 및 테스트

```bash
npm run build        # tsc → dist/
npm test             # 단위 테스트 (18개)
npm run test:unit    # 단위 테스트만
npm run test:int     # 통합 테스트 (CLI 명령어 8개)
npm run test:all     # 단위 + 통합 전체
npm run typecheck    # tsc --noEmit
npm run dev          # tsc --watch

# 개발 서버 (자동 리로드)
npm run dev:viewer   # http://localhost:3000 (Three.js 뷰어)
npm run dev:sync     # ws://localhost:8080 (WebSocket sync)

# 패키지로 설치 (로컬)
npm pack             # space-network-0.1.0.tgz 생성
```

---

## 13개 프리셋 템플릿 (v2.0 리뉴얼)

| 유형 | 템플릿 | 콘셉트 | 객체수 | 상호작용 |
|------|--------|--------|--------|----------|
| education | 스마트 강의실 | AI 강사 + 홀로그램 화이트보드 | 20 | 6 |
| education | 퀀텀 연구소 | 양자 컴퓨터 + 홀로그램 현미경 | 18 | 7 |
| education | 아틀란티스 서재 | 해저 도서관 + 개인 학습 포드 | 20 | 6 |
| collaboration | 오디세이 회의실 | 지구 궤도 + AI 회의록 | 18 | 7 |
| collaboration | 무한 캔버스 스튜디오 | 벽면 전체 연결 화이트보드 | 16 | 9 |
| collaboration | 이데아 클라우드 | 구름 위 아이디어 생츄어리 | 14 | 7 |
| exhibition | 에테르 갤러리 | 무중력 전시 + AI 큐레이터 | 19 | 6 |
| exhibition | 노바 쇼케이스 | 3층 제품 런칭 쇼케이스 | 17 | 7 |
| simulation | 아크로폴리스 훈련장 | 고대 도시 장애물 코스 | 19 | 7 |
| simulation | 스텔라리스 함교 | 6인 협력 우주선 시뮬레이터 | 14 | 9 |
| simulation | 제네시스 샌드박스 | 세계 창조 지형/생태계 편집 | 13 | 9 |
| social | 네뷸라 라운지 | 성운 라운지 + 감정 조명 | 18 | 9 |
| social | 크리스탈 이벤트 홀 | 수정 cavern 이벤트 홀 (200인) | 15 | 8 |

---

## 환경 변수

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `OPENAI_API_KEY` | 선택 | - | LLM 기반 공간 생성 시 필요 |
| `LLM_MODEL` | 선택 | `gpt-4o` | 사용할 LLM 모델명 |

---

## Phase 진행 상태

전체 12개 Phase가 완료되었으며, `phases/` 디렉터리에 모든 진행 상태가 기록되어 있다.

```bash
# 전체 phase 상태
cat phases/index.json

# 특정 phase 상세
cat phases/3-context-engine/index.json

# 완료된 phase 요약
cat phases/baselines/3-context-engine.json
```

---

## 라이선스

MIT
