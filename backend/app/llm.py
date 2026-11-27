"""ChatKHU API Gateway (OpenAI-compatible) client. Only public paper data (title, abstract) is ever sent.
The network call (`post`) is injected so tests never reach a real LLM."""
import json
import logging
import re
import time

import httpx

from . import summary_rules
from .settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


class Client:
    def __init__(self, base_url, api_key, model, post=httpx.post, sleep=time.sleep):
        self.base_url, self.api_key, self.model = (base_url or "").rstrip("/"), api_key, model
        self.post, self.sleep = post, sleep
        self.disabled_reason = ""   # set when the gateway rejects the key or credit runs out; cleared on restart
        self.stats = {"calls": 0, "failures": 0, "discarded": 0, "fallbacks": 0}

    def status(self):
        reason = ("LLM_BASE_URL / FACTCHAT_API_KEY가 설정되지 않았습니다." if not (self.base_url and self.api_key)
                  else self.disabled_reason)
        return {"enabled": not reason, "model": self.model, "reason": reason, "stats": dict(self.stats)}

    def available(self):
        return self.status()["enabled"]

    def chat(self, messages, max_tokens=400):
        if not self.available():
            raise LLMError(self.status()["reason"])
        for attempt in range(4):
            self.stats["calls"] += 1
            try:
                r = self.post(f"{self.base_url}/chat/completions", timeout=60,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json={"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens})
            except httpx.HTTPError as e:
                raise LLMError(f"LLM 게이트웨이 연결 실패: {type(e).__name__}: {e}")
            body = r.text[:300]
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (401, 403):
                self.disabled_reason = f"LLM API 키가 거부되었습니다 (HTTP {r.status_code})."
            elif r.status_code == 402 or re.search(r"credit|quota|insufficient|balance|크레딧", body, re.I):
                self.disabled_reason = f"LLM 크레딧이 소진되었습니다 (HTTP {r.status_code})."
            elif r.status_code == 429 and attempt < 3:
                log.warning("LLM 429, backoff %ss", 2 ** attempt)
                self.sleep(2 ** attempt)
                continue
            log.error("LLM HTTP %s: %s", r.status_code, body)
            raise LLMError(self.disabled_reason or f"LLM 호출 실패 (HTTP {r.status_code}): {body}")
        raise LLMError("LLM 호출 제한(429) — 재시도 후 실패")

    def summarize(self, title, abstract, keywords=()):
        """Never raises: two attempts at most, then a rule-based summary marked used_fallback."""
        prompt = (
            "다음 논문의 제목과 abstract만 보고 JSON으로 답하세요.\n"
            '{"one_line": "한국어 한 문장 요약", "contributions": ["핵심 기여 (한국어, 최대 3개)"], '
            '"keywords": ["영어 키워드 3~5개"]}\n\n'
            f"Title: {title}\nAbstract: {abstract or '(abstract 없음)'}")
        messages = [{"role": "system", "content": "You are a concise research assistant. Output JSON only."},
                    {"role": "user", "content": prompt}]
        reason = ""
        for _ in range(2):
            if not self.available():
                reason = self.status()["reason"]
                break
            try:
                data = _json(self.chat(messages))
                return {**summary_rules.validate(data), "used_fallback": False}
            except summary_rules.BadSummary as e:
                self.stats["discarded"] += 1
                reason = str(e)
            except LLMError as e:
                self.stats["failures"] += 1
                reason = str(e)
            log.warning("LLM summary attempt failed: %s", reason)
        self.stats["fallbacks"] += 1
        return {**summary_rules.fallback(title, abstract, keywords), "reason": reason}

    def tab_name(self, page_title, institution, authors, keywords):
        prompt = ("연구 소스 탭 이름을 '기관 · 연구실명 · 주력 분야' 형식으로 한 줄만 출력하세요. 기관은 짧은 약칭(예: KAIST), "
                  "주력 분야는 2~3단어 영어. 예: KAIST 비주얼컴퓨팅랩 · 3D Recon\n"
                  f"페이지 제목: {page_title}\n기관: {institution}\n저자: {', '.join(authors)}\n대표 키워드: {', '.join(keywords)}")
        name = self.chat([{"role": "user", "content": prompt}], max_tokens=40).strip().strip('"').splitlines()[0]
        return name[:80]


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0))
    except (AttributeError, json.JSONDecodeError):
        raise LLMError(f"LLM 응답을 JSON으로 해석할 수 없습니다: {(text or '')[:200]}")


client = Client(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
status, available, summarize, tab_name = client.status, client.available, client.summarize, client.tab_name
