"""Detaylı CV kontrol listesi: Türkiye'deki İK beklentileri + başvuru sistemleri (ATS) + iyi CV kuralları.

Her kontrol: {"area", "ok", "level": kritik|önemli|öneri, "msg", "tip"}.
Hiçbir şeyi değiştirmez; sadece ölçer. Eksik kalan konular CV Koçu'na (cv_interview) soru olarak gider.
"""
import re
from collections import Counter

from ai_engine import cv_studio as cs

WEIGHT = {"kritik": 10, "önemli": 5, "öneri": 2}
_YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")
_NUM = re.compile(r"\d")
_LANG_LEVEL = re.compile(r"\b(a1|a2|b1|b2|c1|c2|başlangıç|temel|orta|iyi|ileri|akıcı|ana dil|anadil|native|fluent|"
                         r"intermediate|advanced|beginner|upper|elementary)\b", re.I)
# Birinci tekil geçmiş zaman: yönettim, kurdum, sağladım, çözdüm, gerçekleştirdim
_PAST_1SG = re.compile(r"[dt][ıiuü]m$")
_TC_NO = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_PERSONAL = {
    "doğum tarihi": r"doğum\s*tarih", "medeni durum": r"medeni\s*(hal|durum)", "din": r"\bdin(i)?\s*:",
    "kan grubu": r"kan\s*grubu", "boy/kilo": r"\b(boy|kilo)\s*:",
}


def _last_word(text):
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", text or "")
    return cs.tr_lower(words[-1]) if words else ""


def _all_text(p):
    parts = [p.get("headline", ""), p.get("summary", ""), p.get("languages", "")]
    parts += [b["text"] for e in p.get("experience", []) for b in e.get("bullets", [])]
    parts += p.get("education", []) + p.get("certificates", []) + p.get("extras", [])
    parts += [i for g in p.get("skills", []) for i in g.get("items", [])]
    return "\n".join(parts)


def audit(p, job_text="", has_photo=False, template="modern", field="it"):
    """CV'yi madde madde denetler. job_text verilirse ilan anahtar kelimeleriyle de karşılaştırır."""
    out = []

    def check(area, ok, level, msg, tip=""):
        out.append({"area": area, "ok": bool(ok), "level": level, "msg": msg, "tip": tip})

    # --- iletişim ve başlık
    check("İletişim", p.get("name"), "kritik", "Ad soyad")
    check("İletişim", cs.EMAIL_RE.search(p.get("email") or ""), "kritik", "Geçerli e-posta adresi")
    check("İletişim", p.get("phone"), "kritik", "Telefon numarası")
    check("İletişim", p.get("city"), "önemli", "Şehir", "İşverenler önce adayın şehrine bakar (ör. 'Ankara').")
    links = " ".join(p.get("links", [])).lower()
    check("İletişim", "linkedin" in links, "önemli", "LinkedIn profil adresi",
          "İK, CV'den sonra ilk LinkedIn'e bakar; adres yoksa profilinizi bulamayabilir.")
    if field == "it":
        check("İletişim", any(k in links for k in ("github", "gitlab", "portfolio", "portfolyo", ".dev", "blog")), "öneri",
              "GitHub / portfolyo bağlantısı", "BT pozisyonlarında betik, otomasyon veya laboratuvar çalışmalarınızı gösterir.")
    head = p.get("headline", "")
    check("Başlık", head and len(head) <= 120, "kritik", "Hedef unvanı söyleyen kısa başlık (en fazla 120 karakter)",
          "Örn: 'Ağ ve Sistem Yöneticisi | Firewall · Active Directory · VMware'")

    # --- özet
    summ = p.get("summary", "")
    check("Özet", 250 <= len(summ) <= 900, "önemli", f"3-5 cümlelik özet (şu an {len(summ)} karakter; ideal 250-900)")
    check("Özet", _NUM.search(summ), "öneri", "Özette en az bir ölçülebilir bilgi (yıl, kullanıcı sayısı...)",
          "İşveren özetin ilk iki satırında 'ne kadar büyük işler yaptın' sorusuna cevap arar.")

    # --- deneyim
    exp = p.get("experience", [])
    check("Deneyim", exp, "kritik", "En az bir iş deneyimi")
    no_date = [e["title"] for e in exp if not _YEAR.search(e.get("dates", ""))]
    check("Deneyim", not no_date, "kritik", "Her işin tarihi (yıl) var" + (f" — eksik: {', '.join(no_date[:3])}" if no_date else ""))
    starts = [int(m.group(0)) for e in exp for m in [_YEAR.search(e.get("dates", ""))] if m]
    check("Deneyim", starts == sorted(starts, reverse=True), "önemli", "Deneyimler yeniden eskiye sıralı",
          "En güncel iş en üstte olmalı; ATS sistemleri de bunu bekler.")
    thin = [e["title"] for e in exp[:3] if len(e.get("bullets", [])) < 2]
    check("Deneyim", not thin, "önemli", "Son işlerde en az 2'şer madde" + (f" — az: {', '.join(thin)}" if thin else ""))
    bullets = [b["text"] for e in exp for b in e.get("bullets", [])]
    if bullets:
        ratio = sum(1 for b in bullets if _NUM.search(b)) / len(bullets)
        check("Deneyim", ratio >= 0.4, "önemli", f"Maddelerin en az %40'ı ölçülebilir (şu an %{round(ratio * 100)})",
              "Sayı içeren madde örneği: '3 yerleşkede 18.000 kullanıcılı ağı yönettim.'")
        long_ = [b[:40] for b in bullets if len(b) > 220]
        short = [b[:40] for b in bullets if len(b) < 35]
        check("Deneyim", not long_, "öneri", f"Maddeler 220 karakteri geçmiyor" + (f" — {len(long_)} uzun madde" if long_ else ""))
        check("Deneyim", not short, "öneri", f"Maddeler çok kısa değil" + (f" — {len(short)} kısa madde" if short else ""),
              "Tek kelimelik maddeler yerine 'ne yaptım + hangi araçla + sonucu' yazın.")
        verbs = [_last_word(b) for b in bullets]
        past = sum(1 for v in verbs if _PAST_1SG.search(v)) / len(verbs)
        check("Deneyim", past >= 0.7, "öneri", "Maddeler aynı kipte ('…yönettim', '…kurdum')",
              "Karışık kip ('yönetilmesi', 'sorumlu') yerine birinci tekil geçmiş zaman okunması en kolay olanıdır.")
        top, n = (Counter(v for v in verbs if _PAST_1SG.search(v)).most_common(1) or [("", 0)])[0]
        check("Deneyim", n < 4, "öneri", (f"Aynı fiil çok tekrarlanıyor: '{top}' {n} kez" if n >= 4 else "Fiiller çeşitli"),
              "Alternatifler: kurdum, yapılandırdım, iyileştirdim, otomatikleştirdim, taşıdım, güvenceye aldım.")

    # --- beceriler
    items = [i for g in p.get("skills", []) for i in g.get("items", [])]
    check("Beceriler", len(items) >= 10, "önemli", f"En az 10 beceri (şu an {len(items)})",
          "İşe alımcılar LinkedIn ve ATS'de beceri adıyla arama yapar.")
    check("Beceriler", len(p.get("skills", [])) >= 2, "öneri", "Beceriler gruplu (Ağ, Güvenlik, Sistem...)")
    dup = [k for k, v in Counter(cs.tr_lower(i) for i in items).items() if v > 1]
    check("Beceriler", not dup, "öneri", (f"Tekrarlanan beceri var: {', '.join(dup[:4])}" if dup else "Tekrarlanan beceri yok"))
    if job_text:
        from ai_engine.job_matcher import find_skills
        missing = sorted(find_skills(job_text) - find_skills(_all_text(p) + "\n" + p.get("summary", "")))
        check("İlan uyumu", not missing, "önemli",
              (f"İlandaki anahtar kelimeler CV'de yok: {', '.join(missing[:8])}" if missing else "İlandaki teknik anahtar kelimeler CV'de var"),
              "Sadece GERÇEKTEN bildiklerinizi ekleyin; koç size tek tek soracak.")

    # --- eğitim, sertifika, dil, ek bilgiler
    edu = p.get("education", [])
    check("Eğitim", edu, "kritik", "Eğitim bilgisi")
    check("Eğitim", all(_YEAR.search(e) for e in edu) if edu else False, "öneri", "Eğitimlerde mezuniyet yılı")
    certs = p.get("certificates", [])
    check("Sertifika", certs, "öneri", "En az bir sertifika / eğitim",
          "BT'de CCNA, Fortinet NSE, Microsoft, Linux (LPI) gibi sertifikalar fark yaratır.")
    if certs:
        check("Sertifika", all(_YEAR.search(c) for c in certs) and not any(re.search(r"\btarih\b", c, re.I) for c in certs),
              "öneri", "Sertifikalarda alınma yılı")
    langs = p.get("languages", "")
    check("Dil", langs, "önemli", "Yabancı dil bilgisi")
    if langs:
        check("Dil", _LANG_LEVEL.search(langs), "öneri", "Dil seviyesi belirtilmiş (ör. İngilizce – B1 / orta)")
    extras = " ".join(p.get("extras", [])).lower()
    check("Ek bilgi", any(k in extras for k in ("ehliyet", "sürücü")), "öneri", "Sürücü belgesi (varsa)",
          "Sahaya / yerleşkeler arası gidilen BT işlerinde sık sorulur.")
    check("Ek bilgi", "askerlik" in extras or "muaf" in extras or "tecil" in extras, "öneri", "Askerlik durumu (varsa)",
          "Türkiye'de pek çok işveren başvuruda bunu sorar; CV'de olması soruyu ortadan kaldırır.")

    # --- risk ve biçim
    text = _all_text(p)
    found = [k for k, pat in _PERSONAL.items() if re.search(pat, text, re.I)] + (["TC kimlik no"] if _TC_NO.search(text) else [])
    check("Gizlilik", not found, "önemli", (f"Gereksiz kişisel veri var: {', '.join(found)}" if found else "Gereksiz kişisel veri yok"),
          "KVKK ve ayrımcılık riski: TC kimlik, doğum tarihi, medeni durum, din CV'de gerekmez.")
    warns = cs.typo_warnings(text)
    check("Yazım", not warns, "önemli", (f"Yazım hatası var: {'; '.join(warns)}" if warns else "Bilinen yazım hatası yok"))
    pages = len(text) / 3300
    check("Biçim", pages <= 2.2, "öneri", f"En fazla 2 sayfa (tahmini {pages:.1f} sayfa)",
          "İK bir CV'ye ortalama 6-8 saniye bakar; 2 sayfayı geçen CV'ler sonuna kadar okunmaz.")
    if cs.TEMPLATE_INFO.get(template, {}).get("photo"):
        check("Biçim", has_photo, "öneri", "Fotoğraf yüklendi (seçili şablon fotoğraflı)",
              "Türkiye'de çoğu işveren fotoğraf bekler; resmi, düz arka planlı bir fotoğraf seçin.")
    return out


def score(checks):
    """Ağırlıklı başarı puanı (0-100)."""
    total = sum(WEIGHT[c["level"]] for c in checks)
    return round(100 * sum(WEIGHT[c["level"]] for c in checks if c["ok"]) / total) if total else 0


def failing(checks):
    order = {"kritik": 0, "önemli": 1, "öneri": 2}
    return sorted((c for c in checks if not c["ok"]), key=lambda c: order[c["level"]])
