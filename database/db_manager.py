"""SQLite veri katmanı. Tüm bağlantılar context manager ile açılır/kapanır, hatalar loglanır."""
import json
import os
import sqlite3
from contextlib import contextmanager

import pandas as pd

from app.logger import get_logger
from app import context
from app import dbconn
from app.settings import STATUS_NEW, STATUS_ANALYZED, STATUS_APPLY_UNVERIFIED, STATUS_APPLIED_VERIFIED

log = get_logger("db")

# Eski tabloya sonradan eklenen kolonlar (otomatik migration)
_EXTRA_COLUMNS = {
    "created_at": "TEXT",
    "updated_at": "TEXT",
    "applied_at": "TEXT",
    "missing_skills": "TEXT",
    "recommendation": "TEXT",
    "cover_letter_path": "TEXT",
    "last_error": "TEXT",
    "matching_skills": "TEXT",
    "match_facts": "TEXT",   # JSON: kodla hesaplanan eşleşme gerçekleri
    "tailored_cv_path": "TEXT",  # ilana özel üretilen CV (.docx)
    "analyzed_at": "TEXT",       # istatistik için: son analiz zamanı
    "cv_created_at": "TEXT",     # istatistik için: özel CV üretim zamanı
    "pipeline_stage": "TEXT",    # başvuru sonrası aşama: Başvuruldu / İK Aradı / Teknik Mülakat / Teklif / Olumsuz
    "interview_date": "TEXT",    # mülakat tarihi (YYYY-MM-DD veya YYYY-MM-DD HH:MM)
    "notes": "TEXT",             # kullanıcı notları
    "followed_up_at": "TEXT",    # son takip mesajı zamanı
}


@contextmanager
def _connect():
    conn = dbconn.connect(context.db_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                title TEXT,
                company TEXT,
                city TEXT,
                url TEXT UNIQUE,
                status TEXT,
                ats_score TEXT,
                golden_keywords TEXT,
                details TEXT,
                evaluation TEXT,
                cover_letter TEXT,
                hr_message TEXT
            )
        """)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for col, col_type in _EXTRA_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
                log.info("Migration: jobs.%s kolonu eklendi", col)
        conn.execute("UPDATE jobs SET created_at = datetime('now','localtime') WHERE created_at IS NULL")
        # Bu kolonlardan önce analiz edilmiş ilanlar: en iyi tahmin son güncelleme zamanı
        conn.execute("""UPDATE jobs SET analyzed_at = COALESCE(updated_at, created_at)
                        WHERE analyzed_at IS NULL AND instr(ats_score, '%') > 0""")
        conn.execute("""UPDATE jobs SET cv_created_at = COALESCE(updated_at, created_at)
                        WHERE cv_created_at IS NULL AND tailored_cv_path IS NOT NULL""")
        # Eski sürüm "Tam Otonom" başvuruları doğrulamadan işaretliyordu → doğrulanmadı olarak düzelt
        cur = conn.execute(
            "UPDATE jobs SET status=?, last_error=? WHERE status='Başvuruldu (Tam Otonom) 🚀'",
            (STATUS_APPLY_UNVERIFIED, "Eski sürüm tarafından doğrulamadan 'başvuruldu' işaretlenmişti; platformdan kontrol edin."),
        )
        if cur.rowcount:
            log.warning("Migration: %d doğrulanmamış eski başvuru kaydı düzeltildi", cur.rowcount)


def insert_job(source, title, company, city, url, details=""):
    """Yeni ilan ekler. Aynı URL zaten varsa False döner."""
    try:
        with _connect() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO jobs
                    (source, title, company, city, url, status, ats_score, golden_keywords,
                     details, evaluation, cover_letter, hr_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, '-', '', ?, '', '', '',
                        datetime('now','localtime'), datetime('now','localtime'))
            """, (source, title, company, city, url, STATUS_NEW, details))
            return cur.rowcount == 1
    except sqlite3.Error:
        log.exception("İlan eklenemedi: %s", url)
        return False


_READY = set()  # bu süreçte kurulumu (tablo/göç) yapılmış veritabanı dosyaları


def _ensure_db():
    """init_db her sayfa yenilemesinde yazma işlemi yapmasın: dosya başına süreç içinde bir kez."""
    path = context.db_path()
    if path not in _READY or not os.path.exists(path):
        init_db()
        _READY.add(path)


def get_all_jobs():
    _ensure_db()
    with _connect() as conn:
        return pd.read_sql_query("""
            SELECT id, source as 'Kaynak', title as 'Pozisyon', company as 'Şirket',
                   city as 'Şehir', ats_score as 'ATS Uyum', status as 'Durum',
                   golden_keywords, details, evaluation, cover_letter, hr_message,
                   missing_skills, matching_skills, match_facts, recommendation, cover_letter_path, tailored_cv_path, last_error,
                   created_at, analyzed_at, cv_created_at, applied_at,
                   pipeline_stage, interview_date, notes, followed_up_at, url
            FROM jobs ORDER BY id DESC
        """, conn)


def update_job_details(job_id, details):
    with _connect() as conn:
        conn.execute("UPDATE jobs SET details=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (details, job_id))


def update_job_analysis(job_id, ats_score, golden_kw, details, evaluation, cover_letter, hr_msg,
                        missing_skills="", recommendation="", cover_letter_path="",
                        matching_skills="", match_facts=None):
    with _connect() as conn:
        conn.execute("""
            UPDATE jobs
            SET ats_score=?, golden_keywords=?, details=?, evaluation=?, cover_letter=?, hr_message=?,
                missing_skills=?, recommendation=?, cover_letter_path=?, matching_skills=?, match_facts=?,
                status=?, last_error=NULL,
                updated_at=datetime('now','localtime'), analyzed_at=datetime('now','localtime')
            WHERE id=?
        """, (ats_score, golden_kw, details, evaluation, cover_letter, hr_msg,
              missing_skills, recommendation, cover_letter_path, matching_skills,
              json.dumps(match_facts, ensure_ascii=False) if match_facts else None, STATUS_ANALYZED, job_id))
    log.info("İlan #%s analizi kaydedildi (puan: %s)", job_id, ats_score)


def set_tailored_cv(job_id, path):
    with _connect() as conn:
        conn.execute("""UPDATE jobs SET tailored_cv_path=?, updated_at=datetime('now','localtime'),
                        cv_created_at=datetime('now','localtime') WHERE id=?""",
                     (path, job_id))
    log.info("İlan #%s için özel CV kaydedildi: %s", job_id, path)


def update_job_status(job_id, status, error=None, applied=False):
    with _connect() as conn:
        conn.execute("""
            UPDATE jobs
            SET status=?, last_error=?, updated_at=datetime('now','localtime'),
                applied_at=CASE WHEN ? THEN datetime('now','localtime') ELSE applied_at END
            WHERE id=?
        """, (status, error, 1 if applied else 0, job_id))
    log.info("İlan #%s durumu: %s%s", job_id, status, f" ({error})" if error else "")


def update_job_tracking(job_id, pipeline_stage="", interview_date="", notes="", mark_followed_up=False):
    """Başvuru sonrası CRM alanlarını (aşama, mülakat tarihi, not, takip zamanı) günceller."""
    _ensure_db()
    with _connect() as conn:
        conn.execute("""
            UPDATE jobs
            SET pipeline_stage=?, interview_date=?, notes=?,
                followed_up_at=CASE WHEN ? THEN datetime('now','localtime') ELSE followed_up_at END,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (pipeline_stage or "", (interview_date or "").strip(), (notes or "").strip(),
              1 if mark_followed_up else 0, int(job_id)))
    log.info("İlan #%s süreç takibi güncellendi: aşama=%s", job_id, pipeline_stage or "-")


def delete_single_job(job_id):
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def delete_unprocessed_jobs():
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE status=?", (STATUS_NEW,))


def reset_database():
    db = context.db_path()
    if os.path.exists(db):
        backup = db + ".bak"
        os.replace(db, backup)
        for ext in ("-wal", "-shm"):  # WAL dosyaları yeni (boş) veritabanına uygulanmasın
            if os.path.exists(db + ext):
                os.replace(db + ext, backup + ext)
        _READY.discard(db)
        log.warning("Veritabanı sıfırlandı, eski kopya: %s", backup)
    init_db()


def mark_applied_from_account(job_ids, source="LinkedIn"):
    """Platform hesabında zaten başvurulmuş görünen ilanları işaretler (tekrar başvurulmasın)."""
    if not job_ids:
        return 0
    with _connect() as conn:
        q = ",".join("?" * len(job_ids))
        cur = conn.execute(f"""UPDATE jobs SET status=?, last_error=?, updated_at=datetime('now','localtime')
                               WHERE id IN ({q}) AND status != ?""",
                           (STATUS_APPLIED_VERIFIED, f"{source} hesabınızda bu ilana başvurulmuş (senkron).",
                            *job_ids, STATUS_APPLIED_VERIFIED))
        return cur.rowcount
