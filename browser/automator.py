"""Tarayıcı otomasyonu (Playwright, kalıcı Chrome profili).

Önemli kural: Bir başvuru ancak sayfada başvuru ONAY metni görülürse "Başvuruldu"
olarak işaretlenir. Aksi halde "Doğrulanamadı" / "Başvuru Ekranında" kalır.
"""
import os
import re
import urllib.parse
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PWTimeout

from app.logger import get_logger
from app.settings import (
    BROWSER_ARGS, JOB_DESC_MAX_CHARS, SCREENSHOTS_DIR,
    APPLY_CONFIRMATION_TEXTS, ALREADY_APPLIED_TEXTS, STATUS_AT_APPLY_SCREEN, STATUS_APPLIED_VERIFIED,
    STATUS_APPLY_UNVERIFIED, STATUS_APPLY_FAILED,
)
from database.db_manager import insert_job, update_job_status
from browser.scraper import filter_title, new_stats, tr_lower
from app import guard
from app import context as ctx  # "context" adı Playwright tarayıcı bağlamı için kullanılıyor

log = get_logger("automator")

APPLY_BUTTON_TEXTS = ["Kolay Başvuru", "Easy Apply", "Hemen Başvur", "Başvur", "Apply"]
NEXT_BUTTON_TEXTS = ["İleri", "Devam Et", "Next", "Continue", "İncele", "Review"]
SUBMIT_BUTTON_TEXTS = ["Başvuruyu Gönder", "Gönder", "Submit application", "Submit"]
MAX_FORM_STEPS = 8


@contextmanager
def _browser():
    """Kalıcı profil ile görünür Chrome açar; her durumda kapatır."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=ctx.chrome_profile(), headless=False, channel="chrome",
            args=BROWSER_ARGS, ignore_default_args=["--enable-automation"], no_viewport=True,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            yield context, page
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass  # kullanıcı pencereyi zaten kapattıysa


def _screenshot(page, label):
    path = os.path.join(SCREENSHOTS_DIR, f"{datetime.now():%Y%m%d_%H%M%S}_{label}.png")
    try:
        page.screenshot(path=path, full_page=False)
        log.info("Ekran görüntüsü: %s", path)
    except PlaywrightError:
        log.warning("Ekran görüntüsü alınamadı (%s)", label)
        return None
    return path


def _wait_until_closed(context, page, timeout_ms):
    """Kullanıcı pencereyi kapatana kadar (veya süre dolana kadar) bekler."""
    try:
        page.wait_for_event("close", timeout=timeout_ms)
    except PWTimeout:
        pass
    except PlaywrightError:
        pass  # tarayıcı kapatıldı


# Oturumun açık olduğunu gösteren çerezler (bot profilinde kalıcıdır → bir kez giriş yeterli)
SESSION_COOKIES = {"LinkedIn": ("linkedin.com", "li_at"), "Kariyer.net": ("kariyer.net", "refresh_token")}
LOGIN_URLS = {"LinkedIn": "https://www.linkedin.com/login", "Kariyer.net": "https://www.kariyer.net/aday/giris"}
LOGIN_URL_HINTS = ("/login", "authwall", "/uas/", "/signup", "/checkpoint", "/aday/giris")
_CHROME_EPOCH_OFFSET = 11644473600  # Chrome çerez zamanı 1601'den mikro saniye


def session_status(profile_dir=None, now=None):
    """Bot profilindeki çerezlerden hangi platformlara giriş yapılmış olduğunu okur (tarayıcı açmadan).
    Dönüş: {"LinkedIn": True/False, "Kariyer.net": True/False}. Çerez DEĞERLERİ okunmaz."""
    import sqlite3, time
    path = os.path.join(profile_dir or ctx.chrome_profile(), "Default", "Cookies")
    out = {k: False for k in SESSION_COOKIES}
    if not os.path.exists(path):
        return out
    now = now or time.time()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        try:
            for plat, (host, name) in SESSION_COOKIES.items():
                rows = conn.execute("SELECT expires_utc FROM cookies WHERE host_key LIKE ? AND name=?",
                                    (f"%{host}", name)).fetchall()
                out[plat] = any(exp == 0 or exp / 1_000_000 - _CHROME_EPOCH_OFFSET > now for (exp,) in rows)
        finally:
            conn.close()
    except Exception:
        log.exception("Oturum durumu okunamadı")
    return out


def _logged_in(context, platform):
    host, name = SESSION_COOKIES[platform]
    try:
        return any(c["name"] == name and host in c["domain"] for c in context.cookies())
    except PlaywrightError:
        return False


def _wait_for_login(context, page, platform, timeout_s=300):
    """Giriş yapılmamışsa giriş sayfasını açar ve kullanıcı giriş yapana kadar bekler. Giriş varsa True."""
    if _logged_in(context, platform) and not any(h in page.url for h in LOGIN_URL_HINTS):
        return True
    if not any(h in page.url for h in LOGIN_URL_HINTS):
        page.goto(LOGIN_URLS[platform])
    log.info("%s girişi bekleniyor (açılan pencerede giriş yapın, en fazla %d sn)", platform, timeout_s)
    for _ in range(timeout_s // 2):
        if page.is_closed():
            return False
        if _logged_in(context, platform) and not any(h in page.url for h in LOGIN_URL_HINTS):
            log.info("%s girişi algılandı; oturum bot profiline kaydedildi", platform)
            return True
        try:
            page.wait_for_timeout(2000)
        except PlaywrightError:
            return False
    return False


def save_login_session(platform):
    """Bot profilinde platforma bir kez giriş yaptırır. Giriş algılanınca pencere kendiliğinden kapanır."""
    plat = "LinkedIn" if platform.lower().startswith("linkedin") else "Kariyer.net"
    try:
        with _browser() as (context, page):
            page.goto(LOGIN_URLS[plat])
            ok = _wait_for_login(context, page, plat)
            if ok:
                page.wait_for_timeout(1500)  # çerezlerin diske yazılması için
        return ok
    except PlaywrightError:
        log.exception("%s oturum kaydı başarısız", plat)
        return False


_TR_ASCII = str.maketrans("çğıöşüâî", "cgiosuai")

# Kart içinden başlık / şirket / konum / sponsorlu bilgisini okur
_CARD_JS = """a => {
    const t = a.querySelector('.k-ad-card-title');
    const leaf = [...a.querySelectorAll('span')].filter(s => !s.className && !s.children.length && s.innerText.trim());
    const loc = a.querySelector('.location');
    return {title: t ? t.innerText.trim() : '', company: leaf.length ? leaf[0].innerText.trim() : '',
            location: loc ? loc.innerText.trim() : '', sponsored: !!a.querySelector('.sponsored-title'),
            text: a.innerText};
}"""


def kariyernet_search_url(keyword, city):
    """Şehir ayrı filtre olarak verilir: /is-ilanlari/ankara?kw=...
    (Şehri arama kelimesine eklemek sonuçlara başka şehirleri ve alakasız ilanları karıştırıyordu.)"""
    kw = urllib.parse.quote(tr_lower(keyword).strip())
    slug = re.sub(r"[^a-z0-9]+", "-", tr_lower(city).translate(_TR_ASCII)).strip("-")
    return f"https://www.kariyer.net/is-ilanlari/{slug}?kw={kw}" if slug else f"https://www.kariyer.net/is-ilanlari?kw={kw}"


def scrape_kariyernet_browser(keyword, city):
    """Kariyer.net arama sonuçlarını tarayıcı ile toplar. Dönüş: istatistik sözlüğü."""
    url = kariyernet_search_url(keyword, city)
    st = new_stats()
    decision = guard.check("Kariyer.net", guard.SCRAPE)
    if not decision.ok:
        st["error"] = "🛡️ " + decision.reason
        return st
    try:
        with _browser() as (context, page):
            page.goto(url)
            guard.record("Kariyer.net", guard.SCRAPE, f"{keyword} / {city}")
            page.wait_for_timeout(2000)
            block = guard.detect_block(_page_text(page), url=page.url)
            if block:  # Kariyer.net taramada rutin doğrulama gösterir; kullanıcı geçer → durdurmak yerine bekle
                log.warning("Kariyer.net doğrulama ekranı (%s); kullanıcının geçmesi bekleniyor", block)
            # Doğrulama ekranı çıkarsa kullanıcının geçmesi için 45 sn tolerans
            page.wait_for_selector("a[href*='/is-ilani/']", timeout=45_000)
            page.wait_for_timeout(1500)
            for el in page.locator("a[href*='/is-ilani/']").all()[:40]:
                href = el.get_attribute("href")
                if not href or "/is-ilani/" not in href:
                    continue
                full_url = ("https://www.kariyer.net" + href if href.startswith("/") else href).split("?")[0]
                info = el.evaluate(_CARD_JS)
                if info["sponsored"]:  # arama kelimesinden bağımsız reklam ilanları
                    continue
                lines = [x.strip() for x in info["text"].split("\n") if len(x.strip()) > 2]
                title = info["title"] or (lines[0] if lines else href.split("/")[-1].replace("-", " ").title())
                company = info["company"] or "Kariyer.net Firması"
                location = (info["location"] or city).split("+")[0].strip()
                st["found"] += 1
                if not filter_title(title, keyword, st):
                    continue
                if insert_job("Kariyer.net", title[:120], company[:80], location, full_url):
                    st["added"] += 1
                else:
                    st["duplicate"] += 1
    except PWTimeout:
        log.warning("Kariyer.net: 45 sn içinde ilan listesi yüklenmedi (doğrulama ekranı veya sonuç yok)")
        st["error"] = ("45 saniye içinde ilan listesi yüklenmedi. Açılan pencerede doğrulama (robot kontrolü) "
                       "çıktıysa onu geçip tekrar deneyin; ya da aramanın sonucu yok.")
    except PlaywrightError as e:
        log.exception("Kariyer.net taraması başarısız")
        msg = str(e)
        if "ProcessSingleton" in msg or "user data directory is already in use" in msg.lower() or "profile" in msg.lower():
            st["error"] = ("Bot tarayıcısı zaten açık (önceki bir pencere kapanmamış). "
                           "Açık bot Chrome penceresini kapatıp tekrar deneyin.")
        else:
            st["error"] = f"Tarayıcı açılamadı: {msg[:150]}"
    log.info("Kariyer.net: '%s' / %s → %s", keyword, city, {k: v for k, v in st.items()})
    return st


def fetch_job_description_browser(url):
    """Tarayıcısız okunamayan ilanların (ör. Kariyer.net) metnini tarayıcı ile okur."""
    try:
        with _browser() as (context, page):
            page.goto(url)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2500)
            for sel in ["[class*='job-detail']", "[class*='description']", "main", "body"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    text = loc.inner_text().strip()
                    if len(text) > 200:
                        return text[:JOB_DESC_MAX_CHARS]
    except PlaywrightError:
        log.exception("İlan metni tarayıcı ile alınamadı: %s", url)
    return ""


# ---------------------------------------------------------------- CV yükleme
_CV_HINTS = ("resume", "cv", "özgeçmiş", "ozgecmis", "upload", "yükle")


def choose_cv(tailored_path=None):
    """Başvuruda kullanılacak CV: ilana özel üretilen varsa o, yoksa orijinal Cv.pdf."""
    if isinstance(tailored_path, str) and tailored_path and os.path.exists(tailored_path):  # NaN/None gelebilir
        return tailored_path
    cv = ctx.cv_path()
    return cv if os.path.exists(cv) else None


def _accepts(accept_attr, path):
    """input[type=file] 'accept' özniteliği bu dosya türünü kabul ediyor mu? (boş = her şey)"""
    accept = (accept_attr or "").lower().replace(" ", "")
    if not accept:
        return True
    ext = os.path.splitext(path)[1].lower()
    mime = {".pdf": "application/pdf", ".docx": "wordprocessingml", ".doc": "msword"}.get(ext, "")
    return any(a == ext or a == "*/*" or (mime and mime in a) for a in accept.split(","))


def try_upload_cv(page, cv_path, fallback_path=None):
    """Sayfadaki CV dosya alanını bulup dosyayı yükler. Dönüş: yüklenen dosya yolu veya None.
    Alan .docx kabul etmiyorsa (ör. sadece PDF) yedek dosya (orijinal Cv.pdf) denenir."""
    if not cv_path:
        return None
    try:
        inputs = page.locator("input[type=file]")
        n = inputs.count()
    except PlaywrightError:
        return None
    if n == 0:
        return None
    # CV ile ilgili görünen alanı tercih et (ön yazı / fotoğraf alanına CV yüklenmesin)
    best = None
    for i in range(n):
        el = inputs.nth(i)
        try:
            info = el.evaluate("""e => [e.name, e.id, e.getAttribute('aria-label'), e.accept,
                (e.labels && e.labels[0] ? e.labels[0].innerText : ''),
                (e.closest('div,section,form') || e).innerText.slice(0, 200)].join(' ').toLowerCase()""")
        except PlaywrightError:
            continue
        if any(w in info for w in ("photo", "fotoğraf", "image", "cover", "ön yazı")):
            continue
        if best is None or any(h in info for h in _CV_HINTS):
            best = el
            if any(h in info for h in _CV_HINTS):
                break
    if best is None:
        return None
    try:
        accept = best.get_attribute("accept")
        for path in (cv_path, fallback_path):
            if path and os.path.exists(path) and _accepts(accept, path):
                best.set_input_files(path)
                page.wait_for_timeout(1500)
                log.info("CV yüklendi: %s", os.path.basename(path))
                return path
        log.warning("CV alanı bu dosya türlerini kabul etmiyor (accept=%s)", accept)
    except PlaywrightError as e:
        log.warning("CV yüklenemedi: %s", e)
    return None


# ---------------------------------------------------------------- Başvuru
def _click_first(page, texts, scope=None):
    """Görünür ve aktif ilk eşleşen butona tıklar; tıklanan metni döner."""
    root = scope or page
    for text in texts:
        btn = root.get_by_role("button", name=re.compile(rf"^\s*{re.escape(text)}\b", re.I)).first
        try:
            if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                btn.click()
                page.wait_for_timeout(2000)
                return text
        except PlaywrightError:
            continue
    return None


def _empty_required_fields(page):
    """Doldurulmamış zorunlu form alanı sayısı (bot bunları doldurmaz — kullanıcıya bırakır)."""
    try:
        return page.evaluate("""() => {
            const els = [...document.querySelectorAll('input[required], select[required], textarea[required], [aria-required="true"]')];
            return els.filter(e => e.offsetParent !== null && (
                (e.type === 'checkbox' || e.type === 'radio') ? !document.querySelector(`[name="${e.name}"]:checked`)
                : !String(e.value || '').trim()
            )).length;
        }""")
    except PlaywrightError:
        return 0


def _page_text(page):
    try:
        return page.locator("body").inner_text(timeout=5000).lower()
    except PlaywrightError:
        return ""


def _found_texts(page, texts):
    body = _page_text(page)
    return {t for t in texts if t in body}


def _is_confirmed(page, baseline):
    """Tıklamadan önce sayfada OLMAYAN bir onay metni belirdiyse True."""
    if page.is_closed():
        return False
    return bool(_found_texts(page, APPLY_CONFIRMATION_TEXTS) - baseline)


_FIELDS_JS = """() => {
    const out = [];
    document.querySelectorAll('[data-ko-field]').forEach(e => e.removeAttribute('data-ko-field'));
    const els = [...document.querySelectorAll('input, textarea')].filter(e =>
        e.offsetParent !== null && !e.disabled && !e.readOnly &&
        ['text', 'tel', 'email', 'number', ''].includes((e.type || '').toLowerCase()) && !String(e.value || '').trim());
    els.forEach((e, i) => {
        let label = e.getAttribute('aria-label') || '';
        if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) label = l.innerText + ' ' + label; }
        if (!label) { const l = e.closest('label'); if (l) label = l.innerText; }
        if (!label) label = e.placeholder || e.name || '';
        e.setAttribute('data-ko-field', String(i));
        out.push({idx: i, label: label.trim().slice(0, 200), type: (e.type || '').toLowerCase()});
    });
    return out;
}"""


def fill_known_fields(page, answers):
    """Formdaki BOŞ alanlardan CV'de cevabı olanları doldurur. Doldurulan alan etiketlerini döndürür."""
    from ai_engine.form_answers import answer_for
    filled = []
    try:
        fields = page.evaluate(_FIELDS_JS)
    except PlaywrightError:
        return filled
    for f in fields:
        value = answer_for(f["label"], f["type"], answers)
        if value is None:
            continue
        try:
            page.locator(f'[data-ko-field="{f["idx"]}"]').first.fill(value, timeout=3000)
            filled.append(f["label"][:60])
            guard.human_pause(0.4, 1.2)
        except PlaywrightError:
            log.warning("Alan doldurulamadı: %s", f["label"][:60])
    if filled:
        log.info("Formda CV bilgisiyle doldurulan alanlar: %s", filled)
    return filled


def _cv_answers():
    try:
        from ai_engine.brain import read_cv_text
        from ai_engine.form_answers import answers_from_cv
        return answers_from_cv(read_cv_text())
    except Exception:
        log.exception("CV'den form cevapları çıkarılamadı")
        return {}


def run_application_bot(job_id, job_url, mode="yari", cv_path=None):
    """
    mode="yari": Başvuru formunu açar, kullanıcı tamamlar. Pencere kapanınca onay metni aranır.
    mode="tam":  Formda adım adım ilerler; boş zorunlu alan görürse DURUR ve kullanıcıya bırakır.
                 Sadece onay metni görülürse "Başvuruldu (Doğrulandı)" yazılır.
    cv_path: formda CV yükleme alanı çıkarsa yüklenecek dosya (genelde ilana özel CV).
    Dönüş: (durum, mesaj)
    """
    fallback = ctx.cv_path() if os.path.exists(ctx.cv_path()) else None
    uploaded = None
    platform = platform_of(job_url)
    decision = guard.check(platform, guard.APPLY)
    if not decision.ok:
        log.info("İlan #%s başvurusu koruma nedeniyle ertelendi: %s", job_id, decision.reason)
        return None, "🛡️ " + decision.reason
    try:
        with _browser() as (context, page):
            page.goto(job_url)
            page.wait_for_timeout(int(guard.random.uniform(3000, 6000)))

            block = guard.detect_block(_page_text(page), url=page.url)
            if block:
                guard.report_block(platform, block)
                _screenshot(page, f"job{job_id}_blocked")
                return None, (f"🛡️ {platform} bot koruması belirtisi gösterdi ({block}). Hesabı korumak için "
                              f"başvurular {guard.settings.BLOCK_COOLDOWN_HOURS:.0f} saat durduruldu.")

            if _found_texts(page, ALREADY_APPLIED_TEXTS):
                update_job_status(job_id, STATUS_APPLY_UNVERIFIED,
                                  error="İlan sayfası bu ilana daha önce başvurulduğunu gösteriyor; kontrol edin.")
                return STATUS_APPLY_UNVERIFIED, "Bu ilana daha önce başvurulmuş görünüyor."

            # Sayfada zaten var olan onay benzeri metinler (menü vb.) sayılmasın
            baseline = _found_texts(page, APPLY_CONFIRMATION_TEXTS)

            clicked = _click_first(page, APPLY_BUTTON_TEXTS)
            if not clicked:
                shot = _screenshot(page, f"job{job_id}_no_apply_button")
                msg = "Başvuru butonu bulunamadı (giriş yapılmamış olabilir veya ilan dış sitede)."
                update_job_status(job_id, STATUS_APPLY_FAILED, error=f"{msg} {shot or ''}".strip())
                if mode == "yari":
                    _wait_until_closed(context, page, 300_000)
                return STATUS_APPLY_FAILED, msg
            log.info("İlan #%s: '%s' butonuna tıklandı (mod: %s)", job_id, clicked, mode)
            guard.record(platform, guard.APPLY, f"job {job_id}")

            if mode == "tam":
                answers = _cv_answers()
                for step in range(MAX_FORM_STEPS):
                    if _is_confirmed(page, baseline):
                        break
                    if not uploaded:
                        uploaded = try_upload_cv(page, cv_path, fallback)
                    fill_known_fields(page, answers)
                    empty = _empty_required_fields(page)
                    if empty:
                        _screenshot(page, f"job{job_id}_needs_input")
                        msg = f"Formda {empty} boş zorunlu alan var; tamamlamanız için pencere açık bırakıldı."
                        update_job_status(job_id, STATUS_AT_APPLY_SCREEN, error=msg)
                        log.info("İlan #%s: %s", job_id, msg)
                        _wait_until_closed(context, page, 300_000)
                        break
                    guard.human_pause(1.5, 4)
                    if _click_first(page, SUBMIT_BUTTON_TEXTS):
                        page.wait_for_timeout(3000)
                        break
                    if not _click_first(page, NEXT_BUTTON_TEXTS):
                        log.info("İlan #%s: adım %d'de ilerleme butonu yok", job_id, step + 1)
                        break
            else:
                update_job_status(job_id, STATUS_AT_APPLY_SCREEN)
                log.info("İlan #%s: yarı otonom — kullanıcının formu tamamlayıp pencereyi kapatması bekleniyor", job_id)
                # Kullanıcı gönderince onay metnini yakalamak için periyodik kontrol
                for _ in range(100):  # ~5 dk
                    if page.is_closed():
                        break
                    if _is_confirmed(page, baseline):
                        break
                    if not uploaded:  # CV alanı formun ileri adımlarında çıkabilir
                        uploaded = try_upload_cv(page, cv_path, fallback)
                    try:
                        page.wait_for_timeout(3000)
                    except PlaywrightError:
                        break

            if _is_confirmed(page, baseline):
                update_job_status(job_id, STATUS_APPLIED_VERIFIED, applied=True)
                _screenshot(page, f"job{job_id}_confirmed")
                cv_note = f" Yüklenen CV: {os.path.basename(uploaded)}." if uploaded else " (Formda CV alanı yoktu / yüklenmedi.)"
                log.info("İlan #%s başvurusu onaylandı.%s", job_id, cv_note)
                return STATUS_APPLIED_VERIFIED, "Başvuru onay ekranı görüldü." + cv_note

            shot = None if page.is_closed() else _screenshot(page, f"job{job_id}_unverified")
            msg = "Başvuru onay metni görülmedi; lütfen platformdan kontrol edin."
            update_job_status(job_id, STATUS_APPLY_UNVERIFIED, error=f"{msg} {shot or ''}".strip())
            return STATUS_APPLY_UNVERIFIED, msg

    except PlaywrightError as e:
        log.exception("İlan #%s başvuru sırasında tarayıcı hatası", job_id)
        update_job_status(job_id, STATUS_APPLY_FAILED, error=str(e)[:300])
        return STATUS_APPLY_FAILED, f"Tarayıcı hatası: {e}"


def platform_of(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    if "linkedin" in host:
        return "LinkedIn"
    if "kariyer.net" in host:
        return "Kariyer.net"
    return host or "diğer"


def open_linkedin_hr_hunter(hr_search_url):
    """Şirketin İK uzmanlarını aramak için LinkedIn'i açar (bağlantı isteği kullanıcı tarafından gönderilir)."""
    try:
        with _browser() as (context, page):
            page.goto(hr_search_url)
            _wait_until_closed(context, page, 300_000)
        return True
    except PlaywrightError:
        log.exception("LinkedIn İK araması açılamadı")
        return False


# ---------------------------------------------------------------- LinkedIn İK davetleri
HR_TERMS = ["insan kaynakları", "i̇nsan kaynakları", "ik ", "ik|", " ik", "human resources", "hr ", " hr", "hrbp",
            "talent", "yetenek", "işe alım", "recruit", "people & culture", "people and culture"]
CONNECT_NAME_RE = re.compile(r"bağlantı kurmak için davet et|invite .* to connect", re.IGNORECASE)
SEND_WITHOUT_NOTE = ["Not olmadan gönderin", "Not olmadan gönder", "Send without a note"]
PENDING_TEXTS = ["beklemede", "pending"]


def name_from_title(title):
    """'(9) Dilek Öden | LinkedIn' → 'Dilek Öden' (profil sayfası başlığı; h1 yapısı LinkedIn'de sık değişiyor)."""
    t = re.sub(r"^\(\d+\)\s*", "", title or "")
    t = t.split("|")[0].strip()
    return "" if t.lower() in ("", "linkedin") else t


def degree_of(card_text):
    """Arama kartındaki bağlantı derecesi: '• 1.' / '1st' → 1; bilinmiyorsa None."""
    m = re.search(r"•\s*(\d)\.|\b(\d)(?:st|nd|rd|th)\b|(\d)\. derece", card_text or "")
    return int(next(g for g in m.groups() if g)) if m else None


def company_key(company):
    """Şirket adının karşılaştırma anahtarı: 'ASELSAN A.Ş.' → 'aselsan'."""
    name = re.split(r"\b(a\.ş|aş|ltd|şti|inc|corp|holding|anonim|limited)\b", tr_lower(company or ""))[0]
    words = [w for w in re.findall(r"[\wçğıöşü]+", name) if len(w) > 1]
    return " ".join(words[:2])


def pick_hr_profiles(cards, company, limit=1):
    """Arama sonucu kartlarından şirketle eşleşen İK kişilerini seçer.
    cards: [{"url": ..., "text": ...}] — şirket adı kartta geçmeyen kişiler ALINMAZ (rastgele davet yok)."""
    key = company_key(company)
    picked = []
    for c in cards:
        text = " " + tr_lower(c.get("text", "")).replace("\n", " ") + " "
        # tam şirket anahtarı ('ankara otomotiv'), kelime sınırıyla ('koç' ≠ 'kariyer koçu')
        if not key or not re.search(rf"(?<![\wçğıöşü]){re.escape(key)}(?![\wçğıöşü])", text):
            continue
        if not any(t in text for t in HR_TERMS):
            continue
        if any(t in text for t in PENDING_TEXTS) or degree_of(c.get("text")) == 1:
            continue
        if _already_invited(c["url"], ""):
            continue
        if c["url"] not in [p["url"] for p in picked]:
            picked.append(c)
        if len(picked) >= limit:
            break
    return picked


_CARDS_JS = """() => {
    const seen = new Map();
    for (const a of document.querySelectorAll('main a[href*="/in/"]')) {
        const url = a.href.split('?')[0];
        let card = a.closest('li') || a.closest('[data-chameleon-result-urn]') || a.parentElement;
        for (let i = 0; i < 6 && card && card.innerText.length < 60; i++) card = card.parentElement;
        const text = card ? card.innerText : a.innerText;
        if (!seen.has(url) || text.length > seen.get(url).length) seen.set(url, text.slice(0, 600));
    }
    return [...seen].map(([url, text]) => ({url, text}));
}"""


def _close_upsell(page):
    """Açık pencere bir Premium reklamıysa Escape ile kapatır (asla satın alma tıklanmaz). Kapattıysa True."""
    try:
        for d in page.locator("[role=dialog]").all():
            if d.is_visible() and "premium" in (d.inner_text(timeout=1000) or "").lower():
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)
                return True
    except PlaywrightError:
        pass
    return False


def _invite_on_profile(page, profile_url):
    """Profil sayfasında notsuz bağlantı daveti gönderir. Dönüş: (gönderildi_mi, ad/neden)."""
    page.goto(profile_url)
    page.wait_for_timeout(int(guard.random.uniform(2500, 4500)))
    block = guard.detect_block(_page_text(page), url=page.url)
    if block:
        return None, block
    name = name_from_title(page.title()) or profile_url
    top = page.locator("main section").first

    name_low = tr_lower(name)
    first_name = name_low.split()[0] if name_low.split() else ""

    def _for_target(loc):
        """Butonun adı hedef kişinin adını içeriyor mu? (kenar paneldeki başka kişilerin butonlarını eler)"""
        try:
            label = tr_lower(loc.get_attribute("aria-label") or loc.inner_text(timeout=1000) or "")
        except PlaywrightError:
            return False
        return bool(first_name) and first_name in label

    btns = [b for b in top.get_by_role("button", name=CONNECT_NAME_RE).all()
            + top.get_by_role("link", name=CONNECT_NAME_RE).all() if b.is_visible() and _for_target(b)]
    if not btns:  # bazı profillerde "Bağlantı kur" yalnızca "Daha fazla" menüsünde
        more = [b for b in top.get_by_role("button", name=re.compile(r"^(Daha fazla|More)", re.I)).all() if b.is_visible()]
        for _ in range(3):  # menü bazen ilk tıklamada açılmıyor
            if not more:
                break
            more[0].click()
            page.wait_for_timeout(900)
            # SADECE açılan menünün içinde ara (sayfadaki diğer kişilerin butonları değil)
            menus = [m for m in page.locator("[role=menu], .artdeco-dropdown__content--is-open").all() if m.is_visible()]
            items = []
            for m in menus:
                items += [i for i in m.get_by_text(re.compile(r"^\s*(Bağlantı kur|Connect)\s*$", re.I)).all() if i.is_visible()]
                items += [i for i in m.get_by_role("menuitem", name=CONNECT_NAME_RE).all() if i.is_visible() and _for_target(i)]
            if items:
                btns = items
                break
    if not btns:
        if any(t in _page_text(page) for t in PENDING_TEXTS):
            return False, f"{name}: davet zaten beklemede"
        return False, f"{name}: 'Bağlantı kur' butonu yok (zaten bağlantı olabilir)"

    def _dialog_for_target():
        """Açılan davet penceresi hedef kişi için mi? Değilse GÖNDERME."""
        try:
            for d in page.locator("[role=dialog]").all():
                if d.is_visible() and first_name and first_name in tr_lower(d.inner_text(timeout=1500)):
                    return True
        except PlaywrightError:
            pass
        return False

    sent = None
    for _ in range(2):  # ilk tıklamada bazen Premium reklamı çıkıyor → kapat, bir kez daha dene
        btns[0].click()
        page.wait_for_timeout(1500)
        if not _dialog_for_target():
            if _close_upsell(page):
                continue
            page.keyboard.press("Escape")
            return False, f"{name}: davet penceresi bu kişiye ait görünmüyor; güvenlik için gönderilmedi"
        sent = _click_first(page, SEND_WITHOUT_NOTE)
        if sent or not _close_upsell(page):
            break
    if not sent:
        page.keyboard.press("Escape")
        return False, f"{name}: davet penceresi beklenen gibi açılmadı"
    page.wait_for_timeout(2000)
    block = guard.detect_block(_page_text(page), url=page.url)
    if block:
        return None, block
    return True, name


def parse_person_card(card):
    """Arama kartı → {"url", "name", "headline", "location", "text"}."""
    lines = [l.strip() for l in (card.get("text") or "").split("\n") if l.strip() and l.strip() not in ("•",)]
    lines = [l for l in lines if not re.fullmatch(r"[•·]?\s*\d+\.?|\d+\. derece|.*bağlantınız|.*takipçi", l)]
    name = re.sub(r"\s*•.*$", "", lines[0]) if lines else ""
    return {"url": card["url"], "name": name, "headline": lines[1] if len(lines) > 1 else "",
            "location": lines[2] if len(lines) > 2 else "", "text": card.get("text", "")}


def filter_hr_people(cards, seen=lambda url, name: False):
    """İK unvanlı, beklemede olmayan ve daha önce davet edilmemiş kişiler (kart sırası korunur)."""
    out, urls = [], set()
    for c in cards:
        p = parse_person_card(c)
        text = " " + tr_lower(p["headline"]) + " "
        if not p["name"] or p["url"] in urls:
            continue
        if not any(t in text for t in HR_TERMS):
            continue
        if any(t in tr_lower(p["text"]) for t in PENDING_TEXTS) or seen(p["url"], p["name"]):
            continue
        if degree_of(c.get("text")) == 1:  # zaten ağında
            continue
        urls.add(p["url"])
        out.append(p)
    return out


def _already_invited(url, name):
    """Daha önce davet edilmiş, daveti bekleyen veya zaten bağlantı olan kişi mi?
    (bot kayıtları + hesaptan senkronlanan davet/bağlantı listesi)"""
    from app import account
    if account.is_known_person(url):
        return True
    if guard.done_recently("LinkedIn", guard.INVITE, f"url={url}", days=365):
        return True
    return bool(name) and guard.done_recently("LinkedIn", guard.INVITE, f"kişi={name};", days=365)


def find_hr_people(query="İnsan Kaynakları Müdürü", city="Ankara", limit=15, max_pages=3, start_page=None):
    """LinkedIn kişi aramasından İK yöneticilerini toplar (davet GÖNDERMEZ — sadece liste).
    Aynı arama tekrarlanınca kaldığı sayfadan devam eder (aynı kişiler tekrar taranmaz, sınır boşa gitmez).
    Dönüş: {"people": [...], "error": str|None, "next_page": int}"""
    from app import account
    key = f"{tr_lower(query).strip()}|{tr_lower(city).strip()}"
    if start_page is None:
        start_page = account.get_search_page(key)
    out = {"people": [], "error": None, "next_page": start_page}
    decision = guard.wait_turn("LinkedIn", guard.SCRAPE)
    if not decision.ok:
        out["error"] = "🛡️ " + decision.reason
        return out
    q = urllib.parse.quote(f"{query} {city}".strip())
    try:
        with _browser() as (context, page):
            for pg in range(start_page, start_page + max_pages):
                if pg > start_page:
                    decision = guard.wait_turn("LinkedIn", guard.SCRAPE)  # her sayfa ayrı istek
                    if not decision.ok:
                        break
                page.goto(f"https://www.linkedin.com/search/results/people/?keywords={q}&page={pg}")
                guard.record("LinkedIn", guard.SCRAPE, f"kişi arama: {query} / {city} sayfa {pg}")
                page.wait_for_timeout(int(guard.random.uniform(3000, 5500)))
                if not _logged_in(context, "LinkedIn") or any(h in page.url for h in LOGIN_URL_HINTS):
                    if not _wait_for_login(context, page, "LinkedIn"):
                        out["error"] = "LinkedIn girişi yapılmadı — üstteki 'LinkedIn'e Bağlan' ile bir kez giriş yapın."
                        break
                    page.goto(f"https://www.linkedin.com/search/results/people/?keywords={q}&page={pg}")
                    page.wait_for_timeout(int(guard.random.uniform(3000, 5500)))
                block = guard.detect_block(_page_text(page), url=page.url)
                if block:
                    guard.report_block("LinkedIn", block)
                    out["error"] = f"🛡️ LinkedIn uyarı verdi ({block}); işlemler durduruldu."
                    break
                if pg == start_page:
                    age = network_sync_age_hours()
                    if (age is None or age > 12) and guard.check("LinkedIn", guard.SYNC).ok:
                        guard.record("LinkedIn", guard.SYNC, "ağ senkronu (arama öncesi)")
                        _sync_network(page)  # bağlantılar/davetliler güncel olsun → listeye gelmesinler
                        page.goto(f"https://www.linkedin.com/search/results/people/?keywords={q}&page={pg}")
                        page.wait_for_timeout(int(guard.random.uniform(3000, 5500)))
                cards = page.evaluate(_CARDS_JS)
                known = {p["url"] for p in out["people"]}
                out["people"] += [p for p in filter_hr_people(cards, _already_invited) if p["url"] not in known]
                out["next_page"] = pg + 1 if cards else 1  # sonuç bittiyse baştan başla
                if len(out["people"]) >= limit or not cards:
                    break
                guard.human_pause(4, 8)
    except PlaywrightError as e:
        log.exception("İK kişi araması başarısız")
        out["error"] = f"Tarayıcı hatası: {str(e)[:150]}"
    out["people"] = out["people"][:limit]
    for p in out["people"]:
        p.pop("text", None)
    account.set_search_page(key, out["next_page"])
    return out


def invite_people(people, on_progress=None):
    """KULLANICININ ONAYLADIĞI kişilere notsuz davet gönderir. people: [{"url", "name", ...}]
    Dönüş: her kişi için {"Kişi", "Sonuç"}."""
    progress = on_progress or (lambda m: None)
    results = []
    try:
        with _browser() as (context, page):
            page.goto("https://www.linkedin.com/feed/")
            page.wait_for_timeout(2500)
            if not _wait_for_login(context, page, "LinkedIn"):
                return [{"Kişi": "-", "Sonuç": "LinkedIn girişi yapılmadı — üstteki 'LinkedIn'e Bağlan' ile giriş yapın."}]
            for i, person in enumerate(people, 1):
                label = f"[{i}/{len(people)}] {person.get('name') or person['url']}"
                decision = guard.check("LinkedIn", guard.INVITE)
                if not decision.ok and decision.wait_seconds <= 120:
                    progress(f"{label}: hesap koruması için {decision.wait_seconds:.0f} sn bekleniyor...")
                    guard.human_pause(decision.wait_seconds + 2, decision.wait_seconds + 8)
                    decision = guard.check("LinkedIn", guard.INVITE)
                if not decision.ok:
                    results += [{"Kişi": p.get("name") or p["url"], "Sonuç": "Ertelendi ⏳ " + decision.reason, "Profil": p["url"]}
                                for p in people[i - 1:]]
                    break
                if _already_invited(person["url"], ""):  # liste eskiyse: bu arada bağlantı/davetli olmuş olabilir
                    results.append({"Kişi": person.get("name"), "Sonuç": "Zaten bağlantı veya davetli — atlandı",
                                    "Profil": person["url"]})
                    continue
                progress(f"{label}: davet gönderiliyor...")
                ok, info = _invite_on_profile(page, person["url"])
                if ok is None:
                    guard.report_block("LinkedIn", info)
                    results.append({"Kişi": person.get("name"), "Sonuç": f"🛡️ LinkedIn uyarı verdi ({info}); durduruldu"})
                    break
                if ok:
                    guard.record("LinkedIn", guard.INVITE, f"kişi={info}; url={person['url']}")
                    results.append({"Kişi": info, "Sonuç": "Davet gönderildi ✅", "Profil": person["url"]})
                else:
                    results.append({"Kişi": person.get("name"), "Sonuç": info, "Profil": person["url"]})
                guard.human_pause(6, 14)
    except PlaywrightError as e:
        log.exception("Toplu davet sırasında tarayıcı hatası")
        results.append({"Kişi": "-", "Sonuç": f"Tarayıcı hatası: {str(e)[:150]}"})
    return results


def send_hr_invites(company, city="Ankara", max_invites=1, dry_run=False):
    """Şirketin İK yöneticilerine notsuz LinkedIn daveti gönderir (guard limitleriyle).
    Aynı şirkete 30 gün içinde tekrar davet gönderilmez. Dönüş: {"sent": [...], "skipped": [...], "error": str|None}"""
    from browser.scraper import build_hr_search_url
    out = {"sent": [], "skipped": [], "error": None}
    key = company_key(company)
    if not key:
        out["error"] = "Şirket adı boş"
        return out
    if guard.done_recently("LinkedIn", guard.INVITE, f"şirket={key};"):
        out["skipped"].append(f"{company}: son 30 günde bu şirkete zaten davet gönderildi")
        return out
    decision = guard.check("LinkedIn", guard.INVITE)
    if decision.ok:
        decision = guard.wait_turn("LinkedIn", guard.SCRAPE)
    if not decision.ok:
        out["error"] = "🛡️ " + decision.reason
        return out
    try:
        with _browser() as (context, page):
            page.goto(build_hr_search_url(company, city))
            guard.record("LinkedIn", guard.SCRAPE, f"şirket İK araması: {company}")
            page.wait_for_timeout(int(guard.random.uniform(3000, 5000)))
            block = guard.detect_block(_page_text(page), url=page.url)
            if block:
                guard.report_block("LinkedIn", block)
                out["error"] = f"🛡️ LinkedIn uyarı verdi ({block}); davetler durduruldu."
                return out
            if not _logged_in(context, "LinkedIn") or any(h in page.url for h in LOGIN_URL_HINTS):
                if not _wait_for_login(context, page, "LinkedIn"):
                    out["error"] = "LinkedIn girişi yapılmadı — üstteki 'LinkedIn'e Bağlan' ile bir kez giriş yapın."
                    return out
                page.goto(build_hr_search_url(company, city))
                page.wait_for_timeout(int(guard.random.uniform(3000, 5000)))
            people = pick_hr_profiles(page.evaluate(_CARDS_JS), company, limit=max_invites)
            if not people:
                out["skipped"].append(f"{company}: şirketle eşleşen İK yöneticisi bulunamadı")
                return out
            for person in people:
                if dry_run:
                    out["skipped"].append(f"(deneme) gönderilecekti: {person['url']}")
                    continue
                decision = guard.check("LinkedIn", guard.INVITE)
                if not decision.ok:
                    out["error"] = "🛡️ " + decision.reason
                    break
                ok, info = _invite_on_profile(page, person["url"])
                if ok is None:
                    guard.report_block("LinkedIn", info)
                    out["error"] = f"🛡️ LinkedIn uyarı verdi ({info}); davetler durduruldu."
                    break
                if ok:
                    guard.record("LinkedIn", guard.INVITE, f"şirket={key}; kişi={info}; url={person['url']}")
                    out["sent"].append(info)
                    log.info("İK daveti gönderildi: %s (%s)", info, company)
                else:
                    out["skipped"].append(info)
                guard.human_pause(4, 9)
    except PlaywrightError as e:
        log.exception("İK daveti sırasında tarayıcı hatası (%s)", company)
        out["error"] = f"Tarayıcı hatası: {str(e)[:150]}"
    return out


# ---------------------------------------------------------------- Hesap senkronu (sadece okuma)
_LINKS_JS = """() => {
    const m = new Map();
    for (const a of document.querySelectorAll('main a[href*="/in/"]')) {
        const url = a.href.split('?')[0];
        const name = (a.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean)[0] || '';
        if (!m.has(url) || (!m.get(url) && name)) m.set(url, name);
    }
    return [...m].map(([url, name]) => ({url, name}));
}"""


def linkedin_job_id(url):
    """'.../jobs/view/devops-engineer-at-obss-4296708666' veya '.../jobs/view/4296708666/' → '4296708666'."""
    m = re.search(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})", url or "")
    return m.group(1) if m else None


def parse_tracker_counts(text):
    """'Başvuruldu · 33', 'Mülakat · 0' → {"applied": 33, "interviews": 0, "in_progress": 5}"""
    out = {}
    for key, label in (("applied", "Başvuruldu"), ("interviews", "Mülakat"), ("in_progress", "Devam Ediyor"),
                       ("applied", "Applied"), ("interviews", "Interview"), ("in_progress", "In progress")):
        m = re.search(rf"{label}\s*·\s*(\d+)", text or "")
        if m and key not in out:
            out[key] = int(m.group(1))
    return out


def parse_profile(main_text, skills_text=""):
    """Profil sayfası metninden başarıyı etkileyen alanlar."""
    t = main_text or ""
    low = tr_lower(t)
    conn = re.search(r"([\d.]+)\+?\s*(?:bağlantı|connections)", t)
    skills = [l for l in (skills_text or "").split("\n") if l.strip()]
    return {
        "verified": "doğrulayın" not in low and "verify now" not in low,
        "connections": int(conn.group(1).replace(".", "")) if conn else 0,
        "open_to_work": ("recruiters" if ("yalnızca kariyer uzmanları" in low or "recruiters only" in low)
                         else "all" if ("çalışmaya açık" in low or "open to work" in low) else None),
        "posts": 0 if ("henüz gönderi yayınlamadınız" in low or "you haven't posted" in low) else None,
        # LinkedIn bölümleri geç/ekrana girince yüklüyor: metinde YOKSA "yok" değil "bilinmiyor" (None) say.
        # (2026-11-15: 'Hakkında' dolu olduğu halde okunamadı, yanlış "ekleyin" önerisi üretildi.)
        "about": True if (("\nhakkında\n" in "\n" + low + "\n") or ("\nabout\n" in "\n" + low + "\n")) else None,
        "skills": len(skills) if skills else None,
    }


def _scroll_collect(page, js, rounds=12):
    """Sonsuz kaydırmalı listeyi sonuna kadar yükleyip toplar ("Daha fazla göster" varsa ona da basar)."""
    seen, stable = [], 0
    for _ in range(rounds):
        items = page.evaluate(js)
        if len(items) == len(seen):
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        seen = items
        # LinkedIn yeni arayüzde kaydırılan alan <main id="workspace">; liste sonunda "Daha fazla yükle" butonu var
        page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight);"
                      " document.querySelectorAll('main').forEach(m => m.scrollTop = m.scrollHeight); }")
        page.wait_for_timeout(int(guard.random.uniform(1200, 2200)))
        _click_first(page, ["Daha fazla yükle", "Daha fazla sonuç göster", "Daha fazla göster",
                            "Show more results", "Load more", "Show more"])
    return seen


def _sync_network(page):
    """Bekleyen davetleri ve bağlantıları okuyup kaydeder (bu kişilere hiç işlem yapılmaz)."""
    from app import account
    page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/")
    page.wait_for_timeout(3500)
    pending = _scroll_collect(page, _LINKS_JS, rounds=30)
    account.save_known_people(pending, "pending_invite")
    page.goto("https://www.linkedin.com/mynetwork/invite-connect/connections/")
    page.wait_for_timeout(3500)
    conns = _scroll_collect(page, _LINKS_JS, rounds=60)  # 10'ar kişi yükleniyor ("Daha fazla yükle")
    account.save_known_people(conns, "connection")
    res = {"pending_invites": len(pending), "connections_listed": len(conns)}
    account.save_snapshot("LinkedIn-ağ", res)
    log.info("LinkedIn ağı senkronlandı: %s", res)
    return res


def network_sync_age_hours():
    from app import account
    snap = account.latest_snapshot("LinkedIn-ağ") or account.latest_snapshot("LinkedIn")
    if not snap:
        return None
    return (datetime.now() - datetime.strptime(snap["_synced_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600


def sync_linkedin_account():
    """Hesaptan okur: bekleyen davetler, bağlantılar, başvurulan ilanlar ve profil özeti.
    Hiçbir şey göndermez/değiştirmez. Dönüş: {"ok", "summary", "error"}"""
    from app import account
    from database.db_manager import get_all_jobs, mark_applied_from_account
    decision = guard.check("LinkedIn", guard.SYNC)
    if not decision.ok:
        return {"ok": False, "error": "🛡️ " + decision.reason}
    snap, out = {}, {"ok": False, "error": None}
    try:
        with _browser() as (context, page):
            page.goto("https://www.linkedin.com/feed/")
            page.wait_for_timeout(2500)
            if not _wait_for_login(context, page, "LinkedIn"):
                return {"ok": False, "error": "LinkedIn girişi yapılmadı — üstteki 'LinkedIn'e Bağlan' ile giriş yapın."}
            guard.record("LinkedIn", guard.SYNC, "hesap senkronu")

            snap.update(_sync_network(page))

            applied_ids, pages = set(), 0
            page.goto("https://www.linkedin.com/jobs-tracker/?stage=applied")
            page.wait_for_timeout(3500)
            snap.update(parse_tracker_counts(_page_text_raw(page)))
            while pages < 10:
                pages += 1
                hrefs = page.eval_on_selector_all('main a[href*="/jobs/view/"]', "els => els.map(e => e.href)")
                applied_ids |= {i for i in map(linkedin_job_id, hrefs) if i}
                if not _click_first(page, ["İleri", "Next"]):
                    break
                page.wait_for_timeout(int(guard.random.uniform(2000, 3500)))
            snap["applied_ids"] = sorted(applied_ids)

            page.goto("https://www.linkedin.com/in/me/")
            page.wait_for_timeout(4000)
            main_text = _page_text_raw(page)
            page.goto(page.url.rstrip("/") + "/details/skills/")
            page.wait_for_timeout(3500)
            skills = page.eval_on_selector_all(
                "main li", "els => els.map(e => (e.innerText||'').split('\\n')[0].trim())"
                           ".filter(t => t && t.length < 60)")
            snap["profile"] = parse_profile(main_text, "\n".join(dict.fromkeys(skills)))
    except PlaywrightError as e:
        log.exception("LinkedIn hesap senkronu başarısız")
        return {"ok": False, "error": f"Tarayıcı hatası: {str(e)[:150]}"}

    jobs = get_all_jobs()
    li_jobs = jobs[jobs["Kaynak"] == "LinkedIn"]
    matched = [int(r.id) for r in li_jobs.itertuples() if linkedin_job_id(r.url) in set(snap["applied_ids"])]
    snap["marked_applied"] = mark_applied_from_account(matched, "LinkedIn")
    account.save_snapshot("LinkedIn", snap)
    out["ok"] = True
    out["summary"] = (f"{snap.get('applied', len(snap['applied_ids']))} başvuru, {snap.get('interviews', 0)} mülakat, "
                      f"{snap['connections_listed']} bağlantı, {snap['pending_invites']} bekleyen davet okundu; "
                      f"listedeki {snap['marked_applied']} ilan 'başvuruldu' olarak işaretlendi.")
    log.info("LinkedIn senkronu: %s", out["summary"])
    return out


def _page_text_raw(page):
    try:
        return page.locator("main").first.inner_text(timeout=5000)
    except PlaywrightError:
        return ""


_KN_CARDS_JS = """() => [...document.querySelectorAll('a[href*="/is-ilani/"]')].map(a => {
    let c = a;
    for (let i = 0; i < 8 && c && !/Durumu Güncelle/.test(c.innerText); i++) c = c.parentElement;
    return {href: a.href.split('?')[0].split('#')[0], text: c ? c.innerText : ''};
}).filter(x => /Durumu Güncelle/.test(x.text))"""


def kariyernet_job_id(url):
    m = re.search(r"/is-ilani/[^?#]*?-(\d{5,})(?:[/?#]|$)", url or "")
    return m.group(1) if m else None


def kariyernet_status(text):
    """Başvuru kartı metni → 'interview' | 'rejected' | 'downloaded' | 'viewed' | 'sent'."""
    t = tr_lower(text)
    if "mülakat" in t:
        return "interview"
    if any(k in t for k in ("olumsuz", "uygun bulunmadı", "reddedildi", "değerlendirme dışı")):
        return "rejected"
    if "indirildi" in t:
        return "downloaded"
    if "görüntülendi" in t or "incelendi" in t:
        return "viewed"
    return "sent"


def summarize_kariyernet(cards):
    """Kartlar → sayılar (aynı ilan bir kez sayılır)."""
    by_id = {}
    for c in cards:
        jid = kariyernet_job_id(c["href"])
        if jid:
            by_id[jid] = kariyernet_status(c["text"])
    counts = {k: sum(1 for v in by_id.values() if v == k) for k in ("sent", "viewed", "downloaded", "interview", "rejected")}
    return {"applied": len(by_id), **counts,
            "viewed": counts["viewed"] + counts["downloaded"] + counts["interview"],  # görüntülenen = olumlu ilgi
            "applied_ids": sorted(by_id)}


def sync_kariyernet_account():
    """Kariyer.net başvurularını ve durumlarını okur (sadece okuma). Zaten başvurulan ilanları işaretler."""
    from app import account
    from database.db_manager import get_all_jobs, mark_applied_from_account
    decision = guard.check("Kariyer.net", guard.SYNC)
    if not decision.ok:
        return {"ok": False, "error": "🛡️ " + decision.reason}
    cards = []
    try:
        with _browser() as (context, page):
            page.goto("https://www.kariyer.net/tum-basvurular")
            page.wait_for_timeout(4000)
            if not _wait_for_login(context, page, "Kariyer.net"):
                return {"ok": False, "error": "Kariyer.net girişi yapılmadı — üstteki 'Kariyer.net'e Bağlan' ile giriş yapın."}
            if "tum-basvurular" not in page.url:
                page.goto("https://www.kariyer.net/tum-basvurular")
                page.wait_for_timeout(4000)
            guard.record("Kariyer.net", guard.SYNC, "hesap senkronu")
            for _ in range(40):  # sayfa başına 50 başvuru
                cards += page.evaluate(_KN_CARDS_JS)
                # Kariyer.net'te "Sonraki" bir <button role="menuitem" aria-label="Go to next page">
                nxt = page.locator('button[aria-label="Go to next page"], button:has-text("Sonraki")').first
                try:
                    if not (nxt.count() and nxt.is_visible() and nxt.is_enabled()):
                        break
                    before = page.evaluate(_KN_CARDS_JS)
                    nxt.click()
                    page.wait_for_timeout(int(guard.random.uniform(2500, 4000)))
                    if page.evaluate(_KN_CARDS_JS) == before:
                        break
                except PlaywrightError:
                    break
    except PlaywrightError as e:
        log.exception("Kariyer.net hesap senkronu başarısız")
        return {"ok": False, "error": f"Tarayıcı hatası: {str(e)[:150]}"}

    snap = summarize_kariyernet(cards)
    jobs = get_all_jobs()
    kn_jobs = jobs[jobs["Kaynak"] == "Kariyer.net"]
    ids = set(snap["applied_ids"])
    matched = [int(r.id) for r in kn_jobs.itertuples() if kariyernet_job_id(r.url) in ids]
    snap["marked_applied"] = mark_applied_from_account(matched, "Kariyer.net")
    account.save_snapshot("Kariyer.net", snap)
    summary = (f"{snap['applied']} başvuru: {snap['viewed']} görüntülendi/indirildi, {snap['interview']} mülakat, "
               f"{snap['rejected']} olumsuz; listedeki {snap['marked_applied']} ilan 'başvuruldu' işaretlendi.")
    log.info("Kariyer.net senkronu: %s", summary)
    return {"ok": True, "summary": summary}
