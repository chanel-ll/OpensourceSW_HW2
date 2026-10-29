"""ChatKHU API Gateway (OpenAI-compatible) client. Only public paper data (title, abstract) is ever sent."""
import json
import logging
import re
import time

import httpx

from .settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

log = logging.getLogger("llm")
_disabled_reason = ""  # set when the gateway rejects the key or credit runs out; cleared on restart


class LLMError(Exception):
    pass


def status():
    if not LLM_BASE_URL or not LLM_API_KEY:
        return {"enabled": False, "model": LLM_MODEL, "reason": ".env에 LLM_BASE_URL / LLM_API_KEY가 설정되지 않았습니다."}
    if _disabled_reason:
        return {"enabled": False, "model": LLM_MODEL, "reason": _disabled_reason}
    return {"enabled": True, "model": LLM_MODEL, "reason": ""}


def available():
    return status()["enabled"]


def chat(messages, max_tokens=400):
    global _disabled_reason
    if not available():
        raise LLMError(status()["reason"])
    for attempt in range(4):
        try:
            r = httpx.post(f"{LLM_BASE_URL}/chat/completions", timeout=60,
                           headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                           json={"model": LLM_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens})
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 게이트웨이 연결 실패: {type(e).__name__}: {e}")
        body = r.text[:300]
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        if r.status_code in (401, 403):
            _disabled_reason = f"LLM API 키가 거부되었습니다 (HTTP {r.status_code})."
        elif r.status_code == 402 or re.search(r"credit|quota|insufficient|balance|크레딧", body, re.I):
            _disabled_reason = f"LLM 크레딧이 소진되었습니다 (HTTP {r.status_code})."
        elif r.status_code == 429 and attempt < 3:
            log.warning("LLM 429, backoff %ss", 2 ** attempt)
            time.sleep(2 ** attempt)
            continue
        log.error("LLM HTTP %s: %s", r.status_code, body)
        raise LLMError(_disabled_reason or f"LLM 호출 실패 (HTTP {r.status_code}): {body}")
    raise LLMError("LLM 호출 제한(429) — 재시도 후 실패")


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMError(f"LLM 응답을 JSON으로 해석할 수 없습니다: {text[:200]}")
    return json.loads(m.group(0))


def summarize(title, abstract):
    prompt = (
        "다음 논문의 제목과 abstract만 보고 JSON으로 답하세요.\n"
        '{"one_line": "한국어 한 문장 요약", "contributions": ["핵심 기여 (한국어, 최대 3개)"], '
        '"keywords": ["영어 키워드 3~5개"]}\n\n'
        f"Title: {title}\nAbstract: {abstract or '(abstract 없음)'}")
    data = _json(chat([{"role": "system", "content": "You are a concise research assistant. Output JSON only."},
                       {"role": "user", "content": prompt}]))
    return {"one_line": str(data.get("one_line", "")).strip(),
            "contributions": [str(c) for c in data.get("contributions", [])][:3],
            "keywords": [str(k) for k in data.get("keywords", [])][:5]}


def tab_name(page_title, institution, authors, keywords):
    prompt = ("연구 소스 탭 이름을 '기관 · 연구실명 · 주력 분야' 형식으로 한 줄만 출력하세요. 기관은 짧은 약칭(예: KAIST), "
              "주력 분야는 2~3단어 영어. 예: KAIST 비주얼컴퓨팅랩 · 3D Recon\n"
              f"페이지 제목: {page_title}\n기관: {institution}\n저자: {', '.join(authors)}\n대표 키워드: {', '.join(keywords)}")
    name = chat([{"role": "user", "content": prompt}], max_tokens=40).strip().strip('"').splitlines()[0]
    return name[:80]
