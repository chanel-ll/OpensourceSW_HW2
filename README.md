# Research Tracker

관심 있는 **연구실·기업 연구팀·연구자**를 등록하면 **최근 2년 논문**을 자동으로 모아 소스별 탭으로 정리하고,
**매주 새 논문·게재 확정·정보 변경**을 Weekly Paper로 알려주며, 논문 노트·내 연구 프로젝트·**3D 연구 지도(Research World)**까지
한곳에서 관리하는 개인용 로컬 웹앱입니다.

- 수집: 무료 공개 학술 API(OpenAlex, Semantic Scholar, arXiv, 선택적으로 DBLP). Google Scholar 스크래핑은 하지 않습니다.
- 키워드·분류·그래프: KeyBERT + 소형 문장 임베딩 모델(CPU 전용) + scikit-learn. **LLM 없이** 동작합니다.
- 요약: OpenAI 호환 LLM 게이트웨이(예: ChatKHU API Gateway). **요약 버튼을 누른 논문과 소스 탭 이름 생성에만** 호출하고, 결과는 저장해 다시 호출하지 않습니다. 키가 없어도 요약만 꺼지고 나머지는 모두 동작합니다.
- 노트: 마크다운 파일로 저장되어 **Obsidian vault**로도 열 수 있습니다.

## 주요 기능

| 화면 | 내용 |
| --- | --- |
| 소스 추가 | 연구실 페이지 링크 → PI 이름 제안 → 학술 API의 저자 후보(소속·최근 논문 3편)에서 **직접 확정**(동명이인 방지) → 최근 2년 논문 수집 |
| 소스 탭 | "기관 · 연구실명 · 주력 분야" 탭 이름, 연도/학회/키워드 필터와 검색, "World에 포함" 토글 |
| 논문 카드 | 학회·저널, 키워드 칩, 링크, 요약 · ⭐ 관심 표시 · 프로젝트에 추가 · 숨기기. 제목을 누르면 논문 노트 |
| Weekly Paper | 7일마다 재조회해 `NEW`·`ACCEPTED`·`UPDATED` 배지, 소스별/키워드별 묶기, 읽음 처리. 앱 실행 시 7일이 지났으면 자동 실행 |
| Library | ⭐ 관심 표시한 논문 모음. 직접 만든 그룹(한 논문이 여러 그룹 가능)으로 정리, 미분류 보기, 검색·정렬, 여러 편 선택해 한 번에 그룹 추가/빼기 |
| 논문 노트 | 자동 정보(헤더·키워드·분야·abstract·AI 요약) + **내 메모**(마크다운, 자동 저장, `[[논문 제목]]` 자동완성) + 관련 논문(인용/피인용/의미 유사) + 사용처 + 백링크 |
| My Research | 프로젝트(상태: 아이디어/진행 중/투고 준비/완료) · 노트 여러 개 · 레퍼런스(역할 태그·메모, arXiv/DOI/제목 붙여넣기) · **BibTeX 내보내기** |
| Research World | ⭐ 논문 + "World에 포함" 소스 + 프로젝트 레퍼런스를 **분야(은하) › 세부 분야(성단) › 논문(별)**로 자동 분류한 3D 그래프. 엣지 4종(인용·의미 유사·같은 소스/공저자·수동 링크) + 프로젝트 노드(◆). 호버 카드, 클릭 시 노트, 분야 확대, 검색, 필터, 줌 단계별 라벨, **2D 전환**. 분야 이름 변경·논문 이동·분야 합치기는 재분류 때도 유지 |

## 요구 사항

- Windows 10/11 + PowerShell (macOS/Linux도 경로만 바꾸면 동작)
- Python 3.11 이상 (3.13에서 검증), Node.js 20.19 이상 (24에서 검증)
- 인터넷 연결 (학술 API, 최초 1회 모델 다운로드)
- 3D 보기는 WebGL이 필요합니다. 브라우저 하드웨어 가속이 꺼져 있으면 자동으로 2D로 표시됩니다.

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

키워드 추출과 분류용 임베딩에 [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)(약 90MB, CPU)를 사용합니다.
첫 논문 수집 때 프로젝트의 `models/` 폴더로 **자동 다운로드**되며, 이후에는 네트워크 없이 불러옵니다. 미리 받아 두려면:

```powershell
.\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', cache_folder='models')"
```

다른 모델을 쓰려면 `config.yaml`의 `keywords.model`을 바꿉니다. (모델을 바꾸면 `data/`를 지우고 다시 수집하세요. 임베딩 차원이 달라집니다.)

## LLM(요약) 설정 — 선택

`.env`를 열어 값을 채웁니다. 비워 두면 요약 버튼만 비활성화되고 이유가 화면에 표시됩니다.

```env
LLM_BASE_URL=https://<게이트웨이 주소>/v1     # OpenAI 호환 주소를 /v1까지
LLM_API_KEY=<발급받은 키>
LLM_MODEL=gpt-5.4-nano                       # 게이트웨이가 제공하는 경량 모델
```

- LLM에는 공개 정보(논문 제목·abstract, 탭 이름 생성 시 연구실 페이지 제목·기관·저자·대표 키워드)만 전송됩니다.
- **논문 메모와 프로젝트 노트는 절대 전송되지 않습니다.**
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

- 기존 DB로 처음 실행하면 새 열이 자동 추가되고, 임베딩이 없는 논문은 백그라운드로 계산됩니다(상단 진행 표시줄).
- 인용 관계는 수집 시 OpenAlex에서 함께 받아오므로, 예전에 수집한 소스는 **다시 수집**하면 인용 엣지가 채워집니다.

## Docker로 실행

`main` 브랜치에 push하면 GitHub Actions(`.github/workflows/ci.yml`)가 이미지를 빌드해 Docker Hub에 올립니다.
이미지에는 프론트엔드 빌드와 임베딩 모델(고정 revision)이 포함되어 있고, 빌드 중 모델이 오프라인으로 정상 로드되는지 검증합니다.

```powershell
docker pull <DockerHub 사용자명>/paper-universe:latest
docker run -d --name paper-universe -p 8000:8000 `
  --env-file .env `
  -v paper-universe-data:/app/data -v paper-universe-notes:/app/notes `
  <DockerHub 사용자명>/paper-universe:latest
```

브라우저에서 **http://127.0.0.1:8000** 을 엽니다(UI와 API가 한 포트). `--env-file .env`는 LLM 요약을 쓸 때만 필요합니다.
DB와 노트는 볼륨(`paper-universe-data`, `paper-universe-notes`)에 남으므로 이미지를 새로 받아도 유지됩니다.
개인 설정을 쓰려면 `-v ${PWD}/config.yaml:/app/config.yaml:ro`를 추가하세요.

직접 빌드: `docker build -t paper-universe .`

CI 설정: GitHub 저장소 Settings → Secrets and variables → Actions에 `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`(Docker Hub Access Token, Read & Write)을 등록합니다.

### 자동 배포 (self-hosted runner)

CI가 이미지를 Docker Hub에 올리면 `.github/workflows/deploy.yml`이 같은 PC의 self-hosted Windows 러너에서
그 이미지(`sha-<커밋>`)를 받아 로컬 컨테이너 `paper-universe`를 교체합니다.

- 접속: **http://127.0.0.1:8090** · 재시작 정책 `unless-stopped`(Docker Desktop이 켜지면 자동 실행)
- 데이터·노트는 Docker 볼륨(`paper-universe-data`, `paper-universe-notes`)에 남아 재배포해도 유지됩니다.
- 새 컨테이너가 2분 안에 응답하지 않으면 로그를 남기고 이전 이미지로 자동 롤백합니다.
- 러너 PC의 `%USERPROFILE%\.paper-universe\.env`(LLM 키)와 `config.yaml`이 있으면 컨테이너에 적용됩니다(저장소에는 올라가지 않음).
- 필요 조건: 러너(`run.cmd` 또는 서비스)와 Docker Desktop 실행 중. Actions 탭의 "Deploy" → Run workflow로 수동 재배포도 가능합니다.

## 노트 파일 (Obsidian 호환)

```
notes/papers/<논문 제목>.md               논문별 내 메모 (자동 정보는 쓰지 않음)
notes/projects/<프로젝트>/<노트>.md        프로젝트 노트
notes/.trash/                             삭제한 노트·프로젝트 폴더 (영구 삭제하지 않음)
```

- `[[논문 제목]]` 링크는 대소문자·문장부호와 무관하게 앱 안의 논문으로 연결되고, Research World의 "수동 링크" 엣지가 됩니다.
- `config.yaml`의 `notes_dir`를 Obsidian vault 안의 폴더로 지정하면 vault에서 바로 열고 편집할 수 있습니다(파일이 원본).

## 설정 (`config.yaml`)

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `contact_email` | `""` | 학술 API에 보내는 User-Agent의 연락처(OpenAlex polite pool). 원할 때만 입력 |
| `lookback_days` / `update_interval_days` | 730 / 7 | 수집 기간(최근 2년) / Weekly 업데이트 주기 |
| `keywords.model`, `keywords.top_n` | MiniLM-L6-v2, 4 | 키워드·임베딩 모델과 키워드 개수 |
| `sources.*` | 모두 `true` | API별 on/off. DBLP는 자동 요청에 봇 확인 페이지를 반환하는 경우가 많아 `dblp: false` 권장 |
| `notes_dir` | `notes` | 마크다운 노트 폴더 |
| `world.assign_threshold` | 0.3 | 새 논문이 기존 세부 분야에 들어가는 최소 유사도. 미만이면 "새 세부 분야 후보" |
| `world.candidate_min`, `similar_top_k`, `similar_min` | 3, 3, 0.5 | 후보 알림 기준, 의미 유사 엣지 수와 최소 유사도 |

선택 API 키(`.env`): `OPENALEX_API_KEY`(무료, 키가 없으면 IP당 작은 일일 예산 공유 — 소스가 많으면 권장), `S2_API_KEY`(Semantic Scholar 호출 제한 완화).

## 동작 메모

- 외부 API가 429/5xx를 반환하면 지수 백오프로 재시도하고, 실패 원인은 화면과 `logs/app.log`에 남습니다. 봇 확인 페이지는 우회하지 않습니다.
- 실행 중 생성되는 `data/`(SQLite), `logs/`, `models/`, `notes/`는 모두 `.gitignore` 대상입니다.

## 폴더 구조

```
backend/app/
  settings.py   .env + config.yaml          models.py   SQLite 스키마 + 자동 열 추가
  collect.py    학술 API·병합·Weekly 변화 감지·레퍼런스 조회    keywords.py  KeyBERT·임베딩 (CPU)
  notes.py      마크다운 노트 파일·[[링크]]    world.py    분류·레이아웃·엣지
  bibtex.py     BibTeX 내보내기               llm.py      게이트웨이 클라이언트    main.py  FastAPI 라우트
Dockerfile, .dockerignore, .github/workflows/ci.yml   컨테이너 이미지 · CI
frontend/src/
  App.tsx (레이아웃·라우팅)  SourceView  AddSource  Weekly  Library  PaperCard  PaperNote  Projects  World  MarkdownEditor  api.ts
```
