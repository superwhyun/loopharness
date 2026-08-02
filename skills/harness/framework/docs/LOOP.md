# 자율 개발 루프 (Loop Engineering)

이 문서는 이 저장소의 자율 루프 워크플로우 원문이다.
AI 에이전트(Claude Code, Codex, Kimi Code CLI, OpenCode, Gemini 등)가 루프를 직접 오케스트레이션할 때 이 문서를 기준으로 작업한다.
`scripts/loop.py`는 에이전트 없이 완전 배치 실행할 때만 사용한다.

**사람 개입 지점은 Phase 0(목표 확정) 단 한 번뿐이다.** `goal.json`이 확정된 이후에는 phase 결정 → step 실행 → phase 리뷰 게이트(2.5단계) → 평가를 사람 승인 없이 반복하며, `stagnated`로 막히는 경우에만 사람에게 알린다.

---

## 전제 조건

반드시 먼저 읽어라:
1. `AGENTS.md` (또는 SKILL.md 기반 진입 시 `SKILL.md`)
2. `HARNESS.md` — 특히 섹션 C(Step 설계) 항목 11의 3회 반복 자가검증 규칙

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
- `HARNESS.md` 섹션 C (Step 설계)의 규칙을 따른다
- phase 목록과 각 phase의 step 구성은 **`HARNESS.md` 섹션 C 항목 11의 3회 반복 자가검증**(1회차: 빠진 것 없어? / 2회차: 완벽한 것 같아? / 3회차: 이대로 구현 바로 하면 돼?)을 그대로 적용한다. 판정만 하고 넘어가지 않는다 — 매 회차 실제 파일 내용을 고쳐 쓴다.
- `python3 skills/harness/framework/scripts/scaffold_phase.py {phase-dir} --project {name} --steps step1 step2 ...` 로 파일 생성
- 설계가 끝나면 사람의 승인을 기다리지 않고 바로 2단계로 진행한다. (사람 개입은 Phase 0의 목표 확정 한 번뿐이다 — 그 이후 phase 결정·실행·리뷰·평가 사이클은 전부 자동 진행한다.)

### 2단계 — Phase 실행

두 가지 방법 중 선택한다:

**방법 A — 배치 실행 (권장, 빠름)**
```bash
python3 skills/harness/framework/scripts/execute.py {phase-dir} --root {project-root}
```
execute.py가 step을 순차 실행하고 자가 교정한다. 완료 후 결과를 요약한다.

**방법 B — 직접 실행 (상세 제어가 필요할 때)**
`HARNESS.md` 섹션 D (실행)의 규칙을 따라 step을 하나씩 직접 수행한다.

**실행 루프 규칙 (방법 A·B 공통):**
- 각 step은 산출물을 작성한 뒤 **step의 AC 전체를 검증**한다.
- AC를 모두 통과하면 그 step을 `completed`로 만들고 다음 step으로 간다.
- AC를 통과하지 못하면 **단순 재실행이 아니라 AC가 지목한 결함 항목을 고쳐 산출물을 재작성**한 뒤 다시 AC를 검증한다.
- 재작성은 **최대 3회**. 3회 내에 통과하지 못하면 그 step을 `blocked`로 기록하고, 원인이 step 범위 밖이면 `blocking-fix`/`contract-change` step을 append해 해소한다.
- 실행 루프는 **무한정 돌리지 않는다** — AC가 루프의 종료 신호다.

### 2.5단계 — Phase 리뷰 게이트 (사람 개입 없이 자동 반복)

phase의 모든 step이 `completed`가 되면, 다음 phase로 넘어가기 전에 이 phase의 변경 사항을 반드시 리뷰한다. 판정을 사람에게 묻지 않고 에이전트가 직접 반복한다.

1. `framework/docs/REVIEW.md`의 리뷰 워크플로우를 이 phase 시작 이후의 diff(마지막 phase 태그 이후 변경분) 전체에 대해 실행한다.
2. 리뷰 결과가 "no findings"면 리뷰 통과 — 3단계(평가)로 진행한다.
3. findings가 있으면:
   - 지적된 항목을 해소하는 step을 현재 phase에 append한다 (`kind: "review-fix"`, 기존 step 번호는 재정렬하지 않는다). 여러 findings는 하나의 review-fix step에 함께 묶어도 된다.
   - "2단계 — Phase 실행"의 규칙대로 그 step을 실행한다 (AC 게이트, 최대 3회 재작성 등 동일하게 적용).
   - 실행 후 다시 1번부터 리뷰를 반복한다.
4. 이 리뷰→수정 사이클은 phase당 **최대 3회**까지 자동 반복한다.
5. 3회 안에 findings가 모두 해소되면 리뷰 통과로 처리한다. 3회를 넘겨도 findings가 남아 있으면, 남은 항목을 `phases/baselines/{phase-dir}.json`의 `known_issues`에 기록하고 리뷰를 통과한 것으로 간주해 다음 단계로 진행한다 — 전체 루프를 사람 응답 대기로 멈추지 않는다.

### 3단계 — 평가

phase 리뷰 게이트를 통과한 뒤, 에이전트가 직접 판정한다:

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

OpenCode에 로컬 LLM을 연결한 상태라면 이 워크플로우를 그대로 사용할 수 있다.
배치 헤드리스 실행이 필요할 때는 `python3 skills/harness/framework/scripts/loop.py --backend {llm-name}` 을 사용한다.
`config.json`의 `local_api` 타입 백엔드 설정 방법은 `ARCHITECTURE.md` 참고.
