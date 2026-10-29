# Research Tracker

관심 있는 **연구실·기업 연구팀·연구자**를 등록하면 그들의 **최근 2년 논문**을 자동으로 모아 소스별 탭으로 정리하고,
**매주 새로 나온 논문·게재 확정·정보 변경**을 Weekly Paper 화면에 모아 보여주는 개인용 로컬 웹앱입니다.

- 수집: 무료 공개 학술 API(OpenAlex, Semantic Scholar, arXiv, 선택적으로 DBLP). Google Scholar 스크래핑은 하지 않습니다.
- 키워드: KeyBERT + 소형 문장 임베딩 모델(CPU 전용, GPU 불필요)
- 요약: OpenAI 호환 LLM 게이트웨이(예: ChatKHU API Gateway). **요약 버튼을 누른 논문과 소스 탭 이름 생성에만** 호출하고, 결과는 저장해 다시 호출하지 않습니다. LLM 키가 없어도 요약 기능만 꺼지고 나머지는 모두 동작합니다.

> 현재 버전은 P0 단계(소스 등록, 2년치 수집, 소스 탭, 논문 카드, 자동 키워드, 요약, Weekly Paper)입니다.
> 논문 노트·My Research(P1), Research World 3D 그래프(P2)는 메뉴에 "준비 중"으로 표시됩니다.

## 주요 기능

| 화면 | 내용 |
| --- | --- |
| 소스 추가 | 연구실 페이지 링크 → PI 이름 제안 → 학술 API의 저자 후보(소속·최근 논문 3편)에서 **직접 확정**(동명이인 방지) → 최근 2년 논문 수집 |
| 소스 탭 | "기관 · 연구실명 · 주력 분야" 탭 이름, 등록 저자·논문 수·대표 키워드, 연도/학회/키워드 필터와 제목 검색 |
| 논문 카드 | 제목, 저자(등록 저자 강조), 학회·저널(미게재 시 arXiv preprint), 키워드 칩, 링크, 요약·관심 표시·숨기기 |
| Weekly Paper | 7일마다 재조회해 `NEW`·`ACCEPTED`·`UPDATED` 배지로 표시, 소스별/키워드별 묶기, 읽음 처리. 앱 실행 시 마지막 업데이트가 7일 이상 지났으면 자동 실행 |

## 요구 사항

- Windows 10/11 + PowerShell (macOS/Linux도 경로만 바꾸면 동작)
- Python 3.11 이상 (3.13에서 검증)
- Node.js 20.19 이상 (24에서 검증)
- 인터넷 연결 (학술 API, 최초 1회 모델 다운로드)

## 설치 방법

PowerShell에서 이 저장소 폴더로 이동한 뒤 실행합니다. Python 패키지는 프로젝트 안의 `.venv`에만 설치됩니다.

```powershell
# 1) Python 가상환경과 백엔드 패키지 (CPU 전용 PyTorch 포함)
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 프론트엔드 패키지
cd frontend; npm install; cd ..

# 3) 설정 파일 만들기
Copy-Item .env.example .env
Copy-Item config.example.yaml config.yaml
```

`py` 명령이 없으면 `python -m venv .venv`를 사용하세요.

## 모델 준비 방법

키워드 추출에는 [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)(약 90MB, CPU)를 사용합니다.
첫 논문 수집 때 프로젝트의 `models/` 폴더로 **자동 다운로드**되며, 이후에는 네트워크 없이 불러옵니다.
미리 받아 두려면 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', cache_folder='models')"
```

다른 모델을 쓰려면 `config.yaml`의 `keywords.model`을 바꿉니다.

## LLM(요약) 설정 — 선택

`.env`를 열어 값을 채웁니다. 비워 두면 요약 버튼만 비활성화되고 이유가 화면에 표시됩니다.

```env
LLM_BASE_URL=https://<게이트웨이 주소>/v1     # OpenAI 호환 주소를 /v1까지
LLM_API_KEY=<발급받은 키>
LLM_MODEL=gpt-5.4-nano                       # 게이트웨이가 제공하는 경량 모델
```

- LLM에는 공개 정보(논문 제목·abstract, 탭 이름 생성 시 연구실 페이지 제목·기관·저자·대표 키워드)만 전송됩니다.
- 키가 거부되거나 크레딧이 소진되면 요약만 꺼지고, 백엔드를 재시작하면 다시 시도합니다.
- `.env`는 `.gitignore`에 포함되어 있으니 키를 커밋하지 마세요.

## 실행 방법

PowerShell 창 2개를 열고, 둘 다 이 저장소 폴더에서 시작합니다.

```powershell
# 창 1 — 백엔드 (http://127.0.0.1:8000)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
# 창 2 — 프론트엔드 (http://127.0.0.1:5173)
cd frontend; npm run dev
```

브라우저에서 **http://127.0.0.1:5173** 을 열고, 왼쪽 사이드바의 **+ 소스 추가**로 시작합니다. 종료는 각 창에서 `Ctrl+C`.

## 설정 (`config.yaml`)

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `contact_email` | `""` | 학술 API에 보내는 User-Agent의 연락처(OpenAlex polite pool). 원할 때만 입력 |
| `lookback_days` | `730` | 수집 기간(최근 2년) |
| `update_interval_days` | `7` | Weekly 업데이트 주기 |
| `keywords.model`, `keywords.top_n` | MiniLM-L6-v2, 4 | 키워드 모델과 개수 |
| `sources.*` | 모두 `true` | API별 on/off. DBLP는 자동 요청에 봇 확인 페이지를 반환하는 경우가 많아 `dblp: false` 권장 |

선택 API 키(`.env`): `OPENALEX_API_KEY`(무료, 키가 없으면 IP당 작은 일일 예산 공유 — 소스가 많으면 권장), `S2_API_KEY`(Semantic Scholar 호출 제한 완화).

## 동작 메모

- 외부 API가 429/5xx를 반환하면 지수 백오프로 재시도하고, 실패 원인은 소스 탭·Weekly 화면과 `logs/app.log`에 남습니다.
- 봇 확인 페이지를 반환하는 사이트는 우회하지 않고 건너뜁니다.
- 실행 중 생성되는 파일: `data/`(SQLite DB), `logs/`, `models/` — 모두 `.gitignore` 대상입니다. 처음부터 다시 시작하려면 `data/` 폴더를 지웁니다.

## 폴더 구조

```
backend/app/
  settings.py   .env + config.yaml 로드, 로깅
  models.py     SQLite 스키마 (Source, Author, Paper, PaperSource, UpdateRun, PaperChange)
  collect.py    학술 API 클라이언트(백오프), 저자 후보, 병합, Weekly 변화 감지
  keywords.py   KeyBERT (CPU)
  llm.py        OpenAI 호환 게이트웨이 클라이언트 (요약, 탭 이름)
  main.py       FastAPI 라우트, 백그라운드 작업, 시작 시 자동 업데이트
frontend/src/
  App.tsx       상단 바 + 사이드바 + 본문 레이아웃
  AddSource.tsx SourceView.tsx Weekly.tsx PaperCard.tsx api.ts index.css
requirements.txt  .env.example  config.example.yaml
```
