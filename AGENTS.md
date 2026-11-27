# AGENTS.md — Research Tracker (paper_universe)

이 저장소에서 작업하는 모든 코딩 에이전트(와 사람)가 지켜야 할 규칙입니다.
작업 계획과 규칙 목록은 [docs/plan.md](docs/plan.md)에 있습니다.

## 1. 개발 순서 (TDD)
1. 바꾸려는 동작을 "X이면 Y여야 한다" 한 문장으로 쓴다.
2. 그 문장을 검사하는 테스트를 먼저 만들고, **실패하는 것을 확인한 뒤** `test: ...` 커밋을 남긴다.
3. 테스트를 통과시키는 최소한의 코드를 `feat: ...` (버그면 `fix: ...`) 커밋으로 남긴다.
4. 동작을 바꾸지 않는 정리는 테스트가 통과하는 상태에서 `refactor: ...`로 따로 커밋한다.
5. 테스트를 지우거나 약하게 바꿔서 통과시키지 않는다.

## 2. 테스트 규칙
- 실행: `pip install -r requirements-dev.txt` 후 `pytest` (저장소 루트에서).
- **테스트는 오프라인에서 통과해야 한다.** 실제 LLM, 학술 API, 인터넷을 호출하지 않는다.
  - LLM은 가짜 `post` 함수를 주입한다 (`llm.Client(post=fake_post)`).
  - 현재 시각은 함수 인자로 받는다 (`update_due(last, now)`). 테스트에서 `datetime.now()`를 쓰지 않는다.
- 테스트는 무거운 모델(torch, KeyBERT)을 불러오지 않는다. 키워드가 필요하면 인자로 넘긴다.
- 핵심 규칙은 DB·네트워크가 없는 순수 함수 모듈에 둔다 (`summary_rules.py`, `tabname.py`, `changes.py`, `schedule.py`, `bibtex.py`).

## 3. LLM 사용 규칙
| 용도 | 언제 | 보내는 것 | 실패 시 |
|---|---|---|---|
| 논문 요약 (핵심) | 사용자가 "요약"을 누를 때만 | 제목, abstract | abstract 첫 문장 + 키워드로 만든 대체 요약 (`used_fallback`) |
| 소스 탭 이름 | 소스 등록 시 한 번 | 페이지 제목, 기관, 저자명, 자동 키워드 (모두 공개 정보) | 규칙 기반 이름 |

- LLM 응답은 **검증을 통과해야만 저장**한다. 형식이 틀리면 버리고 이유를 기록한다.
- JSON이 아닌 응답은 **정확히 한 번만** 다시 요청한다.
- LLM 요약은 한 번 저장되면 다시 호출하지 않는다. 대체 요약만 나중에 LLM 요약으로 교체할 수 있다.
- 키가 없거나 크레딧이 없어도 서비스 전체가 동작해야 한다. LLM 실패가 500 오류가 되면 안 된다.
- 개인 노트, My Research 내용, 사용자 설정은 **절대 LLM에 보내지 않는다.**

## 4. 비밀값과 개인 정보
- API 키는 환경 변수로만 읽는다: `FACTCHAT_API_KEY` (없으면 `LLM_API_KEY`).
- 키, 토큰, 이메일을 코드·테스트·문서·커밋·이미지에 넣지 않는다. 테스트에는 `"test-key"` 같은 가짜 값만 쓴다.
- `.env`, `config.yaml`, `data/`, `notes/`, `models/`, `logs/`, 러너 파일은 커밋하지 않는다 (`.gitignore`).
- 봇 차단(예: DBLP Anubis)을 우회하지 않는다. 막히면 그 소스를 건너뛴다.

## 5. Git과 배포
- main에 직접 push하지 않는다. `hw6/<주제>` 같은 기능 브랜치에서 작업하고 Pull Request로 병합한다.
- CI 순서: `test → build → deploy`. **test가 실패하면 build와 deploy는 실행되지 않는다.**
- PR에서는 test만 실행한다. 단, PR 실행은 PR 쪽 워크플로 파일을 쓰므로 `if` 조건은 보안 경계가 아니다.
  외부 PR은 저장소 설정 "Require approval for all external contributors"로 막는다 (self-hosted 러너 보호).
- 프롬프트에 구체적인 예시 이름을 넣지 않는다 (실제 실행에서 LLM이 예시 연구실명을 그대로 베꼈다).
- Action은 태그가 아니라 커밋 SHA로 고정한다.
- 배포 확인은 `/health`의 `version`이 새 커밋과 같은지로 한다. 다르면 이전 컨테이너로 되돌린다.
- 데이터는 Docker 볼륨(`paper-universe-data`, `-notes`)에 있으므로 재배포해도 남아야 한다.

## 6. 리뷰
- 기능을 병합하기 전에 서브에이전트 리뷰(정확성, 보안, 배포)를 받는다.
- 받아들인 지적마다 그것을 드러내는 테스트(`test:`)를 먼저 쓰고 고친다(`fix:`).
- 받아들이지 않은 지적은 이유를 `docs/review.md`에 남긴다.
