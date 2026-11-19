"""Mülakat provası: alana, CV'ye ve (isteğe bağlı) ilana özel sorular → cevap değerlendirmesi → karne.

Gerçek bir Türk şirketi mülakat akışı: açılış → motivasyon → teknik → davranışsal (STAR) → kapanış.
Yapay zekâ (yerel model) yoksa alan bazlı soru bankası ve kural tabanlı değerlendirme devreye girer.
'Daha iyi cevap' örneği yalnızca adayın CV'sindeki ve kendi cevabındaki bilgilerle yazılır; uydurma denetimi
(cv_builder.check_text) geçemeyen örnek gösterilmez. Eksik bilgi yerine [köşeli parantezli yer tutucu] konur.
"""
import json
import os
import re
from datetime import datetime

from app.logger import get_logger

log = get_logger("interview")

AI_TIMEOUT = 150
STAGE_LABEL = {"intro": "Açılış", "motivation": "Motivasyon", "technical": "Teknik", "behavioral": "Davranışsal",
               "closing": "Kapanış", "followup": "Ek soru"}

COMMON = {
    "intro": ("Bize kendinizden ve kariyerinizden kısaca bahseder misiniz?",
              "2 dakikayı geçmeyen, güncel rolden başlayan, en güçlü 2-3 başarıyı sayılarla veren ve bu pozisyona bağlanan bir özet."),
    "motivation": ("Bu pozisyona neden başvurdunuz, sizi bu işe uygun kılan nedir?",
                   "Şirkete/role özel gerekçe, CV'den somut eşleşme, kariyer hedefiyle tutarlılık; maaş ya da 'iş arıyorum' değil."),
    "closing": ("Son olarak, maaş beklentiniz nedir ve bize sormak istediğiniz bir şey var mı?",
                "Net bir aralık ya da piyasaya dayalı gerekçe; ardından ekibe, beklentilere veya ilk 3 aya dair 1-2 düşünülmüş soru."),
}

BANK = {
    "it": {
        "technical": [
            ("VLAN nedir? Trunk ve access port arasındaki farkı bir örnekle anlatır mısınız?",
             "VLAN'ın yayın alanını ayırması, 802.1Q etiketleme, access=tek VLAN, trunk=çok VLAN, native VLAN; gerçek bir uygulama örneği."),
            ("Kullanıcılar 'internet çok yavaş' dediğinde sorunu adım adım nasıl daraltırsınız?",
             "Katmanlı yaklaşım: tek kullanıcı mı herkes mi, ping/traceroute, DNS, bant genişliği, switch port hataları, firewall; ölçümle karar."),
            ("Active Directory'de bir grup ilkesinin (GPO) bir kullanıcıya uygulanmadığını nasıl tespit edersiniz?",
             "gpresult/RSoP, OU ve güvenlik filtreleme, WMI filtresi, replikasyon, gpupdate /force, olay günlükleri."),
            ("Firewall'da yeni bir servis için kural yazarken nelere dikkat edersiniz?",
             "En az yetki, kaynak/hedef/port daraltma, kural sırası, kayıt (log), değişiklik kaydı, test ve geri dönüş planı."),
            ("Yedekleme stratejinizi anlatır mısınız? 3-2-1 kuralını nasıl uygularsınız?",
             "3 kopya, 2 farklı ortam, 1 dışarıda; geri dönüş testi, RPO/RTO, şifreleme, fidye yazılımına karşı değiştirilemez kopya."),
            ("Site-to-site VPN ile SSL VPN arasındaki farkı ve hangisini ne zaman kullandığınızı anlatır mısınız?",
             "Ofisler arası kalıcı tünel (IPsec) ve uzak kullanıcı erişimi; kimlik doğrulama, MFA, bölünmüş tünel."),
            ("Sanal sunucularda kaynak (CPU/RAM/disk) yetmediğinde neler yaparsınız?",
             "İzleme verisiyle darboğazı bulma, aşırı atama kontrolü, kaynak artırma/taşıma, kapasite planlaması."),
            ("Şüpheli bir oturum açma ya da olası güvenlik ihlalinde ilk 30 dakikada neler yaparsınız?",
             "Kanıtı koruma, hesabı/cihazı izole etme, günlükleri inceleme, yetkilileri bilgilendirme, kök neden ve kayıt."),
        ],
        "behavioral": [
            ("Baskı altında, kısa sürede çözmeniz gereken kritik bir arızayı anlatır mısınız? Siz ne yaptınız, sonuç ne oldu?",
             "STAR: durum, görev, kendi eylemleri, ölçülebilir sonuç (kesinti süresi, etkilenen kullanıcı) ve çıkarılan ders."),
            ("Teknik olmayan bir yöneticiye karmaşık bir teknik konuyu anlatmanız gereken bir örnek verir misiniz?",
             "Basit dil, iş etkisine çeviri, karar için seçenekler; sonuçta alınan karar."),
            ("Bir ekip arkadaşınızla ya da başka bir birimle anlaşmazlık yaşadığınız bir durumu nasıl çözdünüz?",
             "Saygılı iletişim, veriyle ilerleme, ortak çözüm, ilişkiyi koruma; somut sonuç."),
            ("Yaptığınız bir hatadan ne öğrendiniz?",
             "Gerçek bir hata, sorumluluğu üstlenme, düzeltme adımları, tekrarını önleyen değişiklik."),
        ],
    },
    "ik": {
        "technical": [
            ("Bir pozisyon için işe alım sürecini baştan sona nasıl yönetirsiniz?",
             "İhtiyaç analizi, iş tanımı, kaynak kanalları, ön eleme, yetkinlik mülakatı, referans, teklif, oryantasyon; süre ve kalite ölçümü."),
            ("Yetkinlik bazlı mülakatı nasıl planlar ve yaparsınız?",
             "Yetkinlik seti, davranışsal sorular, STAR ile sondaj, puanlama ölçeği, birden fazla değerlendirici."),
            ("Çalışan bağlılığını nasıl ölçer ve artırırsınız?",
             "Anket/eNPS, çıkış mülakatları, devir oranı; aksiyon planı ve takibi, yönetici katılımı."),
            ("Performans değerlendirme sistemi kurarken nelere dikkat edersiniz?",
             "Ölçülebilir hedefler, yetkinlikler, kalibrasyon, düzenli geri bildirim, ücretle bağlantı, adalet algısı."),
            ("İş sözleşmesinin feshinde İş Kanunu açısından nelere dikkat edersiniz?",
             "Bildirim süreleri, geçerli/haklı neden, yazılı bildirim, savunma, kıdem/ihbar tazminatı hesapları, belgeler."),
        ],
        "behavioral": [
            ("Zor bir çalışan ya da yönetici şikâyetini nasıl ele aldığınızı anlatır mısınız?",
             "STAR: tarafları dinleme, gizlilik, kanıt, adil süreç, sonuç ve kalıcı önlem."),
            ("Kısa sürede çok sayıda pozisyonu doldurmanız gereken bir dönemi anlatır mısınız?",
             "Önceliklendirme, kanal çeşitliliği, süreç hızlandırma, kaliteyi koruma; sayılarla sonuç."),
        ],
    },
    "genel": {
        "technical": [
            ("Mevcut ya da son işinizde günlük sorumluluklarınızı ve en çok değer kattığınız işi anlatır mısınız?",
             "Somut görevler, kullanılan araçlar, ölçülebilir katkı."),
            ("İşinizde kullandığınız en önemli araç ya da yöntem nedir, nasıl kullanırsınız?",
             "Araç adı, kullanım örneği, verimlilik etkisi."),
            ("İş yükünüz arttığında önceliklerinizi nasıl belirlersiniz?",
             "Önem/aciliyet, paydaşlarla iletişim, planlama aracı, örnek."),
        ],
        "behavioral": [
            ("Baskı altında çalıştığınız bir dönemi ve nasıl başa çıktığınızı anlatır mısınız?",
             "STAR yapısı, kendi eylemleri, sonuç."),
            ("Bir ekip arkadaşınızla anlaşmazlık yaşadığınız bir durumu nasıl çözdünüz?",
             "İletişim, ortak çözüm, sonuç."),
        ],
    },
}

FILLERS = ("şey", "yani", "ııı", "eee", "ıı", "hani", "işte", "falan")
_STAR = {"durum": r"(o dönem|bir gün|sırasında|projede|çalışırken|olmuştu|vardı)",
         "eylem": r"(\bben\b|yaptım|kurdum|çözdüm|incele|tespit ettim|başlattım|aldım|düzenledim|hazırladım)",
         "sonuç": r"(sonuç|sonunda|böylece|azaldı|arttı|düştü|kısaldı|başarı|tamamlandı|%|\d)"}


def _q(stage, question, expects, source="banka"):
    return {"stage": stage, "question": question, "expects": expects, "source": source}


def bank_questions(field, n_tech=4, n_beh=2, offset=0):
    """Model yoksa: alanın soru bankasından (her yeni mülakatta farklı sırayla) sorular."""
    b = BANK.get(field) or BANK["genel"]
    tech = [b["technical"][(offset + i) % len(b["technical"])] for i in range(min(n_tech, len(b["technical"])))]
    beh = [b["behavioral"][(offset + i) % len(b["behavioral"])] for i in range(min(n_beh, len(b["behavioral"])))]
    return [_q("technical", q, e) for q, e in tech] + [_q("behavioral", q, e) for q, e in beh]


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "maxItems": 10, "items": {
        "type": "object",
        "properties": {"stage": {"type": "string", "enum": ["technical", "behavioral"]},
                       "question": {"type": "string"}, "expects": {"type": "string"}},
        "required": ["stage", "question", "expects"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}
_FIELD_NAME = {"it": "Bilgi Teknolojileri (sistem/ağ/güvenlik)", "ik": "İnsan Kaynakları", "genel": "genel"}


def plan_interview(profile, field="genel", job_title="", job_text="", n_tech=4, n_beh=2, use_ai=True, model=None):
    """Mülakat soruları: açılış + motivasyon + teknik + davranışsal + kapanış. Dönüş: (sorular, yapay_zeka_hatası)."""
    from ai_engine.cv_studio import _profile_prompt
    core, err = [], None
    if use_ai:
        try:
            from ai_engine.brain import _chat_json, fast_model
            system = ("Sen Türkiye'de kıdemli bir işe alım yöneticisi ve alan uzmanısın; gerçekçi bir iş mülakatı "
                      "yapacaksın. Sorular Türkçe, kısa, tek soru işaretli ve doğal konuşma dilinde olsun. Adayın CV'sindeki "
                      "gerçek deneyimlere atıf yapabilirsin ama adayla ilgili bilgi uydurma. Sadece istenen JSON'u döndür.")
            user = f"""ALAN: {_FIELD_NAME.get(field, field)}
POZİSYON: {job_title or profile.get('headline') or '-'}
{('İLAN:' + chr(10) + job_text[:2500]) if job_text else ''}

ADAYIN CV'Sİ:
{_profile_prompt(profile)}

GÖREV: {n_tech} teknik ve {n_beh} davranışsal mülakat sorusu üret.
- technical: alan bilgisini GERÇEKTEN ölçen sorular (tanım + uygulama + arıza/senaryo). Kolaydan zora sırala.
  En az birini adayın CV'sindeki bir deneyime bağla ("CV'nizde ... yazıyor; ... nasıl yaptınız?").
  İlan verildiyse ilandaki gereksinimlere öncelik ver.
- behavioral: STAR ile cevaplanacak, yaşanmış örnek isteyen sorular (baskı, hata, çatışma, iletişim, öncelik).
- expects: iyi bir cevapta mülakatçının duymak istediği 3-5 nokta (tek cümle)."""
            data = _chat_json(system, user, "interview_plan", _PLAN_SCHEMA, temperature=0.5, model=model or fast_model(),
                              timeout=AI_TIMEOUT, max_tokens=1500)
            for q in data.get("questions", []):
                text = re.sub(r"\s+", " ", (q.get("question") or "")).strip()
                if 12 <= len(text) <= 260 and text.count("?") <= 2:
                    core.append(_q(q.get("stage") if q.get("stage") in ("technical", "behavioral") else "technical",
                                   text, (q.get("expects") or "").strip(), "yapay zekâ"))
        except Exception as e:  # model kapalı / yavaş / geçersiz JSON → banka
            err = str(e)
            log.warning("Mülakat soruları üretilemedi: %s", e)
    tech = [q for q in core if q["stage"] == "technical"][:n_tech]
    beh = [q for q in core if q["stage"] == "behavioral"][:n_beh]
    offset = int(datetime.now().strftime("%j"))
    fill = bank_questions(field, n_tech, n_beh, offset)
    tech += [q for q in fill if q["stage"] == "technical"][:n_tech - len(tech)]
    beh += [q for q in fill if q["stage"] == "behavioral"][:n_beh - len(beh)]
    qs = [_q("intro", *COMMON["intro"]), _q("motivation", *COMMON["motivation"])] + tech + beh + \
         [_q("closing", *COMMON["closing"])]
    for i, q in enumerate(qs, 1):
        q["id"] = f"Q{i}"
    return qs, err


# ---------------------------------------------------------------- değerlendirme
def answer_signals(question, answer):
    """Modelden bağımsız, ölçülebilir sinyaller (karnede ve yedek puanlamada kullanılır)."""
    a = (answer or "").strip()
    low = a.lower()
    words = re.findall(r"\w+", low)
    fillers = sum(len(re.findall(rf"(?<!\w){re.escape(f)}(?!\w)", low)) for f in FILLERS)
    star = {k: bool(re.search(p, low)) for k, p in _STAR.items()}
    return {"words": len(words), "fillers": fillers, "numbers": len(re.findall(r"\d+", a)), "star": star,
            "too_short": len(words) < (25 if question["stage"] in ("behavioral", "intro") else 15),
            "too_long": len(words) > 320}


def rule_evaluation(question, answer):
    """Model yoksa ya da cevap boşsa: sinyallerden 1-5 puan ve somut öneriler."""
    s = answer_signals(question, answer)
    if s["words"] == 0:
        return {"score": 1, "strengths": [], "improve": ["Bu soruya cevap verilmedi."], "better": "", "followup": "",
                "signals": s, "source": "kural"}
    score, strengths, improve = 3, [], []
    if s["too_short"]:
        score -= 1
        improve.append("Cevap çok kısa; somut bir örnek ve sonuç ekleyin.")
    if s["too_long"]:
        improve.append("Cevap uzun; 1-2 dakikada (150-250 kelime) toparlamaya çalışın.")
    if s["numbers"]:
        score += 1
        strengths.append("Sayıyla desteklediniz (ölçülebilir sonuç).")
    else:
        improve.append("Sayı verin: kaç kullanıcı/cihaz/kişi, ne kadar sürede, yüzde kaç iyileşme.")
    if question["stage"] == "behavioral":
        missing = [k for k, ok in s["star"].items() if not ok]
        if missing:
            improve.append("STAR yapısı eksik: " + ", ".join(missing) + " kısmını açıkça söyleyin.")
        else:
            score += 1
            strengths.append("Durum → eylem → sonuç yapısı net.")
    if s["fillers"] >= 4:
        score -= 1
        improve.append(f"Dolgu kelimeleri çok ({s['fillers']} kez 'yani/şey/eee'); kısa duraklamalar daha iyi.")
    return {"score": max(1, min(5, score)), "strengths": strengths, "improve": improve, "better": "", "followup": "",
            "signals": s, "source": "kural"}


_EVAL_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5},
                   "strengths": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                   "improve": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                   "better": {"type": "string"}, "followup": {"type": "string"}},
    "required": ["score", "strengths", "improve", "better", "followup"], "additionalProperties": False,
}


def evaluate(question, answer, profile, field="genel", job_title="", cv_text="", use_ai=True, model=None):
    """Cevabı değerlendirir: {"score" 1-5, "strengths", "improve", "better", "followup", "signals", "source"}."""
    base = rule_evaluation(question, answer)
    if not use_ai or base["signals"]["words"] == 0:
        return base
    try:
        from ai_engine.brain import _chat_json, fast_model
        system = ("Sen kıdemli bir Türk işe alım yöneticisi ve alan uzmanısın. Mülakat cevabını adil, net ve yapıcı "
                  "değerlendir. Türkçe yaz. Adayla ilgili bilgi UYDURMA. Sadece istenen JSON'u döndür.")
        user = f"""ALAN: {_FIELD_NAME.get(field, field)} · POZİSYON: {job_title or profile.get('headline') or '-'}
SORU ({STAGE_LABEL.get(question['stage'], '')}): {question['question']}
İYİ CEVAPTA BEKLENEN: {question.get('expects') or '-'}
ADAYIN CEVABI (konuşmadan yazıya çevrildi, küçük yazım hataları olabilir): {answer}

PUAN ÖLÇEĞİ: 1=cevap yok/yanlış, 2=yüzeysel, 3=yeterli, 4=iyi ve somut, 5=örnek düzeyde (doğru, derin, sayılı, yapılı).
- strengths: en fazla 3 güçlü yan (somut).
- improve: en fazla 3 somut iyileştirme (ne eksikti, nasıl söylenmeliydi).
- better: aynı soruya 4-6 cümlelik daha iyi bir cevap; birinci tekil şahıs; SADECE adayın cevabındaki ve CV'sindeki
  bilgileri kullan. Bilmediğin her sayı/araç/ayrıntı için [sayı], [araç], [sonuç] gibi köşeli parantezli yer tutucu koy.
- followup: gerçek bir mülakatçının bu cevaptan sonra soracağı tek bir ek soru (gerekmiyorsa boş).

ADAYIN CV ÖZETİ:
{(cv_text or '')[:1800]}"""
        data = _chat_json(system, user, "interview_eval", _EVAL_SCHEMA, temperature=0.3, model=model or fast_model(),
                          timeout=AI_TIMEOUT, max_tokens=900)
    except Exception as e:
        log.warning("Cevap değerlendirilemedi, kural tabanlı puan kullanılıyor: %s", e)
        return {**base, "ai_error": str(e)}
    better = (data.get("better") or "").strip()
    if better:
        from ai_engine.cv_builder import check_text
        problems = check_text(re.sub(r"\[[^\]]*\]", "", better), f"{cv_text}\n{answer}")
        if problems:  # örnek cevap adayda olmayan beceri/sayı içeriyor → gösterilmez
            log.info("Örnek cevap uydurma içerdiği için gizlendi: %s", problems)
            better = ""
    score = data.get("score")
    return {"score": int(score) if isinstance(score, int) and 1 <= score <= 5 else base["score"],
            "strengths": [s for s in data.get("strengths", []) if s][:3] or base["strengths"],
            "improve": [s for s in data.get("improve", []) if s][:3] or base["improve"],
            "better": better, "followup": (data.get("followup") or "").strip(), "signals": base["signals"],
            "source": "yapay zekâ"}


# ---------------------------------------------------------------- karne ve kayıt
def report(results):
    """results: [{"question": {...}, "answer": str, "eval": {...}}] → karne."""
    done = [r for r in results if r.get("eval")]
    if not done:
        return {"overall": 0, "by_stage": {}, "strengths": [], "improve": [], "words": 0, "fillers": 0}
    by_stage = {}
    for r in done:
        by_stage.setdefault(STAGE_LABEL.get(r["question"]["stage"], r["question"]["stage"]), []).append(r["eval"]["score"])
    count = {}
    for key in ("strengths", "improve"):
        for r in done:
            for s in r["eval"].get(key, []):
                count.setdefault(key, {}).setdefault(s, 0)
                count[key][s] += 1
    top = lambda key: [s for s, _ in sorted(count.get(key, {}).items(), key=lambda x: -x[1])][:4]  # noqa: E731
    avg = sum(r["eval"]["score"] for r in done) / len(done)
    return {"overall": round(avg * 20), "by_stage": {k: round(sum(v) / len(v), 1) for k, v in by_stage.items()},
            "strengths": top("strengths"), "improve": top("improve"),
            "words": sum(r["eval"]["signals"]["words"] for r in done),
            "fillers": sum(r["eval"]["signals"]["fillers"] for r in done)}


def _dir(slug):
    from ai_engine.cv_studio import PROFILES_DIR
    d = os.path.join(PROFILES_DIR, slug, "mulakatlar")
    os.makedirs(d, exist_ok=True)
    return d


def save_session(slug, session):
    session = {**session, "saved": datetime.now().strftime("%Y-%m-%d %H:%M")}
    path = os.path.join(_dir(slug), datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return path


def list_sessions(slug, limit=10):
    d = _dir(slug)
    out = []
    for name in sorted(os.listdir(d), reverse=True)[:limit]:
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                s = json.load(f)
            out.append({"Tarih": s.get("saved", name[:13]), "Pozisyon": s.get("title", "-"),
                        "Puan": s.get("report", {}).get("overall", 0), "Soru": len(s.get("results", []))})
        except (OSError, json.JSONDecodeError):
            continue
    return out
