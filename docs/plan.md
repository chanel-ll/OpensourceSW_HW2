# HW6 계획 — Research Tracker를 제품 수준으로

코드를 고치기 전에 작성한 계획입니다. 작업 규칙은 [AGENTS.md](../AGENTS.md)에 있습니다.

## 서비스 한 줄 설명
관심 연구실을 등록하면 최근 2년 논문을 모아 주고, 매주 새 논문과 게재 확정을 알려주며,
사용자가 요청한 논문만 LLM으로 요약하는 개인 연구 트래커.

## 요구사항과 증거
| 영역 | 이 프로젝트에서 하는 것 | 증거 |
|---|---|---|
| Product | 실제로 쓰는 논문 트래커, README만 보고 실행 가능 | README, 실행 화면 |
| TDD | 아래 규칙 8개를 테스트 먼저 작성, LLM·네트워크는 가짜 함수로 대체 | `test:` → `feat:` 커밋 순서 |
| LLM | 논문 요약 호출, 응답 검증, 실패 시 대체 요약 | `tests/test_llm.py`, `tests/test_summary_rules.py` |
| DevOps | `test → build → deploy`, 테스트 실패 시 배포 중단, 키는 GitHub Secret | 막힌 실행, 성공한 실행 |
| Agent | AGENTS.md, 이 계획, 서브에이전트 리뷰 후 수정 | AGENTS.md, docs/plan.md, `fix:` 커밋 |
| GitHub | 기능 브랜치 → PR → 병합 | PR 링크 |

## 테스트로 고정할 규칙
| # | 규칙 (X이면 Y여야 한다) | 모듈 | 테스트 |
|---|---|---|---|
| 1 | LLM 요약에 `one_line`이 없거나 문자열이 아니거나 `contributions`가 3개를 넘으면 버리고 `bad_summary`를 기록한다 | `summary_rules.py` | `test_summary_rules.py` |
| 2 | LLM 응답이 JSON이 아니면 정확히 한 번만 다시 요청한다 | `llm.py` | `test_llm.py` |
| 3 | 키 없음, 두 번 실패, 시간 초과, 크레딧 소진이면 abstract 첫 문장 + 키워드로 대체 요약을 만들고 `used_fallback=True`로 표시한다 | `llm.py`, `summary_rules.py` | `test_llm.py` |
| 4 | 대체 요약은 다시 요약하면 LLM 요약으로 교체할 수 있고, LLM 요약은 저장 후 다시 호출하지 않는다 | `llm.py` | `test_llm.py` |
| 5 | LLM 탭 이름이 40자를 넘거나 "·" 형식이 아니면 규칙 기반 이름으로 바꾼다 | `tabname.py` | `test_tabname.py` |
| 6 | preprint가 학회 게재로 바뀌면 `ACCEPTED`, 한 API가 잠시 정보를 안 줘도 게재 정보는 되돌리지 않는다 | `changes.py` | `test_changes.py` |
| 7 | 마지막 업데이트 후 7일 이상 지났을 때만 자동 업데이트한다. 기록이 없으면 하지 않는다 | `schedule.py` | `test_schedule.py` |
| 8 | 저자·연도·첫 단어가 같은 논문이 여러 개여도 BibTeX 인용 키는 중복되지 않는다 | `bibtex.py` | `test_bibtex.py` |

1~5는 새 동작이라 테스트를 먼저 쓴다. 6~8은 기존 코드를 순수 함수로 분리하면서 테스트로 고정한다.

## LLM 사용처와 대체 동작
| LLM이 이렇게 하면 | 서비스는 이렇게 |
|---|---|
| JSON이 아닌 텍스트 | 한 번만 재요청 |
| 필수 필드 누락·형식 오류 | 응답을 버리고 버린 횟수 기록 |
| 두 번 실패·시간 초과·키 없음·크레딧 소진 | 대체 요약, 화면에 "대체 요약" 표시 |
| 탭 이름이 너무 길거나 형식이 틀림 | 규칙 기반 이름 |

- 운영 수치(LLM 호출, 실패, 버린 응답, 대체 동작 횟수)를 화면과 `/health`에 표시한다.
- 실제 LLM으로 한 번 실행해 보고, 그 결과에서 배운 점을 새 테스트로 추가한다.
- LLM에는 공개 정보(제목, abstract)만 보낸다.

## CI/CD
```
push / PR ─▶ test (GitHub 서버, ubuntu, 키 없음, pytest)
              └─ main push만 ─▶ build (내 PC 러너: 이미지 빌드·Docker Hub 업로드)
                                   └─▶ deploy (내 PC 러너: blue-green, /health 확인, 실패 시 롤백)
```
- `ci.yml`과 `deploy.yml`을 하나의 워크플로(job 3개)로 합친다.
- 테스트용 `requirements-dev.txt`에는 torch를 넣지 않는다.
- `FACTCHAT_API_KEY`는 deploy job에서만 컨테이너에 넘긴다.
- `/health`: `status`, `db`, `llm`, `version`, 운영 수치.

## 작업 순서
1. `hw6/plan`: AGENTS.md, 이 계획 → PR #1
2. `hw6/llm-contract`: 규칙 1~5 → PR #2
3. `hw6/pure-rules`: 규칙 6~8 → PR #3
4. `hw6/ci-gate`: 파이프라인 재구성, `/health`, Secret 연결 → PR #4
5. 일부러 깨진 테스트 push → 막힌 실행 캡처 → revert → 성공한 실행 캡처
6. `hw6/review-fixes`: 서브에이전트 리뷰 3개 → `test:` → `fix:` → PR #5
7. 보고서 2쪽 (규칙-테스트 표, LLM 대체 동작, 리뷰 결과)
8. 제출 전 최종 점검 (아래)

## 제출 전 최종 점검
| 항목 | 확인 방법 | 이 프로젝트에서 |
|---|---|---|
| 테스트가 코드보다 먼저 | `git log`에서 `test:` 커밋이 해당 `feat:` 커밋보다 앞에 있다 | `git log --oneline --reverse`로 규칙 1~8의 커밋 쌍 확인 |
| 테스트가 오프라인 | Wi-Fi를 끄고 `pytest`를 실행해도 통과한다 | 네트워크를 끊고 `pytest` 실행 |
| LLM이 안전하게 실패 | API 키를 빼고 서비스를 써도 동작한다 | 키 없이 컨테이너를 실행하고 요약 버튼 → 대체 요약 표시 |
| 배포 차단이 동작 | 깨진 테스트를 push하면 build와 deploy가 건너뛰어진다 | 5단계의 막힌 실행 화면 |
| 데이터가 남음 | 재배포 후 같은 계정으로 로그인한다 | 로그인이 없는 1인용 서비스이므로, 재배포 전후로 같은 소스·관심 논문·노트가 남아 있는지 확인 |
| 저장소에 비밀값 없음 | 저장소에서 키를 검색하면 결과가 없다 | 키 값으로 `git grep`과 `git log -p` 검색 → 0건 |
