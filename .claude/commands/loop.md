# /loop — 자율 개발 루프

이 커맨드는 AI 에이전트(Claude Code, OpenCode, Codex, Gemini 등)가 루프를 직접 오케스트레이션한다.
`scripts/loop.py`는 에이전트 없이 완전 배치 실행할 때만 사용한다.

---

## 전제 조건

반드시 먼저 읽어라:
1. `/AGENTS.md`
2. `/docs/HARNESS.md`

---

## Phase 0 — 목표 확정

`goal.json`이 존재하면 이 단계를 건너뛴다.

존재하지 않으면 **아래 항목을 한 번에 하나씩 사용자에게 물어보며** goal.json을 완성한다.

```
1. 무엇을 만들 것인가? (한 문장)
2. 언제 "완성"이라고 할 수 있는가? (체크리스트 형태)
3. 자동으로 검증할 수 있는 명령이 있는가? (예: pytest, curl http://localhost:3000)
4. 최대 phase 수는? (기본 10)
5. 연속 정체를 몇 번까지 허용할 것인가? (기본 3)
```

정보가 모이면 아래 구조로 `goal.json`을 대상 프로젝트 루트에 저장하고 사용자에게 확인을 받는다.

```json
{
  "goal": "한 문장 설명",
  "success_criteria": ["기준 1", "기준 2"],
  "auto_checks": ["pytest", "npm test"],
  "max_phases": 10,
  "stagnation_limit": 3
}
```

확인 전까지 loop을 시작하지 않는다.

---

## 루프 본체

아래 싸이클을 `goal.json`의 `max_phases` 횟수까지 반복한다.

### 중단 조건 (매 반복 시작 시 확인)

- `phases/STOP` 파일이 존재하면 즉시 종료
- 완료된 phase 수가 `max_phases`에 도달하면 종료
- 연속 `stagnated` 판정이 `stagnation_limit`에 도달하면 종료
- 사용자가 "멈춰", "stop", "중단" 등을 입력하면 종료

### 1단계 — Phase 결정

`phases/index.json`을 읽어 `pending` 상태 phase가 있으면 그것을 사용한다.

없으면 에이전트가 다음 phase를 직접 설계한다:
- `goal.json`, `phases/project-manifest.json` (있으면), 완료된 phase baseline 내용을 참고
- `docs/HARNESS.md` 섹션 C (Step 설계)의 규칙을 따른다
- 초안을 만든 뒤 아래 관점으로 기본 5회 자기검토한다: 누락 요구사항, 성공 기준 충족, 모듈 경계·의존성, 실행 가능한 AC, 범위와 다음 세션 연속성. 매 회 완전한 수정안을 만든다.
- `python3 scripts/scaffold_phase.py {phase-dir} --project {name} --steps step1 step2 ...` 로 파일 생성
- 사용자에게 phase 계획을 간단히 요약하고 승인을 받는다

### 2단계 — Phase 실행

두 가지 방법 중 선택한다:

**방법 A — 배치 실행 (권장, 빠름)**
```bash
python3 scripts/execute.py {phase-dir} --root {project-root}
```
execute.py가 step을 순차 실행하고 자가 교정한다. 완료 후 결과를 요약한다.

**방법 B — 직접 실행 (상세 제어가 필요할 때)**
`docs/HARNESS.md` 섹션 D (실행)의 규칙을 따라 step을 하나씩 직접 수행한다.

### 3단계 — 평가

phase가 끝나면 에이전트가 직접 판정한다:

1. `goal.json`의 `auto_checks` 명령을 실행한다
2. `success_criteria`를 하나씩 확인한다
3. 파일 변화, 테스트 결과, 코드 상태를 종합한다
4. 아래 셋 중 하나로 판정한다:

| 판정 | 조건 |
|------|------|
| `done` | 모든 success_criteria 충족 |
| `continue` | 진전이 있고 아직 부족함 |
| `stagnated` | 실질적 변화 없음 (같은 오류 반복, 파일 미변경 등) |

판정 결과와 다음 단계 제안을 사용자에게 알린다.

- `done` → 루프 종료, 완료 요약 출력
- `continue` → 다음 반복으로
- `stagnated` → stagnation 카운터 증가, 사용자에게 방향 전환 제안

---

## 루프 종료 후

```
✓ 총 완료 phase: N
✓ 달성된 success_criteria: [목록]
✗ 미달성: [있으면 목록]
다음 단계 제안: [있으면]
```

---

## 로컬 LLM (OpenCode) 사용 시

OpenCode에 로컬 LLM을 연결한 상태라면 이 커맨드를 그대로 사용할 수 있다.
배치 헤드리스 실행이 필요할 때는 `python3 scripts/loop.py --backend {llm-name}` 을 사용한다.
`config.json`의 `local_api` 타입 백엔드 설정 방법은 `docs/ARCHITECTURE.md` 참고.
