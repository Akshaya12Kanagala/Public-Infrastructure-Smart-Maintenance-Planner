"""Parse the Markdown rulebook and match incidents / questions to runbook entries (TF-IDF, no LLM)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config

MIN_SCORE = 0.10          # below this a match is not trusted: "no source, no action"
FALLBACK_ID = "RB-108"
_cache: dict = {}


@dataclass
class Entry:
    id: str
    title: str
    meta: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)

    @property
    def effort_min(self) -> int:
        m = re.search(r"\d+", self.meta.get("estimated effort", ""))
        return int(m.group()) if m else 30

    @property
    def action(self) -> str:
        return self.meta.get("executable action", "none").strip().lower()

    @property
    def fallback(self) -> str:
        return self.meta.get("fallback action", "none").strip().lower()

    @property
    def approval(self) -> str:
        return self.meta.get("approval", "required").strip().lower()

    def steps(self) -> list[str]:
        txt = self.sections.get("soft remedy (steps)", "")
        return [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in txt.splitlines() if re.match(r"^\d+\.", ln.strip())]

    def bullets(self, section: str) -> list[str]:
        return [ln.strip()[2:].strip() for ln in self.sections.get(section.lower(), "").splitlines()
                if ln.strip().startswith("- ")]

    def markdown(self) -> str:
        out = [f"### {self.id}: {self.title}"]
        for k, v in self.meta.items():
            out.append(f"- **{k.title()}:** {v}")
        for name, body in self.sections.items():
            out.append(f"\n**{name.title()}**\n{body.strip()}")
        return "\n".join(out)


def _parse(text: str) -> tuple[list[Entry], list[tuple[str, str]]]:
    entries: list[Entry] = []
    extras: list[tuple[str, str]] = []
    cur: Entry | None = None
    extra_title, extra_lines, section = None, [], None

    def flush_extra():
        nonlocal extra_title, extra_lines
        if extra_title:
            extras.append((extra_title, "\n".join(extra_lines).strip()))
        extra_title, extra_lines = None, []

    for line in text.splitlines():
        m = re.match(r"^##\s+(RB-\d+):\s*(.+)$", line)
        if m:
            flush_extra()
            cur = Entry(m.group(1), m.group(2).strip())
            entries.append(cur)
            section = None
            continue
        if line.startswith("## "):
            flush_extra()
            cur, section = None, None
            extra_title = line[3:].strip()
            continue
        if cur is None:
            if extra_title:
                extra_lines.append(line)
            continue
        if line.startswith("### "):
            section = line[4:].strip().lower()
            cur.sections[section] = ""
            continue
        if section is None:
            mm = re.match(r"^- \*\*(.+?):\*\*\s*(.*)$", line)
            if mm:
                cur.meta[mm.group(1).strip().lower()] = mm.group(2).strip()
            continue
        cur.sections[section] += line + "\n"
    flush_extra()
    return entries, extras


def load():
    path = config.rulebook_path()
    mtime = path.stat().st_mtime
    key = (str(path), mtime)
    if _cache.get("key") != key:
        entries, extras = _parse(path.read_text(encoding="utf-8"))
        docs = [f"{e.title} {e.meta.get('keywords', '')} {e.meta.get('keywords', '')} "
                f"{e.sections.get('trigger', '')} {e.meta.get('service scope', '')}" for e in entries]
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit(docs)
        chunks = []
        for e in entries:
            for name, body in e.sections.items():
                if body.strip():
                    chunks.append({"id": e.id, "title": e.title, "section": name, "text": body.strip()})
        cvec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        cmat = cvec.fit_transform([f"{c['title']} {c['section']} {c['text']}" for c in chunks])
        _cache.update(key=key, entries=entries, extras=extras, vec=vec, mat=vec.transform(docs),
                      chunks=chunks, cvec=cvec, cmat=cmat)
    return _cache["entries"], _cache["extras"]


def get(rb_id: str) -> Entry | None:
    return next((e for e in load()[0] if e.id == rb_id), None)


def match(symptoms: str, service: str = "", k: int = 3) -> list[tuple[Entry, float]]:
    """Rank runbooks for a symptom text. A service-scope hit adds a small bonus."""
    entries, _ = load()
    sims = cosine_similarity(_cache["vec"].transform([symptoms]), _cache["mat"])[0]
    scored = []
    for e, s in zip(entries, sims):
        bonus = 0.05 if service and service in e.meta.get("service scope", "") else 0.0
        scored.append((e, float(s) + (bonus if s > 0 else 0.0)))
    return sorted(scored, key=lambda t: t[1], reverse=True)[:k]


def best_for(symptoms: str, service: str = "") -> tuple[Entry, float, bool]:
    """(entry, score, trusted). Untrusted matches fall back to the escalation runbook."""
    top = match(symptoms, service, 1)
    if top and top[0][1] >= MIN_SCORE:
        return top[0][0], top[0][1], True
    return get(FALLBACK_ID) or top[0][0], top[0][1] if top else 0.0, False


def search_chunks(query: str, k: int = 3) -> list[dict]:
    load()
    sims = cosine_similarity(_cache["cvec"].transform([query]), _cache["cmat"])[0]
    idx = sims.argsort()[::-1][:k]
    return [dict(_cache["chunks"][i], score=float(sims[i])) for i in idx if sims[i] >= MIN_SCORE]
