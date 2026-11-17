"""📄 CV Stüdyosu — adım adım:
1) CV'ni yükle → 2) formatı seç (7 şablon) → 3) Yapay zekâ koçu: CV'ni okur, soru sorar, cevaplarınla günceller
→ 4) kontrol et ve düzenle → 5) indir.

Çok kişili: her kişinin verisi profiles/<ad>/ altında ayrı tutulur.
"""
import html as _html
import os

import streamlit as st

from ai_engine import cv_audit as ca
from ai_engine import cv_interview as ci
from ai_engine import cv_studio as cs
from ai_engine.brain import AIError
from app import context
from app.ui.common import CSS as COMMON_CSS, show_flash, set_flash

STEPS = ["Yükle", "Format", "Yapay zekâ koçu", "Kontrol et", "İndir"]
STEP_ICONS = ["📥", "🎨", "🤖", "🔎", "⬇️"]

CSS = """<style>
.cvx-hero {border-radius: 18px; padding: 22px 26px; margin: 0 0 14px;
  background: linear-gradient(120deg, rgba(79,70,229,.14), rgba(14,165,233,.12) 55%, rgba(16,185,129,.10));
  border: 1px solid rgba(99,102,241,.25);}
.cvx-hero h2 {margin: 0 0 4px; font-size: 1.55rem;}
.cvx-hero p {margin: 0; opacity: .8;}
.cvx-chips {margin-top: 10px;} .cvx-chip {display: inline-block; font-size: .78rem; padding: 3px 10px; margin: 0 6px 4px 0;
  border-radius: 999px; background: rgba(99,102,241,.14); border: 1px solid rgba(99,102,241,.25);}
.cvx-track {display: flex; align-items: center; gap: 0; margin: 4px 0 8px;}
.cvx-dot {width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: .85rem; border: 2px solid rgba(128,128,128,.35); flex: 0 0 auto;}
.cvx-dot.done {background: #10b981; border-color: #10b981; color: #fff;}
.cvx-dot.now {background: linear-gradient(135deg,#6366f1,#0ea5e9); border-color: transparent; color: #fff;
  box-shadow: 0 0 0 4px rgba(99,102,241,.2);}
.cvx-line {flex: 1 1 auto; height: 2px; background: rgba(128,128,128,.25); margin: 0 6px;}
.cvx-line.done {background: #10b981;}
.cvx-lbl {font-size: .78rem; margin: 0 4px; white-space: nowrap; opacity: .85;}
.cvx-diff {border-radius: 12px; overflow: hidden; border: 1px solid rgba(128,128,128,.25); margin: 4px 0 2px;}
.cvx-diff .old {padding: 8px 12px; background: rgba(239,68,68,.08); text-decoration: line-through; opacity: .75;}
.cvx-diff .new {padding: 8px 12px; background: rgba(16,185,129,.10); font-weight: 500;}
.cvx-diff .tag {font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; opacity: .65; display: block;
  text-decoration: none;}
.cvx-why {font-size: .82rem; opacity: .7; margin-top: 2px;}
</style>"""


def _hero(n_templates):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f"""<div class="cvx-hero"><h2>📄 CV Stüdyosu</h2>
<p>CV'nizi yükleyin, formatını seçin; yapay zekâ koçu eksikleri bulsun, size sorsun ve CV'nizi sizin cevaplarınızla güçlendirsin.</p>
<div class="cvx-chips"><span class="cvx-chip">🎨 {n_templates} profesyonel format</span><span class="cvx-chip">🤖 Soru soran yapay zekâ koçu</span>
<span class="cvx-chip">🔎 Detaylı kontrol listesi</span><span class="cvx-chip">🛡️ Uydurma denetimi</span>
<span class="cvx-chip">🔒 Yerel model — verileriniz bilgisayarınızda kalır</span></div></div>""", unsafe_allow_html=True)


def _diff(old, new, label):
    old_html = f"<div class='old'>{_html.escape(old[:500])}</div>" if old else ""
    return (f"<div class='cvx-diff'>{old_html}<div class='new'><span class='tag'>{_html.escape(label)}</span>"
            f"{_html.escape(new)}</div></div>")


def _k(slug, name):
    return f"cv_{name}_{slug}"


def _reset_pending(slug):
    """CV değişti (yeni CV, elle kayıt): eski indekslere dayanan bekleyen öneriler geçersiz."""
    for name in ("questions", "props", "sugg", "out", "last_round"):
        st.session_state.pop(_k(slug, name), None)


def _reset_edit_widgets(slug):
    """Düzenleme kutuları eski metni tutmasın (kaydedilen yeni metin görünsün)."""
    prefix = f"cv_e_"
    for key in [k for k in st.session_state if isinstance(k, str) and k.startswith(prefix) and k.endswith(f"_{slug}")]:
        st.session_state.pop(key, None)


def _go(slug, n):
    st.session_state[_k(slug, "step")] = n
    st.rerun()


# ---------------------------------------------------------------- adım çubuğu
def _stepper(slug, current, enabled):
    parts = []
    for i, label in enumerate(STEPS, 1):
        cls = "done" if i < current else "now" if i == current else ""
        parts.append(f"<div class='cvx-dot {cls}'>{'✓' if i < current else i}</div><span class='cvx-lbl'>{label}</span>")
        if i < len(STEPS):
            parts.append(f"<div class='cvx-line {'done' if i < current else ''}'></div>")
    st.markdown(f"<div class='cvx-track'>{''.join(parts)}</div>", unsafe_allow_html=True)
    cols = st.columns(len(STEPS))
    for i, (c, label) in enumerate(zip(cols, STEPS), 1):
        if c.button(f"{STEP_ICONS[i - 1]} {label}", key=_k(slug, f"nav{i}"), width="stretch",
                    type="primary" if i == current else "tertiary", disabled=not enabled and i > 1):
            _go(slug, i)


LEVEL_ICON = {"kritik": "🔴", "önemli": "🟠", "öneri": "🔵"}


def _checks(slug, p, job=""):
    return ca.audit(p, job_text=job, has_photo=cs.photo_data_uri(slug) is not None,
                    template=p.get("template") or "modern", field=context.field())


def _score_box(slug, p, job=""):
    checks = _checks(slug, p, job)
    score, bad = ca.score(checks), ca.failing(checks)
    c1, c2 = st.columns([1, 3])
    c1.metric("CV kalite puanı", f"{score}/100", help=f"{len(checks)} maddelik detaylı kontrol listesine göre")
    with c2:
        st.progress(score / 100)
        for c in bad[:3]:
            st.caption(f"{LEVEL_ICON[c['level']]} {c['area']}: {c['msg']}")
        if len(bad) > 3:
            st.caption(f"… ve {len(bad) - 3} madde daha (4. adım → 🔎 Detaylı kontrol)")
    return score


def _checklist(slug, p):
    job = st.text_area("Hedef ilan metni (isteğe bağlı) — yapıştırırsanız ilandaki anahtar kelimeler de kontrol edilir",
                       key=_k(slug, "chk_job"), height=80)
    checks = _checks(slug, p, job)
    st.markdown(f"**{sum(c['ok'] for c in checks)} / {len(checks)} madde tamam** · "
                "🔴 kritik · 🟠 önemli · 🔵 öneri")
    areas = list(dict.fromkeys(c["area"] for c in checks))
    for area in areas:
        items = [c for c in checks if c["area"] == area]
        ok = all(c["ok"] for c in items)
        with st.expander(f"{'✅' if ok else '⚠️'} {area} ({sum(c['ok'] for c in items)}/{len(items)})", expanded=not ok):
            for c in items:
                st.markdown(f"{'✅' if c['ok'] else LEVEL_ICON[c['level']]} {c['msg']}")
                if not c["ok"] and c.get("tip"):
                    st.caption(c["tip"])
    if ca.failing(checks) and st.button("🤖 Eksikleri koça sordur →", key=_k(slug, "chk_go")):
        _go(slug, 3)


# ---------------------------------------------------------------- 1) yükle
def _step_import(slug, exists):
    st.markdown("#### 📥 CV'nizi yükleyin")
    st.caption("PDF veya Word. LinkedIn profilinizi de kullanabilirsiniz: LinkedIn → Profil → Daha fazla → PDF olarak kaydet.")
    c1, c2 = st.columns(2)
    up = c1.file_uploader("CV yükle (PDF / DOCX)", type=["pdf", "docx", "txt"], key=_k(slug, "up"))
    if up and c1.button("📥 Bu CV'yi içe aktar", type="primary", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(up.getvalue(), up.name))
        _save_import(slug, text, f"{up.name} içe aktarıldı")
    main_cv = context.cv_path()
    if os.path.exists(main_cv) and c2.button("📄 Kayıtlı CV'mi kullan", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(open(main_cv, "rb").read(), main_cv))
        _save_import(slug, text, "Sistemdeki CV içe aktarıldı")
    if exists:
        c2.success("Kayıtlı bir CV profiliniz var. Yeni CV yüklerseniz onun yerine geçer.")
        if c2.button("Mevcut CV ile devam et →", width="stretch"):
            _go(slug, 2)


def _save_import(slug, text, msg):
    _reset_pending(slug)
    _reset_edit_widgets(slug)
    p = cs.profile_from_text(text)
    p["name"] = p["name"] or context.name()
    if slug in cs.list_profiles():  # yeni CV: seçili şablon ve renk korunur, eski soru-cevaplar sıfırlanır
        old, _ = cs.load_profile(slug)
        p["template"], p["accent"] = old.get("template", "modern"), old.get("accent", "#1f4e79")
    cs.save_profile(slug, p, text)
    set_flash("cv", "success", f"✅ {msg}: {len(p['experience'])} deneyim, {sum(len(g['items']) for g in p['skills'])} beceri." +
              ("  \n⚠️ " + "  \n⚠️ ".join(p["_warnings"]) if p.get("_warnings") else ""))
    _go(slug, 2)


# ---------------------------------------------------------------- 2) format seç
def _thumb(doc, height=330, scale=0.29):
    """Şablonun küçük önizlemesi (A4 = 794x1123 px, ölçekli)."""
    src = _html.escape(doc, quote=True)
    st.iframe(
        f"""<div style="width:{int(794 * scale)}px;height:{height}px;overflow:hidden;border:1px solid #d9e2ec;border-radius:8px;
background:#fff;margin:auto"><iframe srcdoc="{src}" style="width:794px;height:1123px;border:0;transform:scale({scale});
transform-origin:0 0;pointer-events:none"></iframe></div>""", height=height + 6)


@st.fragment
def _step_format(slug, p):
    st.markdown("#### 🎨 CV formatını seçin")
    st.caption("Önizlemeler sizin bilgilerinizle hazırlandı. Fotoğraflı şablonlar için fotoğrafınızı aşağıdan yükleyebilirsiniz. "
               "Hangi formatı seçerseniz seçin, başvuru sistemleri için sade bir Word (ATS) dosyası da üretilir.")
    c1, c2 = st.columns([1, 2])
    accent = c1.color_picker("Vurgu rengi", p.get("accent") or "#1f4e79", key=_k(slug, "accent"))
    photo = c2.file_uploader("Fotoğraf (isteğe bağlı)", type=["jpg", "jpeg", "png"], key=_k(slug, "photo"))
    if photo:
        cs.save_photo(slug, photo.getvalue(), photo.name)
    names = list(cs.TEMPLATE_INFO)
    for row in range(0, len(names), 4):
        cols = st.columns(4)
        for c, t in zip(cols, names[row:row + 4]):
            info = cs.TEMPLATE_INFO[t]
            with c:
                with st.container(border=True):
                    chosen = p.get("template") == t
                    st.markdown(f"**{'✅ ' if chosen else ''}{info['label']}**")
                    _thumb(cs.render_html(p, t, cs.template_photo(slug, t), accent))
                    st.caption(info["desc"])
                    st.caption(f"👍 {info['best']}" + ("  ·  🤖 ATS dostu" if info["ats"] else "")
                               + ("  ·  📷 fotoğraflı" if info["photo"] else ""))
                    if st.button("Seçili" if chosen else "Bu formatı seç", key=_k(slug, f"pick_{t}"), width="stretch",
                                 type="primary" if chosen else "secondary", disabled=chosen):
                        p["template"], p["accent"] = t, accent
                        cs.save_profile(slug, p)
                        st.rerun()
    if accent != p.get("accent"):
        p["accent"] = accent
        cs.save_profile(slug, p)
    if st.button("Devam: Yapay zekâ koçu →", type="primary"):
        _go(slug, 3)


# ---------------------------------------------------------------- 3) yapay zekâ koçu
def _step_coach(slug, p, original):
    st.markdown("#### 🤖 Yapay zekâ koçu")
    st.caption("Yapay zekâ CV'nizi bir İK uzmanı gözüyle okur, eksik kalan yerleri size SORAR ve CV'yi sizin "
               "cevaplarınızla günceller. Kendisi bilgi uydurmaz: CV'de ya da cevaplarınızda olmayan her sayı, "
               "beceri ve iddia kod tarafından otomatik reddedilir. Her değişikliği siz onaylarsınız.")
    rnd = st.session_state.get(_k(slug, "round"), 1)
    qs = st.session_state.get(_k(slug, "questions"))
    props = st.session_state.get(_k(slug, "props"))

    if props is not None:
        return _coach_review(slug, p, props, rnd)
    if qs is None:
        before = _score_box(slug, p)
        st.session_state[_k(slug, "score_before")] = before
        c1, c2 = st.columns(2)
        target = c1.text_input("Hedef unvan (isteğe bağlı)", p.get("headline", ""), key=_k(slug, "target"))
        job = c2.text_area("Hedef ilan metni (isteğe bağlı) — yapıştırırsanız sorular bu ilana göre olur",
                           key=_k(slug, "job"), height=100)
        done = len(p.get("qa_log", []))
        if done:
            st.caption(f"Daha önce {done} soru cevaplandı; onlar tekrar sorulmaz.")
        if st.button(f"🔍 {rnd}. tur: CV'mi incele ve soru sor (yaklaşık 1-2 dk)", type="primary"):
            with st.status("Yapay zekâ koçu çalışıyor...", expanded=True) as status:
                st.write("📋 CV detaylı kontrol listesinden geçiriliyor...")
                st.write("🤖 Yapay zekâ CV'yi bir İK uzmanı gözüyle okuyor (yaklaşık 1-2 dk)...")
                qs, err = ci.build_questions(p, original, target, job)
                st.write(f"✅ {len(qs)} soru hazır.")
                status.update(label=f"{len(qs)} soru hazır", state="complete")
            st.session_state[_k(slug, "questions")] = qs
            if err:
                set_flash("cv", "warning", "⚠️ Yapay zekâya ulaşılamadı (LM Studio açık mı?). Şimdilik kural tabanlı "
                                           f"sorular gösteriliyor. Ayrıntı: {err[:150]}")
            st.rerun()
        return
    if not qs:
        st.success("🎉 Sorulacak yeni bir şey kalmadı; CV'niz güçlü görünüyor.")
        if st.button("Devam: Kontrol et →", type="primary"):
            st.session_state.pop(_k(slug, "questions"), None)
            _go(slug, 4)
        return

    with st.chat_message("assistant", avatar="🤖"):
        st.markdown(f"Merhaba {(p.get('name') or '').split(' ')[0]}! CV'nizi okudum. **{len(qs)} sorum var** "
                    f"({rnd}. tur). Bilmediğiniz ya da CV'de görünmesini istemediğiniz soruyu boş bırakın; "
                    "cevaplarınızı CV diline ben çevireceğim, son kararı siz vereceksiniz.")
    with st.form(_k(slug, f"form{rnd}")):
        answers = {}
        for i, q in enumerate(qs):
            with st.chat_message("assistant", avatar="🤖" if q["source"] == "yapay zekâ" else "📋"):
                st.markdown(f"**{i + 1}. {q['question']}**")
                if q.get("why"):
                    st.markdown(f"<div class='cvx-why'>Neden soruyorum: {_html.escape(q['why'])}</div>",
                                unsafe_allow_html=True)
            with st.chat_message("user", avatar="👤"):
                if q["kind"] == "yesno":
                    answers[q["key"]] = st.radio("Cevap", ["Evet", "Hayır"], index=None, horizontal=True,
                                                 key=_k(slug, f"a{rnd}_{i}"), label_visibility="collapsed") or ""
                else:
                    answers[q["key"]] = st.text_area("Cevap", key=_k(slug, f"a{rnd}_{i}"), height=68,
                                                     placeholder=("Örn: " + q["example"]) if q.get("example") else "Cevabınız...",
                                                     label_visibility="collapsed")
        c1, c2 = st.columns(2)
        go = c1.form_submit_button("✍️ Cevaplarımı CV'ye işle", type="primary", width="stretch")
        skip = c2.form_submit_button("Bu turu atla", width="stretch")
    if skip:
        st.session_state.pop(_k(slug, "questions"), None)
        _go(slug, 4)
    if go:
        qa = [{**q, "answer": answers.get(q["key"], "")} for q in qs]
        with st.status("Cevaplarınız CV'ye işleniyor...", expanded=True) as status:
            st.write("✍️ Yapay zekâ cevaplarınızı CV diline çeviriyor...")
            props = ci.propose_edits(p, original, qa)
            st.write(f"🛡️ Uydurma denetimi: {len(props['accepted'])} öneri geçti, {len(props['rejected'])} reddedildi.")
            status.update(label="Öneriler hazır", state="complete")
        st.session_state[_k(slug, "props")] = {**props, "qa": qa}
        st.rerun()


def _coach_review(slug, p, props, rnd):
    if props.get("ai_error"):
        st.warning("⚠️ Yapay zekâ cevapları düzenleyemedi; cevaplarınız olduğu gibi eklenmek üzere hazırlandı. "
                   "İsterseniz 4. adımda elle düzeltebilirsiniz.")
    with st.chat_message("assistant", avatar="🤖"):
        st.markdown(f"Cevaplarınızdan **{len(props['accepted'])} değişiklik** hazırladım. Her birini CV'nize ve "
                    "cevaplarınıza karşı denetledim. Uygulamak istemediklerinizin işaretini kaldırın.")
    picks = []
    for k, e in enumerate(props["accepted"]):
        c1, c2 = st.columns([1, 12])
        ok = c1.checkbox("Uygula", value=True, key=_k(slug, f"pk{rnd}_{k}"), label_visibility="collapsed")
        c2.markdown(_diff(e.get("old") or "", e["new"], e["label"]), unsafe_allow_html=True)
        if ok:
            picks.append(e)
    if not props["accepted"]:
        st.info("Cevaplarınızdan CV'ye eklenecek bir değişiklik çıkmadı.")
    if props["rejected"]:
        with st.expander(f"🚫 {len(props['rejected'])} öneri denetimden geçemedi (uydurma ya da bilgi kaybı)"):
            for r in props["rejected"]:
                st.markdown(f"- _{r['new'][:250]}_ → {'; '.join(r['why'])}")
    c1, c2 = st.columns(2)
    if c1.button(f"✅ Onayla ve CV'yi güncelle ({len(picks)} değişiklik)", type="primary", width="stretch"):
        skipped = ci.apply_edits(p, picks, props["qa"])
        cs.save_profile(slug, p)
        _reset_edit_widgets(slug)
        if skipped:
            set_flash("cv", "warning", f"⚠️ {len(skipped)} değişiklik uygulanmadı: öneriden sonra CV'nin o kısmı "
                                       "değişmişti (yanlış yere yazılmasın diye atlandı).")
        after = ca.score(_checks(slug, p))
        before = st.session_state.get(_k(slug, "score_before"), after)
        for name in ("questions", "props"):
            st.session_state.pop(_k(slug, name), None)
        st.session_state[_k(slug, "round")] = rnd + 1
        st.session_state[_k(slug, "last_round")] = {"n": len(picks), "before": before, "after": after}
        st.rerun()
    if c2.button("Vazgeç (hiçbir şey değişmesin)", width="stretch"):
        for name in ("questions", "props"):
            st.session_state.pop(_k(slug, name), None)
        st.rerun()


def _round_result(slug):
    last = st.session_state.get(_k(slug, "last_round"))
    if not last:
        return
    diff = last["after"] - last["before"]
    st.success(f"✅ {last['n']} değişiklik uygulandı. CV kalite puanı: {last['before']} → {last['after']}"
               + (f" (+{diff})" if diff > 0 else ""))
    c1, c2 = st.columns(2)
    if c1.button("🔁 Bir tur daha: yeni sorular sor", width="stretch"):
        st.session_state.pop(_k(slug, "last_round"), None)
        st.rerun()
    if c2.button("👁️ Devam: CV'yi kontrol et →", type="primary", width="stretch"):
        st.session_state.pop(_k(slug, "last_round"), None)
        _go(slug, 4)
    return True


# ---------------------------------------------------------------- 4) kontrol et ve düzenle
@st.fragment
def _step_review(slug, p, original):
    st.markdown("#### 🔎 Kontrol edin ve düzenleyin")
    _score_box(slug, p)
    preview, panel = st.columns([3, 2])
    with panel:  # önce düzenleme alanı çalışır → önizleme yazdığınız anda güncellenir
        tabs = st.tabs(["✏️ Düzenle", "🔎 Detaylı kontrol", "✨ Parlat", f"🗂️ Cevaplar ({len(p.get('qa_log', []))})"])
        with tabs[0]:
            _edit(slug, p)
        with tabs[1]:
            _checklist(slug, p)
        with tabs[2]:
            _improve(slug, p, original)
        with tabs[3]:
            if not p.get("qa_log"):
                st.caption("Koça henüz cevap vermediniz.")
            for q in p.get("qa_log", []):
                st.markdown(f"- **{q['question']}**  \n  {q['answer'] or '_(boş bırakıldı)_'}")
    with preview:
        t = p.get("template") or "modern"
        st.caption(f"Canlı önizleme — {cs.TEMPLATE_INFO.get(t, {}).get('label', t)} "
                   "(kaydedilmemiş değişiklikler de görünür; formatı 2. adımdan değiştirebilirsiniz)")
        st.iframe(cs.render_html(p, t, cs.template_photo(slug, t), p.get("accent") or "#1f4e79"), height=1000)
    if st.button("Devam: İndir →", type="primary"):
        _go(slug, 5)


def _edit(slug, p):
    c = st.columns(2)
    p["name"] = c[0].text_input("Ad Soyad", p["name"], key=_k(slug, "e_name"))
    p["headline"] = c[1].text_input("Başlık (hedef unvan)", p["headline"], key=_k(slug, "e_head"))
    c = st.columns(3)
    p["email"] = c[0].text_input("E-posta", p["email"], key=_k(slug, "e_mail"))
    p["phone"] = c[1].text_input("Telefon", p["phone"], key=_k(slug, "e_tel"))
    p["city"] = c[2].text_input("Şehir", p["city"], key=_k(slug, "e_city"))
    p["links"] = [x.strip() for x in st.text_input("Bağlantılar (virgülle)", ", ".join(p["links"]), key=_k(slug, "e_links")).split(",") if x.strip()]
    p["summary"] = st.text_area("Özet", p["summary"], height=120, key=_k(slug, "e_sum"))
    for i, e in enumerate(p["experience"]):
        text = st.text_area(f"💼 {e['title']} — {e['company']} (her satır bir madde)", "\n".join(b["text"] for b in e["bullets"]),
                            key=_k(slug, f"e_b{i}"), height=140)
        old = {b["text"]: b.get("user", False) for b in e["bullets"]}
        e["bullets"] = [{"text": t.strip(), "user": old.get(t.strip(), True)} for t in text.splitlines() if t.strip()]
    text = st.text_area("🧰 Beceriler (her satır: Grup: beceri1, beceri2)",
                        "\n".join(f"{g['group']}: {', '.join(g['items'])}" for g in p["skills"]), height=150, key=_k(slug, "e_sk"))
    p["skills"] = [{"group": l.split(":", 1)[0].strip(), "items": [x.strip() for x in l.split(":", 1)[1].split(",") if x.strip()]}
                   for l in text.splitlines() if ":" in l]
    p["education"] = [x for x in st.text_area("🎓 Eğitim (her satır bir okul)", "\n".join(p["education"]), key=_k(slug, "e_ed")).splitlines() if x.strip()]
    p["certificates"] = [x for x in st.text_area("📜 Sertifikalar", "\n".join(p["certificates"]), key=_k(slug, "e_ce")).splitlines() if x.strip()]
    p["languages"] = st.text_input("🌍 Diller", p["languages"], key=_k(slug, "e_la"))
    p["extras"] = [x for x in st.text_area("➕ Ek bilgiler (ehliyet, askerlik, projeler...)", "\n".join(p["extras"]), key=_k(slug, "e_ex")).splitlines() if x.strip()]
    st.caption("CV'de olmayan yeni bir madde eklerseniz 'sizin beyanınız' olarak işaretlenir ve yapay zekâ denetiminde kaynak sayılır.")
    if st.button("💾 Kaydet", type="primary", key=_k(slug, "e_save")):
        cs.save_profile(slug, p)
        for name in ("questions", "props", "sugg"):  # eski maddelere dayanan bekleyen öneriler geçersiz
            st.session_state.pop(_k(slug, name), None)
        st.toast("✅ Kaydedildi")


def _improve(slug, p, original):
    target = st.text_input("Hedef unvan (isteğe bağlı)", p.get("headline", ""), key=_k(slug, "imp_t"))
    if st.button("✨ Yapay zekâ ile parlat (1-2 dk)", key=_k(slug, "imp_go")):
        with st.spinner("Öneriler üretiliyor ve her biri CV'nizle karşılaştırılıyor..."):
            try:
                st.session_state[_k(slug, "sugg")] = cs.improve(p, original, target)
            except AIError as e:
                set_flash("cv", "error", f"❌ {e}")
        st.rerun()
    sugg = st.session_state.get(_k(slug, "sugg"))
    if not sugg:
        st.caption("Başlık, özet ve zayıf maddeleri daha etkili yazar. CV'de olmayan beceri, sayı veya iddia içeren "
                   "her öneri otomatik reddedilir.")
        return
    if not sugg["accepted"]:
        st.info("Kabul edilebilir öneri çıkmadı.")
    picks = []
    for k, sgg in enumerate(sugg["accepted"]):
        ok = st.checkbox(f"Uygula · {sgg['where']}", value=True, key=_k(slug, f"imp_{k}"))
        st.markdown(f"~~{sgg['old'][:300]}~~  \n**→ {sgg['new']}**")
        if ok:
            picks.append(sgg)
    if sugg["rejected"]:
        st.caption(f"🚫 {len(sugg['rejected'])} öneri uydurma/bilgi kaybı içerdiği için reddedildi.")
    if picks and st.button(f"✅ Seçilen {len(picks)} öneriyi uygula", type="primary", key=_k(slug, "imp_apply")):
        for sgg in picks:
            cs.apply_suggestion(p, sgg)
        cs.save_profile(slug, p)
        st.session_state.pop(_k(slug, "sugg"), None)
        _reset_edit_widgets(slug)
        set_flash("cv", "success", f"✅ {len(picks)} iyileştirme uygulandı.")
        st.rerun()


# ---------------------------------------------------------------- 5) indir
def _step_download(slug, p):
    st.markdown("#### ⬇️ İndirin")
    t = p.get("template") or "modern"
    info = cs.TEMPLATE_INFO.get(t, {})
    st.write(f"Format: **{info.get('label', t)}** · PDF + başvuru sistemleri için sade Word (ATS).")
    if st.button("⬇️ PDF ve Word üret", type="primary"):
        with st.spinner("PDF hazırlanıyor..."):
            st.session_state[_k(slug, "out")] = cs.export(slug, p, t, p.get("accent") or "#1f4e79")
        st.rerun()
    out = st.session_state.get(_k(slug, "out"))
    if out:
        d1, d2, d3 = st.columns(3)
        d1.download_button("📄 PDF indir", open(out["pdf"], "rb").read(), file_name=os.path.basename(out["pdf"]),
                           mime="application/pdf", width="stretch")
        if out.get("docx"):
            d2.download_button("📝 Word indir (ATS)", open(out["docx"], "rb").read(), file_name=os.path.basename(out["docx"]),
                               width="stretch")
        if d3.button("⭐ Bu CV'yi başvurularda kullan", help="İlan analizi ve başvurularda bu PDF kullanılır", width="stretch"):
            import shutil
            shutil.copyfile(out["pdf"], os.path.join(context.user_dir(), "cv.pdf"))
            set_flash("cv", "success", "✅ Artık analiz ve başvurularda bu CV kullanılıyor.")
            st.rerun()


# ---------------------------------------------------------------- sayfa
def page_cv():
    st.markdown(COMMON_CSS, unsafe_allow_html=True)
    _hero(len(cs.TEMPLATE_INFO))
    show_flash("cv")
    slug = context.current()  # herkes sadece kendi CV'sini görür
    exists = slug in cs.list_profiles()
    current = st.session_state.get(_k(slug, "step"), 2 if exists else 1)
    if not exists:
        current = 1
    _stepper(slug, current, exists)
    st.divider()
    if current == 1:
        return _step_import(slug, exists)
    p, original = cs.load_profile(slug)
    if current == 2:
        _step_format(slug, p)
    elif current == 3:
        if not _round_result(slug):
            _step_coach(slug, p, original)
    elif current == 4:
        _step_review(slug, p, original)
    else:
        _step_download(slug, p)
