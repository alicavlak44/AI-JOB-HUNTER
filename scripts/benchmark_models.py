"""LM Studio modellerini aynı ilanlar üzerinde karşılaştırır.

Kullanım (proje kökünden, model LM Studio'da yüklüyken):
    venv/bin/python scripts/benchmark_models.py <model_id> [job_id ...]
Sonuç: reports/benchmark/<model>.json
"""
import json
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine.brain import full_ai_analysis, read_cv_text, AIError  # noqa: E402
from app.settings import DB_PATH, REPORTS_DIR  # noqa: E402

DEFAULT_JOBS = [1, 2, 3, 5, 9, 20]
OUT_DIR = os.path.join(REPORTS_DIR, "benchmark")
os.makedirs(OUT_DIR, exist_ok=True)

STOP = {"yönetimi", "deneyim", "bilgi", "sistem", "sistemleri", "management", "experience", "ile", "ve"}


def skill_in_cv(skill, cv_low):
    """Becerinin anlamlı kelimelerinden en az biri CV'de geçiyor mu (kaba halüsinasyon kontrolü)."""
    words = [w for w in re.findall(r"[\wçğıöşü/+#.-]+", skill.lower()) if len(w) >= 3 and w not in STOP]
    return any(w in cv_low for w in words) if words else True


def main():
    model = sys.argv[1]
    job_ids = [int(x) for x in sys.argv[2:]] or DEFAULT_JOBS
    cv_low = read_cv_text().lower()
    con = sqlite3.connect(DB_PATH)
    results = []
    for jid in job_ids:
        title, company, city, details = con.execute(
            "SELECT title, company, city, details FROM jobs WHERE id=?", (jid,)).fetchone()
        t0 = time.time()
        entry = {"job_id": jid, "title": title, "company": company}
        try:
            r = full_ai_analysis(jid, title, company, city, details or "", model=model, save=False)
            matching = [s.strip() for s in r["matching_skills"].split(",") if s.strip()]
            halluc = [s for s in matching if not skill_in_cv(s, cv_low)]
            entry.update(ok=True, seconds=round(time.time() - t0, 1), score=r["score_int"],
                         llm_score=r.get("llm_score"), score_notes=r.get("score_notes"), facts=r.get("facts"),
                         requirements=r.get("requirements"), field_fit=r.get("field_fit"),
                         recommendation=r["recommendation"], matching=matching, hallucinated=halluc,
                         missing=r["missing_skills"], hr_message=r["hr_message"],
                         hr_len=len(r["hr_message"]),
                         cover_words=len(r["cover_letter"].split()),
                         cover_has_placeholder=bool(re.search(r"\[[^\]]+\]", r["cover_letter"])),
                         evaluation=r["evaluation"], cover_letter=r["cover_letter"])
        except AIError as e:
            entry.update(ok=False, seconds=round(time.time() - t0, 1), error=str(e))
        results.append(entry)
        print(f"#{jid} {title[:40]:40} -> {entry.get('score')} (LLM {entry.get('llm_score')}) {entry.get('recommendation')} "
              f"({entry['seconds']}s, halüsinasyon: {len(entry.get('hallucinated', []))})", flush=True)

    tag = os.getenv("BENCH_TAG", "")
    path = os.path.join(OUT_DIR, f"{model.replace('/', '_').replace('@', '_')}{'_' + tag if tag else ''}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": model, "results": results}, f, ensure_ascii=False, indent=2)
    print("Kaydedildi:", path)


if __name__ == "__main__":
    main()
