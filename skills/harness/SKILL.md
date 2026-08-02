---
name: harness
description: Run the autonomous Plan → Execute → Evaluate development loop and design/scaffold the phases/ harness structure using the bundled harness framework. Use when the user asks to develop or design a project per a step-based harness framework, run a phased development loop, create phase directories, continue step-based work, or drive autonomous multi-step development.
---

# Harness Development Loop

하네스 프레임워크에 따라 프로젝트를 개발/설계한다. **이 스킬 폴더 안에 실제 프레임워크
복사본이 들어 있다** — `framework/` 아래 `engine/`, `scripts/`, `templates/`, `docs/`.
다른 프로젝트에서 이 스킬을 써도 이 번들 프레임워크를 그대로 활용한다.

> 번들 프레임워크 루트 = 베이스(스킬) 디렉터리 아래 `framework/`.
> 모든 스크립트 호출은 이 루트 기준으로 한다. (`python <framework>/scripts/...`)

## 0. 부트스트랩 — phases/ 구조 설계/생성

사용자가 "하네스 프레임워크에 따라 설계해줘"라고 하고 대상 프로젝트에 `phases/`가 없으면 먼저 구조를 만든다. 대상 프로젝트에 자체 `scripts/`·`engine/`가 있으면 그걸 우선, 없으면 번들 프레임워크를 쓴다.

1. **목표 명세** `goal.json` 생성 (없으면) — `goal`, `success_criteria[]`, `auto_checks[]`(예: `npm test`), `max_phases`, `stagnation_limit`. 사용자와 협의해 확정.
2. **phase 스캐폴드**: 번들 스크립트를 대상 프로젝트 루트에서 실행
   ```bash
   python <framework>/scripts/scaffold_phase.py {phase-dir} --project {name} --steps s0 s1 ...
   ```
   (또는 위 절차에 따라 `phases/index.json`, `phases/{task}/index.json`, `module-map.json`, `stepN.md` 생성)
3. `phases/baselines/` 디렉터리 생성.
4. **git 초기화**(없을 때만 `git init` 1회) 후 첫 커밋 전에 `.gitignore` 작성.
5. 모듈-페르소나가 있으면 `docs/modules/registry.json` + 각 모듈 `MODULE.md` 초안(번들 `templates/` 사용).
6. 생성 후 형식 검증:
   ```bash
   python <framework>/scripts/validate_phase.py {phase-dir}
   ```
   단, `--root`가 대상 프로젝트 루트를 가리키도록 지정.

*스캐폴드 템플릿·MODULE.md 포맷의 진본은 번들 `framework/templates/` 및 `framework/docs/MODULES.md`에 있다.*

## 1. 상태 확인

- `phases/index.json`, `phases/project-manifest.json`(있으면), 현재 phase의 `index.json`/`module-map.json`을 읽는다.
- 상태가 어긋나면 동기화하고 보고. 첫 `pending` step부터 진행.

## 2. 계획 (Plan)

- 한 번에 한 step. `completed`면 다음 step, `blocked`면(pending blocking-fix가 있으면) 그것부터.
- 남은 phase가 없거나 요청이 범위를 벗어난 새 기능이면 **다음 phase를 설계**(append-only, 기존 step 번호 재정렬 금지).

## 3. step 실행 (Execute)

- `stepN.md` 지시서만 수행. `owned_paths`만 수정, 다른 모듈/`forbidden_paths`는 섞지 않는다.
- 이전 구현 전체를 재탐색하지 말고 `module-map.json`·baseline·public contract를 우선.
- **객관적 완료 게이트**: 실행 가능한 AC 명령 + `goal.json`의 `auto_checks`를 실제 실행해 통과해야 `completed`로 인정.
- **실패 시(최대 3회)**: 무작정 재실행이 아닌, 변경 파일 diff + 실패 AC를 피드백 삼아 해당 결함만 고쳐 재작성.
- **blocked**: 원인이 범위 밖(contract/모듈 문제)이면 `blocked`로 기록(`blocked_reason`)하고 `blocking-fix`/`contract-change` step을 append해 해소 → 원 step을 `pending`으로 복구.
- **완료 직후 step 단위 커밋**: `feat({project}/step{N}): {name} — {한 줄 요약}`.
- 3회에도 AC 통과 불가/해소 불가면 `error`로 기록(`error_message`)하고 중단.

## 4. phase 마감

마지막 step 완료 시:
- `phases/index.json`의 해당 phase를 `completed`로 갱신.
- baseline `phases/baselines/{phase}.json` 작성 (다음 phase가 재탐색하지 않도록 모듈/public surface/contracts/routes/integration 요약).
- `phases/project-manifest.json` 갱신.
- `git tag {project}-phase{N}-done`.

## 5. 평가 (Evaluate)

`goal.json`의 `success_criteria`·`auto_checks` 대비 판정:
- **done**: 전부 충족 + auto_checks 통과 → 종료.
- **continue**: 진전 있음 → 다음 phase.
- **stagnated**: 실질 진전 없음 → 3회 연속이면 중단.

## 배치 실행 (헤드리스)

번들 프레임워크로 헤드리스 자동 루프를 돌릴 수 있다:
```bash
python <framework>/scripts/loop.py --root {대상 프로젝트 루트} --goal goal.json --backend <name>
```

## 금지사항

- `phases/` SSOT를 삭제·초기화·재스캐폴드하지 않는다 (진행 중이면 이어서).
- 기존 step 번호를 재정렬/중간 삽입하지 않는다. 새 step은 항상 append.
- LLM 자가 보고 "completed"를 맹신하지 않는다 — 실행 가능한 검증이 있으면 통과 확인 후 인정.
- 스킬의 번들 프레임워크(`framework/`)를 프로젝트 코드처럼 임의 수정하지 않는다.
