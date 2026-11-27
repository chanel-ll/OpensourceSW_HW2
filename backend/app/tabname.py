"""Pure rules for source tab names: '기관 · 연구실명 · 주력 분야' (no DB, no network)."""
import re

MAX_LEN = 40


def heuristic(page_title, inst_short, first_author, keywords):
    lab = re.split(r"\s[\(\|\-–,:]|,", page_title or "")[0].strip() or first_author or ""
    if inst_short and lab.lower().startswith(inst_short.lower()):
        lab = lab[len(inst_short):].strip()
    return " · ".join(x for x in (inst_short, lab, keywords[0] if keywords else "") if x)


def choose(llm_name, rule_name):
    """Use the LLM name only if it is one short 'A · B[ · C]' line; otherwise the rule-based name."""
    lines = (llm_name or "").strip().splitlines()
    name = lines[0].strip().strip('"\'') if lines else ""
    parts = [p.strip() for p in name.split("·")]
    if len(name) > MAX_LEN or len(parts) < 2 or not all(parts):
        return rule_name
    return name
