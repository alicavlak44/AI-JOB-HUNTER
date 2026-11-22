"""Hesaptan senkronlanan veriler ve başarı analizi.

- known_people: LinkedIn'de zaten bağlantın olan veya davetin beklemede olan kişiler.
  Bot bu kişilere tekrar davet göndermez / listede göstermez.
- account_snapshot: her senkronda platform sayıları (başvuru, mülakat, bağlantı, bekleyen davet)
  ve profil özeti → başarı oranı ve zaman içindeki değişim.
- recommendations(): sayılara ve profile bakarak başarı oranını artıracak somut öneriler (kural tabanlı).
"""
import json
import re

from app import dbconn
from datetime import datetime

from app import guard
from app.logger import get_logger

log = get_logger("account")
_LI_PROFILE_RE = re.compile(r"^(https?://[^/]+/in/[^/]+)(?:/.*)?$")


def _connect():
    conn = dbconn.connect(guard.db_file())
    conn.execute("""CREATE TABLE IF NOT EXISTS known_people (
        url TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT, synced_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS account_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)""")
    return conn


def norm_url(url):
    """Profil adresini karşılaştırılabilir hale getirir (sorgu, alt yol /opportunities/..., sondaki /, büyük harf)."""
    u = (url or "").split("?")[0].split("#")[0].rstrip("/").lower()
    u = u.replace("https://tr.linkedin.com", "https://www.linkedin.com")
    m = _LI_PROFILE_RE.match(u)
    return m.group(1) if m else u


def save_known_people(people, kind):
    """people: [{"url", "name"}], kind: 'connection' | 'pending_invite'."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        for p in people:
            # bağlantı > bekleyen davet: kabul edilen davet bağlantıya döner
            conn.execute("""INSERT INTO known_people(url, kind, name, synced_at) VALUES (?,?,?,?)
                            ON CONFLICT(url) DO UPDATE SET
                              kind=CASE WHEN excluded.kind='connection' THEN 'connection' ELSE known_people.kind END,
                              name=COALESCE(excluded.name, known_people.name), synced_at=excluded.synced_at""",
                         (norm_url(p["url"]), kind, p.get("name"), now))
        conn.commit()
    finally:
        conn.close()


def is_known_person(url):
    conn = _connect()
    try:
        return conn.execute("SELECT 1 FROM known_people WHERE url=?", (norm_url(url),)).fetchone() is not None
    finally:
        conn.close()


def known_counts():
    conn = _connect()
    try:
        return dict(conn.execute("SELECT kind, COUNT(*) FROM known_people GROUP BY kind").fetchall())
    finally:
        conn.close()


def save_snapshot(platform, data):
    conn = _connect()
    try:
        conn.execute("INSERT INTO account_snapshot(platform, data, created_at) VALUES (?,?,?)",
                     (platform, json.dumps(data, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()


def latest_snapshot(platform):
    conn = _connect()
    try:
        row = conn.execute("SELECT data, created_at FROM account_snapshot WHERE platform=? ORDER BY id DESC LIMIT 1",
                           (platform,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    data = json.loads(row[0])
    data["_synced_at"] = row[1]
    return data


def bot_invites_sent():
    """Botun gönderdiği davet sayısı (activity_log)."""
    conn = guard._connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM activity_log WHERE platform='linkedin' AND action='invite'").fetchone()[0]
    finally:
        conn.close()


def accepted_bot_invites():
    """Botun davet ettiği kişilerden şimdi bağlantı olanlar."""
    conn = guard._connect()
    try:
        rows = conn.execute("SELECT detail FROM activity_log WHERE platform='linkedin' AND action='invite'").fetchall()
    finally:
        conn.close()
    urls = {norm_url(d.split("url=", 1)[1].split(";")[0]) for (d,) in rows if d and "url=" in d}
    if not urls:
        return 0
    conn = _connect()
    try:
        q = ",".join("?" * len(urls))
        return conn.execute(f"SELECT COUNT(*) FROM known_people WHERE kind='connection' AND url IN ({q})",
                            tuple(urls)).fetchone()[0]
    finally:
        conn.close()


def pct(part, whole):
    return None if not whole else round(100 * part / whole)


def success_metrics(li=None, kn=None):
    """Panel için oranlar. li / kn: latest_snapshot('LinkedIn' / 'Kariyer.net')."""
    li = li if li is not None else latest_snapshot("LinkedIn")
    kn = kn if kn is not None else latest_snapshot("Kariyer.net")
    out = {}
    if li:
        out["LinkedIn başvuru → mülakat"] = (pct(li.get("interviews", 0), li.get("applied", 0)),
                                            f"{li.get('interviews', 0)}/{li.get('applied', 0)}")
    sent = bot_invites_sent()
    if sent:
        acc = accepted_bot_invites()
        out["Davet kabul oranı (bot)"] = (pct(acc, sent), f"{acc}/{sent}")
    if kn and kn.get("applied"):
        positive = kn.get("viewed", 0)
        out["Kariyer.net başvuru → görüntülenme"] = (pct(positive, kn["applied"]), f"{positive}/{kn['applied']}")
        out["Kariyer.net başvuru → mülakat"] = (pct(kn.get("interview", 0), kn["applied"]),
                                               f"{kn.get('interview', 0)}/{kn['applied']}")
    return out


def recommendations(li=None, kn=None, avg_score=None):
    """Başarı oranını artırmak için somut, öncelik sıralı öneriler: [(öncelik, başlık, açıklama)]."""
    li = li if li is not None else latest_snapshot("LinkedIn")
    kn = kn if kn is not None else latest_snapshot("Kariyer.net")
    recs = []
    if li:
        prof = li.get("profile") or {}
        applied, interviews = li.get("applied", 0), li.get("interviews", 0)
        if applied >= 10 and interviews == 0:
            recs.append((1, "Az ama isabetli başvuru",
                         f"{applied} başvuruda mülakat yok. Sadece uyum puanı %65+ ilanlara, ilana özel CV ile "
                         "başvurun; puanı düşük ilanlara başvurmak oranı düşürür."))
        if prof.get("skills") is not None and prof["skills"] < 5:  # None = okunamadı → öneri yok
            recs.append((1, "LinkedIn 'Yetenekler' bölümünü doldurun",
                         "Yetenekler bölümü boş/az. İşe alımcılar aramada yeteneklere göre filtreler; CV'nizdeki "
                         "en güçlü 10-20 beceriyi (araç, teknoloji, yöntem) ekleyin."))
        if prof.get("about") is False:  # None = okunamadı → öneri yok
            recs.append((2, "'Hakkında' bölümü ekleyin",
                         "3-4 cümlelik özet: en büyük ölçekli işiniz (kaç kullanıcı/kişi/şube), ana uzmanlıklarınız ve hedef "
                         "unvanınız. CV Stüdyosu'ndaki özetinizi kullanabilirsiniz."))
        if not prof.get("verified"):
            recs.append((2, "Profilinizi doğrulayın",
                         "Doğrulanmış profiller daha çok görüntülenir ve davetleri daha sık kabul edilir."))
        if prof.get("open_to_work") == "recruiters":
            recs.append((3, "'Çalışmaya açık' görünürlüğü",
                         "Şu an sadece işe alımcılar görüyor; bu doğru tercih (işvereniniz görmez). Hedef unvanlarınızı "
                         "benzer unvanlarla genişletin (Profil ve Ayarlar → Aranacak pozisyonlar)."))
        if prof.get("connections", 0) < 500:
            recs.append((2, "Ağı hedefli büyütün",
                         f"{prof.get('connections', 0)} bağlantı var. Hedef şirketlerdeki İK ve BT yöneticilerine "
                         "günde 10-15 davet; kabul edenlere başvurudan sonra kısa bir mesaj atın."))
        if prof.get("posts", 0) == 0:
            recs.append((3, "Ayda 1-2 teknik paylaşım",
                         "Hiç gönderi yok. Bir firewall/sanallaştırma deneyimini anlatan kısa paylaşım profil "
                         "görüntülenmesini artırır."))
    sent = bot_invites_sent()
    if sent >= 15:
        rate = pct(accepted_bot_invites(), sent)
        if rate is not None and rate < 20:
            recs.append((2, "Davet kabul oranı düşük",
                         f"Kabul oranı %{rate}. Notlu davet hakkınızı (ayda 3) en önemli şirketlere saklayın; "
                         "ortak bağlantısı olan kişileri önceliklendirin."))
    if kn and kn.get("applied", 0) >= 200 and pct(kn.get("viewed", 0), kn["applied"]) < 5:
        recs.append((1, "Toplu başvuru oranı düşürüyor",
                     f"Kariyer.net'te {kn['applied']} başvurudan sadece {kn.get('viewed', 0)} tanesi görüntülenmiş "
                     f"(%{pct(kn.get('viewed', 0), kn['applied'])}). İşverenler aynı adayın çok sayıda alakasız başvurusunu "
                     "görünce özgeçmişi açmıyor. Haftada 10-15 isabetli (uyum %65+) başvuruya inin, her birinde ilana "
                     "özel CV kullanın."))
    elif kn and kn.get("applied", 0) >= 10 and 0 < kn.get("viewed", 0) and pct(kn["viewed"], kn["applied"]) < 25:
        recs.append((1, "Kariyer.net'te özgeçmiş az açılıyor",
                     f"Başvuruların %{pct(kn['viewed'], kn['applied'])}'i görüntülenmiş. Özgeçmiş başlığını hedef unvana "
                     "('Ağ ve Sistem Yöneticisi') çevirin, ilk satıra en güçlü 3 teknolojiyi yazın; part-time / "
                     "öğretmenlik / ERP gibi alakasız ilanlara başvurmayın."))
    if kn and kn.get("applied", 0) >= 5 and kn.get("viewed", 0) == 0:
        recs.append((1, "Kariyer.net özgeçmişi görüntülenmiyor",
                     "Başvurular hiç görüntülenmemiş: özgeçmiş başlığını ve anahtar kelimeleri ilanlara göre güncelleyin."))
    if avg_score is not None and avg_score < 55:
        recs.append((2, "Hedef pozisyonları daraltın",
                     f"Analiz edilen ilanların ortalama uyumu %{avg_score}. Ağ/sistem yöneticisi ve güvenlik "
                     "operasyonu ilanlarına odaklanın; yazılım/ERP ilanlarını aramadan çıkarın."))
    return sorted(recs, key=lambda r: r[0])


def get_search_page(key):
    """Kişi aramasında kalınan sayfa (aynı arama tekrarlanınca oradan devam edilir). 12 saatte sıfırlanır."""
    conn = _connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS search_cursor (key TEXT PRIMARY KEY, page INTEGER, updated_at TEXT)")
        row = conn.execute("SELECT page, updated_at FROM search_cursor WHERE key=?", (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return 1
    age = datetime.now() - datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    return 1 if age.total_seconds() > 12 * 3600 else max(1, int(row[0]))


def set_search_page(key, page):
    conn = _connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS search_cursor (key TEXT PRIMARY KEY, page INTEGER, updated_at TEXT)")
        conn.execute("INSERT INTO search_cursor(key, page, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                     "page=excluded.page, updated_at=excluded.updated_at",
                     (key, int(page), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
