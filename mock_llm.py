import json as _json
import math, re, zlib

URL = "https://openrouter.ai/api/v1/chat/completions"
_state = {"calls": 0}                 # every call to post() counts, including rejected ones


def reset():
    """Restart the call counter. Call once before each independent run so results are reproducible."""
    _state["calls"] = 0


class Response:
    def __init__(self, status_code, body):
        self.status_code, self._body, self.text = status_code, body, _json.dumps(body)

    def json(self):
        return self._body


def est_tokens(text):
    """Project-wide token estimator: ceil(number of whitespace-separated words x 1.3)."""
    return math.ceil(len((text or "").split()) * 1.3)


LABELS = ["billing", "signal", "plan_change", "cancellation"]
KW = {"billing": {"charged", "deducted", "payment", "bill", "refund", "recharge", "money", "amount"},
      "signal": {"signal", "picture", "freezing", "pixelation", "screen", "channels", "box"},
      "plan_change": {"plan", "upgrade", "pack", "switch", "add"},
      "cancellation": {"cancel", "close", "closing", "stop", "disconnect"}}
STOP = {"the", "a", "an", "is", "of", "to", "for", "in", "on", "how", "what", "when", "who", "are", "do", "does", "i", "my", "be",
        "can", "after", "from", "it", "or", "and", "at", "by", "which", "why", "if", "than", "that", "me", "you", "this", "with",
        "was", "but", "not", "no", "have", "has", "am", "your", "please", "help"}


def _words(t):
    return set(re.findall(r"[a-z]+", (t or "").lower()))


def _stems(t):
    return {w[:5] for w in re.findall(r"[a-z]+", (t or "").lower()) if w not in STOP}


def _keyword_label(text):
    w = _words(text)
    for lab in LABELS:                                   # fixed order: billing, signal, plan_change, cancellation
        if KW[lab] & w:
            return lab, sorted(KW[lab] & w)[0]
    return "billing", "the issue"


def _classify(system, user):
    pairs = re.findall(r"Ticket:\s*(.+)\n\s*Label:\s*(\w+)", system)
    uw = _words(user)
    score = {lab: float(len(KW[lab] & uw)) for lab in LABELS}
    first_kw = {lab: (sorted(KW[lab] & uw) or ["the issue"])[0] for lab in LABELS}
    if pairs:                       # few-shot: words seen in the examples of exactly one label add weight to that label
        seen = {}
        for t, l in pairs:
            for w in _words(t) - STOP:
                seen.setdefault(w, set()).add(l)
        for w in uw - STOP:
            if w in seen and len(seen[w]) == 1:
                score[next(iter(seen[w]))] = score.get(next(iter(seen[w])), 0) + 2.0
    best = max(LABELS, key=lambda lab: (score[lab], -LABELS.index(lab)))      # ties go to the earlier label in LABELS
    lab = best if score[best] > 0 else "billing"
    if re.search(r"only the label", system, re.I):
        return lab
    return f"This looks like a {lab.replace('_', ' ')} ticket because the customer mentions {first_kw[lab]}."


def _extract(msgs):
    user_msgs = [m["content"] for m in msgs if m["role"] == "user"]
    ticket = user_msgs[0]
    retry = any(c.startswith("VALIDATION ERROR") for c in user_msgs[1:])
    if ticket.strip() in ("", "..."):
        return "I am unable to extract anything from this ticket."
    sid = re.search(r"TP\d{5}", ticket)
    cat, _ = _keyword_label(ticket)
    low = ticket.lower()
    urgency = 5 if re.search(r"urgent|immediately|third time", low) else (4 if re.search(r"no signal|freezing|not active|still off", low) else 2)
    rec = {"subscriber_id": sid.group(0) if sid else None, "category": cat, "urgency": urgency,
           "wants_refund": bool(re.search(r"refund|money|deduct|charged twice|extra amount", low))}
    g = 99 if retry else zlib.crc32(ticket.encode()) % 12          # first attempt: three kinds of slip, chosen by the ticket text
    if g == 0:
        rec["urgency"] = 7                                          # outside the allowed 1-5 range
    elif g == 1:
        rec["category"] = "Billing Issue"                           # outside the allowed category list
    elif g == 2:
        return "Sure! Here is the extracted record: " + _json.dumps(rec).replace('"', "'")   # not valid JSON
    return _json.dumps(rec)


PARAPHRASE = [(r"top-?up|topped up|top up", "recharge"), (r"\bmoney\b", "amount"), (r"\bdeducted\b", "debited"),
              (r"\bback to back\b", "another"), (r"\bget it back\b", "returned"), (r"\bcheaper\b", "downgrade"),
              (r"\bextra channel packs\b", "add-on packs"), (r"\bat once\b", "at a time"), (r"\bkeep\b", "hold"), (r"\bcustomers?\b", "subscriber"), (r"long-term", "tenure"),
              (r"likely to leave", "High risk"), (r"breaking up|freezing", "pixelation"), (r"\bpicture\b", "signal")]


def _paraphrase(question):
    """A small paraphrase table: lets the mock match a question to a policy sentence worded differently, as a real model would."""
    for pat, rep in PARAPHRASE:
        question = re.sub(pat, rep, question, flags=re.I)
    return question


def _policy(system, user):
    grounded = re.search(r"\bonly\b", system, re.I) and re.search(r"context", system, re.I)
    m = re.search(r"CONTEXT:\s*(.*?)\s*QUESTION:\s*(.*)", user, re.S)
    context, question = (m.group(1), m.group(2)) if m else ("", user)
    if not grounded:                                                # no grounding instruction: confident invention
        return "As of my last update, this is usually processed within 3 working days and the fee is typically INR 500."
    sents = [s.strip() for s in re.split(r"(?<=[.])\s+", re.sub(r"\[[^\]]*\.txt\]", " ", context)) if s.strip()]
    qs = _stems(_paraphrase(question))
    df = {q: sum(q in _stems(s) for s in sents) for q in qs}
    best, best_score = None, 0.0
    for s in sents:
        sc = sum(1.0 / df[q] for q in qs & _stems(s))
        if sc > best_score:
            best, best_score = s, sc
    if best is None or best_score < 1.0:
        return "I don't have enough information to answer that."
    return best


def _brief(user):
    facts = dict(re.findall(r"^(\w+):[ \t]*(\S.*)$", user.split("POLICY CONTEXT:")[0], re.M))
    ctx = user.split("POLICY CONTEXT:")[-1]
    blocks = re.split(r"(?=\[[^\]]+\.txt\])", ctx)
    band, ten, nf = facts.get("risk_band", ""), int(facts.get("tenure_months", "0")), int(facts.get("failed_recharges_6m", "0"))

    def find(phrase):
        for b in blocks:
            if phrase in b:
                m = re.match(r"\[([^\]]+\.txt)\]", b.strip())
                return m.group(1) if m else "unknown"
        return None
    rules = []
    if band == "High" and nf >= 3:
        rules = [("auto-renew setup call", "Offer an auto-renew setup call and a 7 day grace extension.")]
    elif band == "High" and ten >= 12:
        rules = [("loyalty discount of 15 percent", "Offer a loyalty discount of 15 percent on the next three recharges.")]
    elif band == "High":
        rules = [("free add-on pack for 2 months", "Offer a free add-on pack for 2 months.")]
    else:
        rules = [("made only to subscribers whose churn risk band is High", "No retention offer applies; keep monitoring the account.")]
    action, src = "No supporting policy found in the retrieved context.", "none"
    for phrase, text in rules:
        s = find(phrase)
        if s:
            action, src = text, s
    return _json.dumps({"subscriber_id": facts.get("subscriber_id"), "risk_band": band, "recommended_action": action, "policy_source": src})


def _generic(msgs):
    last = msgs[-1]["content"]
    if re.search(r"what is my name", last, re.I):
        for m in msgs[:-1]:
            hit = re.search(r"my name is (\w+)", m["content"], re.I)
            if hit:
                return f"Your name is {hit.group(1)}."
        return "I do not know your name."
    return "I am a mock assistant. I can classify tickets, extract ticket fields, answer policy questions and write retention briefs."


def _behave(msgs):
    system = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
    user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    if "TICKET CLASSIFIER" in system:
        return _classify(system, user)
    if "TICKET EXTRACTOR" in system:
        return _extract(msgs)
    if "POLICY ASSISTANT" in system:
        return _policy(system, user)
    if "RETENTION BRIEF" in system:
        return _brief(user)
    return _generic(msgs)


def post(url, headers=None, json=None, timeout=None):
    """Same call shape as requests.post(url, headers=..., json=..., timeout=...)."""
    _state["calls"] += 1
    if url != URL:
        return Response(404, {"error": {"message": "Not Found"}})
    auth = (headers or {}).get("Authorization", "")
    if not auth.startswith("Bearer ") or len(auth) <= len("Bearer "):
        return Response(401, {"error": {"message": "Missing or invalid Authorization header"}})
    if not isinstance(json, dict) or "model" not in json or not json.get("messages"):
        return Response(400, {"error": {"message": "Request needs 'model' and a non-empty 'messages' list"}})
    if _state["calls"] % 9 == 0:                                    # every 9th call is rate limited; an immediate retry succeeds
        return Response(429, {"error": {"message": "Rate limit exceeded"}})
    content = _behave(json["messages"])
    finish, cap = "stop", json.get("max_tokens")
    if cap is not None and est_tokens(content) > cap:
        content, finish = " ".join(content.split()[:max(1, int(cap / 1.3))]), "length"
    return Response(200, {"model": json["model"],
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
                          "usage": {"prompt_tokens": sum(est_tokens(m["content"]) for m in json["messages"]),
                                    "completion_tokens": est_tokens(content)}})
