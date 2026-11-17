"""CV Stüdyosu — adım adım:
01 Yükle → 02 Format (7 şablon) → 03 Koç: CV'yi okur, eksikleri SORAR, cevaplarla günceller → 04 Kontrol → 05 İndir.

Görünüm: kâğıt + mürekkep (dergi sayfası). Tema renkleri .streamlit/config.toml'da; sayfaya özel stil aşağıdaki CSS'te.
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

STEPS = ["Yükle", "Format", "Koç", "Kontrol", "İndir"]
INK, MUTED, RULE, ACCENT = "#1F1B16", "#6B6257", "#E2D9CA", "#B4532A"
LEVEL = {"kritik": ("kritik", "#B4532A"), "önemli": ("önemli", "#B7791F"), "öneri": ("öneri", "#6B6257")}

CSS = f"""<style>
.cvx-mast {{padding: 6px 0 18px; border-bottom: 1px solid {RULE}; margin-bottom: 6px;}}
.cvx-over {{font-family: 'IBM Plex Mono', monospace; font-size: .72rem; letter-spacing: .16em; text-transform: uppercase;
  color: {MUTED};}}
.cvx-mast h1 {{font-family: 'Fraunces', Georgia, serif; font-weight: 600; font-size: 2.6rem; line-height: 1.08;
  margin: 8px 0 10px; padding: 0; color: {INK};}}
.cvx-mast h1 em {{color: {ACCENT}; font-style: italic;}}
.cvx-lede {{font-size: 1.05rem; max-width: 46rem; color: #3D362E; margin: 0;}}
.cvx-facts {{margin-top: 14px; display: flex; flex-wrap: wrap; gap: 0;}}
.cvx-facts span {{font-family: 'IBM Plex Mono', monospace; font-size: .74rem; color: {MUTED}; padding: 0 14px;
  border-left: 1px solid {RULE};}}
.cvx-facts span:first-child {{padding-left: 0; border-left: none;}}
/* adım çubuğu: sekme gibi, altı çizili */
[class*="st-key-cv_nav"] button {{background: transparent !important; border: none !important; border-radius: 0 !important;
  border-bottom: 2px solid {RULE} !important; box-shadow: none !important; justify-content: flex-start !important;
  padding: 6px 2px !important; color: {MUTED} !important;}}
[class*="st-key-cv_nav"] button p {{font-family: 'IBM Plex Mono', monospace; font-size: .8rem; letter-spacing: .04em;}}
[class*="st-key-cv_nav"] button[data-testid="stBaseButton-primary"] {{color: {INK} !important;
  border-bottom-color: {ACCENT} !important;}}
[class*="st-key-cv_nav"] button[data-testid="stBaseButton-primary"] p {{font-weight: 600;}}
.cvx-sect {{display: flex; gap: 16px; align-items: baseline; margin: 18px 0 4px;}}
.cvx-sect .n {{font-family: 'Fraunces', Georgia, serif; font-size: 2.2rem; color: {ACCENT}; line-height: 1;}}
.cvx-sect h3 {{font-family: 'Fraunces', Georgia, serif; margin: 0; padding: 0; font-size: 1.5rem;}}
.cvx-sect p {{margin: 2px 0 0; color: {MUTED}; font-size: .92rem; max-width: 52rem;}}
.cvx-q {{display: grid; grid-template-columns: 44px 1fr; gap: 6px; padding-top: 14px; border-top: 1px solid {RULE};}}
.cvx-q .num {{font-family: 'IBM Plex Mono', monospace; color: {ACCENT}; font-size: .85rem; padding-top: 3px;}}
.cvx-q .q {{font-family: 'Fraunces', Georgia, serif; font-size: 1.13rem; line-height: 1.35; color: {INK};}}
.cvx-q .why {{font-size: .84rem; color: {MUTED}; font-style: italic; margin-top: 3px;}}
.cvx-q .src {{font-family: 'IBM Plex Mono', monospace; font-size: .66rem; letter-spacing: .1em; text-transform: uppercase;
  color: {MUTED}; margin-left: 8px; font-style: normal;}}
.cvx-note {{font-family: 'Fraunces', Georgia, serif; font-style: italic; font-size: 1.08rem; color: #3D362E;
  border-left: 2px solid {ACCENT}; padding: 2px 0 2px 14px; margin: 8px 0 14px;}}
.cvx-diff {{padding: 6px 0 10px; border-bottom: 1px dashed {RULE};}}
.cvx-diff .tag {{font-family: 'IBM Plex Mono', monospace; font-size: .68rem; letter-spacing: .1em; text-transform: uppercase;
  color: {MUTED};}}
.cvx-diff .old {{color: {MUTED}; text-decoration: line-through; text-decoration-color: {ACCENT}; margin: 3px 0;}}
.cvx-diff .new {{color: {INK}; border-left: 3px solid {ACCENT}; padding-left: 10px; margin-top: 3px;}}
.cvx-card-title {{font-family: 'Fraunces', Georgia, serif; font-size: 1.12rem; color: {INK};}}
.cvx-picked {{font-family: 'IBM Plex Mono', monospace; font-size: .68rem; color: {ACCENT}; letter-spacing: .12em; margin-left: 6px;}}
.cvx-meta {{font-size: .8rem; color: {MUTED};}}
.cvx-chk {{display: grid; grid-template-columns: 74px 1fr; gap: 8px; padding: 5px 0; border-bottom: 1px solid {RULE};
  font-size: .9rem;}}
.cvx-chk .lv {{font-family: 'IBM Plex Mono', monospace; font-size: .7rem; letter-spacing: .06em; text-transform: uppercase;
  padding-top: 2px;}}
.cvx-chk .tip {{display: block; color: {MUTED}; font-size: .8rem;}}
.cvx-chk.ok {{color: {MUTED};}}
</style>"""


def _md(html_str):
    st.markdown(html_str, unsafe_allow_html=True)


def _masthead(n_templates):
    _md(CSS)
    _md(f"""<div class="cvx-mast"><div class="cvx-over">Kariyer Otonomu · CV Stüdyosu</div>
<h1>CV'nizi birlikte <em>yeniden</em> yazalım.</h1>
<p class="cvx-lede">Siz anlatın, biz düzenleyelim. Koç CV'nizde eksik kalan yerleri size sorar; CV'ye yalnızca sizin
söyledikleriniz girer.</p>
<div class="cvx-facts"><span>{n_templates} format</span><span>sizi dinleyen koç</span><span>uydurma yok</span>
<span>veriler bu bilgisayarda</span></div></div>""")


def _section(n, title, note=""):
    _md(f"""<div class="cvx-sect"><span class="n">{n:02d}</span><div><h3>{_html.escape(title)}</h3>
{f'<p>{note}</p>' if note else ''}</div></div>""")


def _diff(old, new, label):
    old_html = f"<div class='old'>{_html.escape(old[:500])}</div>" if old else ""
    return (f"<div class='cvx-diff'><span class='tag'>{_html.escape(label)}</span>{old_html}"
            f"<div class='new'>{_html.escape(new)}</div></div>")


def _k(slug, name):
    return f"cv_{name}_{slug}"


def _reset_pending(slug):
    """CV değişti (yeni CV, elle kayıt): eski indekslere dayanan bekleyen öneriler geçersiz."""
    for name in ("questions", "props", "sugg", "out", "last_round"):
        st.session_state.pop(_k(slug, name), None)


def _reset_edit_widgets(slug):
    """Düzenleme kutuları eski metni tutmasın (kaydedilen yeni metin görünsün)."""
    for key in [k for k in st.session_state if isinstance(k, str) and k.startswith("cv_e_") and k.endswith(f"_{slug}")]:
        st.session_state.pop(key, None)


def _go(slug, n):
    st.session_state[_k(slug, "step")] = n
    st.rerun()


# ---------------------------------------------------------------- adım çubuğu
def _stepper(slug, current, enabled):
    cols = st.columns(len(STEPS))
    for i, (c, label) in enumerate(zip(cols, STEPS), 1):
        done = "  ✓" if i < current else ""
        if c.button(f"{i:02d}  {label}{done}", key=_k(slug, f"nav{i}"), width="stretch",
                    type="primary" if i == current else "secondary", disabled=not enabled and i > 1):
            _go(slug, i)


def _checks(slug, p, job=""):
    return ca.audit(p, job_text=job, has_photo=cs.photo_data_uri(slug) is not None,
                    template=p.get("template") or "modern", field=context.field())


def _level(c):
    name, color = LEVEL[c["level"]]
    return f"<span class='lv' style='color:{color}'>{name}</span>"


def _score_box(slug, p, job=""):
    checks = _checks(slug, p, job)
    score, bad = ca.score(checks), ca.failing(checks)
    c1, c2 = st.columns([1, 3])
    c1.metric("CV kalite puanı", f"{score}/100", help=f"{len(checks)} maddelik kontrol listesine göre")
    with c2:
        st.progress(score / 100)
        rows = "".join(f"<div class='cvx-chk'>{_level(c)}<div>{_html.escape(c['area'])} — {_html.escape(c['msg'])}</div></div>"
                       for c in bad[:3])
        more = f"<div class='cvx-meta' style='margin-top:6px'>ve {len(bad) - 3} madde daha · 04 Kontrol → Kontrol listesi</div>" \
            if len(bad) > 3 else ""
        _md(rows + more)
    return score


def _checklist(slug, p):
    job = st.text_area("Hedef ilan metni (isteğe bağlı) — yapıştırırsanız ilandaki anahtar kelimeler de kontrol edilir",
                       key=_k(slug, "chk_job"), height=80)
    checks = _checks(slug, p, job)
    _md(f"<div class='cvx-meta'>{sum(c['ok'] for c in checks)} / {len(checks)} madde tamam</div>")
    for area in dict.fromkeys(c["area"] for c in checks):
        items = [c for c in checks if c["area"] == area]
        ok = all(c["ok"] for c in items)
        with st.expander(f"{area}   {sum(c['ok'] for c in items)}/{len(items)}", expanded=not ok):
            rows = []
            for c in items:
                if c["ok"]:
                    rows.append(f"<div class='cvx-chk ok'><span class='lv'>tamam</span><div>{_html.escape(c['msg'])}</div></div>")
                else:
                    tip = f"<span class='tip'>{_html.escape(c['tip'])}</span>" if c.get("tip") else ""
                    rows.append(f"<div class='cvx-chk'>{_level(c)}<div>{_html.escape(c['msg'])}{tip}</div></div>")
            _md("".join(rows))
    if ca.failing(checks) and st.button("Eksikleri koça sordur →", key=_k(slug, "chk_go")):
        _go(slug, 3)


# ---------------------------------------------------------------- 01 yükle
def _step_import(slug, exists):
    _section(1, "CV'nizi yükleyin", "PDF veya Word. LinkedIn profilinizi de kullanabilirsiniz: "
                                    "LinkedIn → Profil → Daha fazla → PDF olarak kaydet.")
    c1, c2 = st.columns(2)
    up = c1.file_uploader("CV dosyası (PDF / DOCX)", type=["pdf", "docx", "txt"], key=_k(slug, "up"))
    if up and c1.button("Bu CV'yi içe aktar", type="primary", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(up.getvalue(), up.name))
        _save_import(slug, text, f"{up.name} içe aktarıldı")
    main_cv = context.cv_path()
    if os.path.exists(main_cv) and c2.button("Kayıtlı CV'mi kullan", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(open(main_cv, "rb").read(), main_cv))
        _save_import(slug, text, "Sistemdeki CV içe aktarıldı")
    if exists:
        c2.caption("Kayıtlı bir CV profiliniz var. Yeni CV yüklerseniz onun yerine geçer.")
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
    set_flash("cv", "success", f"{msg}: {len(p['experience'])} deneyim, {sum(len(g['items']) for g in p['skills'])} beceri." +
              ("  \nKontrol edin: " + "; ".join(p["_warnings"]) if p.get("_warnings") else ""))
    _go(slug, 2)


# ---------------------------------------------------------------- 02 format
def _thumb(doc, height=330, scale=0.29):
    """Şablonun küçük önizlemesi (A4 = 794x1123 px, ölçekli)."""
    src = _html.escape(doc, quote=True)
    st.iframe(
        f"""<div style="width:{int(794 * scale)}px;height:{height}px;overflow:hidden;border:1px solid {RULE};
background:#fff;margin:auto"><iframe srcdoc="{src}" style="width:794px;height:1123px;border:0;transform:scale({scale});
transform-origin:0 0;pointer-events:none"></iframe></div>""", height=height + 6)


@st.fragment
def _step_format(slug, p):
    _section(2, "Bir format seçin", "Önizlemeler sizin bilgilerinizle hazırlandı. Hangisini seçerseniz seçin, "
                                   "başvuru sistemleri için sade bir Word (ATS) dosyası da üretilir.")
    c1, c2 = st.columns([1, 2])
    accent = c1.color_picker("Vurgu rengi", p.get("accent") or "#1f4e79", key=_k(slug, "accent"))
    photo = c2.file_uploader("Fotoğraf (isteğe bağlı, fotoğraflı formatlar için)", type=["jpg", "jpeg", "png"],
                             key=_k(slug, "photo"))
    if photo:
        cs.save_photo(slug, photo.getvalue(), photo.name)
    names = list(cs.TEMPLATE_INFO)
    for row in range(0, len(names), 4):
        cols = st.columns(4)
        for c, t in zip(cols, names[row:row + 4]):
            info = cs.TEMPLATE_INFO[t]
            chosen = p.get("template") == t
            with c:
                with st.container(border=True):
                    _md(f"<div class='cvx-card-title'>{info['label']}"
                        f"{'<span class=cvx-picked>SEÇİLİ</span>' if chosen else ''}</div>")
                    _thumb(cs.render_html(p, t, cs.template_photo(slug, t), accent))
                    tags = " · ".join(x for x in ("ATS dostu" if info["ats"] else "", "fotoğraflı" if info["photo"] else "") if x)
                    _md(f"<div class='cvx-meta'>{info['desc']}<br><b>Kime:</b> {info['best']}"
                        f"{'<br>' + tags if tags else ''}</div>")
                    if st.button("Seçili" if chosen else "Bu formatı seç", key=_k(slug, f"pick_{t}"), width="stretch",
                                 type="primary" if chosen else "secondary", disabled=chosen):
                        p["template"], p["accent"] = t, accent
                        cs.save_profile(slug, p)
                        st.rerun()
    if accent != p.get("accent"):
        p["accent"] = accent
        cs.save_profile(slug, p)
    if st.button("Devam: koçla konuşun →", type="primary"):
        _go(slug, 3)


# ---------------------------------------------------------------- 03 koç
def _step_coach(slug, p, original):
    _section(3, "Koçla konuşun", "Koç CV'nizi bir İK uzmanı gözüyle okur ve eksik kalan yerleri size sorar. Kendisi "
                                 "bilgi eklemez: CV'de ya da cevaplarınızda olmayan sayı, beceri ve iddialar otomatik "
                                 "reddedilir. Her değişikliği siz onaylarsınız.")
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
        if st.button(f"{rnd}. tur: CV'mi oku ve bana sor (1-2 dk)", type="primary"):
            with st.status("Koç CV'nizi okuyor...", expanded=True) as status:
                st.write("Kontrol listesinden geçiriliyor...")
                st.write("Bir İK uzmanı gözüyle okunuyor; işverenin soracakları çıkarılıyor...")
                qs, err = ci.build_questions(p, original, target, job)
                status.update(label=f"{len(qs)} soru hazır", state="complete")
            st.session_state[_k(slug, "questions")] = qs
            if err:
                set_flash("cv", "warning", "Yerel modele ulaşılamadı (LM Studio açık mı?). Şimdilik kontrol listesinden "
                                           f"çıkan sorular gösteriliyor. Ayrıntı: {err[:150]}")
            st.rerun()
        return
    if not qs:
        st.success("Sorulacak yeni bir şey kalmadı; CV'niz güçlü görünüyor.")
        if st.button("Devam: kontrol →", type="primary"):
            st.session_state.pop(_k(slug, "questions"), None)
            _go(slug, 4)
        return

    first = (p.get("name") or "").split(" ")[0]
    _md(f"<div class='cvx-note'>{_html.escape(first)}, CV'nizi okudum. {len(qs)} sorum var. Bilmediğiniz ya da "
        "CV'de görünmesini istemediğiniz soruyu boş bırakın; cevaplarınızı CV diline ben çeviririm, son söz sizin.</div>")
    with st.form(_k(slug, f"form{rnd}")):
        answers = {}
        for i, q in enumerate(qs):
            src = "kontrol listesi" if q["source"] == "kural" else "koç"
            why = f"<div class='why'>{_html.escape(q['why'])}<span class='src'>{src}</span></div>" if q.get("why") else ""
            _md(f"<div class='cvx-q'><div class='num'>{i + 1:02d}</div><div><div class='q'>{_html.escape(q['question'])}</div>"
                f"{why}</div></div>")
            if q["kind"] == "yesno":
                answers[q["key"]] = st.radio("Cevap", ["Evet", "Hayır"], index=None, horizontal=True,
                                             key=_k(slug, f"a{rnd}_{i}"), label_visibility="collapsed") or ""
            else:
                answers[q["key"]] = st.text_area("Cevap", key=_k(slug, f"a{rnd}_{i}"), height=68,
                                                 placeholder=("Örn: " + q["example"]) if q.get("example") else "Cevabınız",
                                                 label_visibility="collapsed")
        c1, c2 = st.columns(2)
        go = c1.form_submit_button("Cevaplarımı CV'ye işle", type="primary", width="stretch")
        skip = c2.form_submit_button("Bu turu atla", width="stretch")
    if skip:
        st.session_state.pop(_k(slug, "questions"), None)
        _go(slug, 4)
    if go:
        qa = [{**q, "answer": answers.get(q["key"], "")} for q in qs]
        with st.status("Cevaplarınız CV'ye işleniyor...", expanded=True) as status:
            st.write("Cevaplar CV diline çevriliyor...")
            props = ci.propose_edits(p, original, qa)
            st.write(f"Denetim: {len(props['accepted'])} öneri geçti, {len(props['rejected'])} reddedildi.")
            status.update(label="Öneriler hazır", state="complete")
        st.session_state[_k(slug, "props")] = {**props, "qa": qa}
        st.rerun()


def _coach_review(slug, p, props, rnd):
    if props.get("ai_error"):
        st.warning("Yerel model cevapları düzenleyemedi; cevaplarınız olduğu gibi eklenmek üzere hazırlandı. "
                   "İsterseniz 04 Kontrol adımında elle düzeltebilirsiniz.")
    _md(f"<div class='cvx-note'>Cevaplarınızdan {len(props['accepted'])} değişiklik çıkardım ve her birini CV'nize ve "
        "cevaplarınıza karşı denetledim. Uygulamak istemediklerinizin işaretini kaldırın.</div>")
    picks = []
    for k, e in enumerate(props["accepted"]):
        c1, c2 = st.columns([1, 14])
        ok = c1.checkbox("Uygula", value=True, key=_k(slug, f"pk{rnd}_{k}"), label_visibility="collapsed")
        c2.markdown(_diff(e.get("old") or "", e["new"], e["label"]), unsafe_allow_html=True)
        if ok:
            picks.append(e)
    if not props["accepted"]:
        st.info("Cevaplarınızdan CV'ye eklenecek bir değişiklik çıkmadı.")
    if props["rejected"]:
        with st.expander(f"Denetimden geçemeyen {len(props['rejected'])} öneri (uydurma ya da bilgi kaybı)"):
            for r in props["rejected"]:
                st.markdown(f"- _{r['new'][:250]}_ → {'; '.join(r['why'])}")
    c1, c2 = st.columns(2)
    if c1.button(f"Onayla ve CV'yi güncelle ({len(picks)} değişiklik)", type="primary", width="stretch"):
        skipped = ci.apply_edits(p, picks, props["qa"])
        cs.save_profile(slug, p)
        _reset_edit_widgets(slug)
        if skipped:
            set_flash("cv", "warning", f"{len(skipped)} değişiklik uygulanmadı: öneriden sonra CV'nin o kısmı "
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
    st.success(f"{last['n']} değişiklik uygulandı. CV kalite puanı: {last['before']} → {last['after']}"
               + (f" (+{diff})" if diff > 0 else ""))
    c1, c2 = st.columns(2)
    if c1.button("Bir tur daha: yeni sorular", width="stretch"):
        st.session_state.pop(_k(slug, "last_round"), None)
        st.rerun()
    if c2.button("Devam: kontrol →", type="primary", width="stretch"):
        st.session_state.pop(_k(slug, "last_round"), None)
        _go(slug, 4)
    return True


# ---------------------------------------------------------------- 04 kontrol ve düzenle
@st.fragment
def _step_review(slug, p, original):
    _section(4, "Kontrol edin", "Soldaki önizleme siz yazarken güncellenir. Kaydetmeyi unutmayın.")
    _score_box(slug, p)
    preview, panel = st.columns([3, 2])
    with panel:  # önce düzenleme alanı çalışır → önizleme yazdığınız anda güncellenir
        tabs = st.tabs(["Düzenle", "Kontrol listesi", "Parlat", f"Cevaplarım ({len(p.get('qa_log', []))})"])
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
        st.caption(f"Önizleme · {cs.TEMPLATE_INFO.get(t, {}).get('label', t)} (formatı 02'den değiştirebilirsiniz)")
        st.iframe(cs.render_html(p, t, cs.template_photo(slug, t), p.get("accent") or "#1f4e79"), height=1000)
    if st.button("Devam: indir →", type="primary"):
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
        text = st.text_area(f"{e['title']} — {e['company']} (her satır bir madde)", "\n".join(b["text"] for b in e["bullets"]),
                            key=_k(slug, f"e_b{i}"), height=140)
        old = {b["text"]: b.get("user", False) for b in e["bullets"]}
        e["bullets"] = [{"text": t.strip(), "user": old.get(t.strip(), True)} for t in text.splitlines() if t.strip()]
    text = st.text_area("Beceriler (her satır: Grup: beceri1, beceri2)",
                        "\n".join(f"{g['group']}: {', '.join(g['items'])}" for g in p["skills"]), height=150, key=_k(slug, "e_sk"))
    p["skills"] = [{"group": l.split(":", 1)[0].strip(), "items": [x.strip() for x in l.split(":", 1)[1].split(",") if x.strip()]}
                   for l in text.splitlines() if ":" in l]
    p["education"] = [x for x in st.text_area("Eğitim (her satır bir okul)", "\n".join(p["education"]), key=_k(slug, "e_ed")).splitlines() if x.strip()]
    p["certificates"] = [x for x in st.text_area("Sertifikalar", "\n".join(p["certificates"]), key=_k(slug, "e_ce")).splitlines() if x.strip()]
    p["languages"] = st.text_input("Diller", p["languages"], key=_k(slug, "e_la"))
    p["extras"] = [x for x in st.text_area("Ek bilgiler (ehliyet, askerlik, projeler...)", "\n".join(p["extras"]), key=_k(slug, "e_ex")).splitlines() if x.strip()]
    st.caption("CV'de olmayan yeni bir madde eklerseniz 'sizin beyanınız' olarak işaretlenir ve denetimde kaynak sayılır.")
    if st.button("Kaydet", type="primary", key=_k(slug, "e_save")):
        cs.save_profile(slug, p)
        for name in ("questions", "props", "sugg"):  # eski maddelere dayanan bekleyen öneriler geçersiz
            st.session_state.pop(_k(slug, name), None)
        st.toast("Kaydedildi")


def _improve(slug, p, original):
    target = st.text_input("Hedef unvan (isteğe bağlı)", p.get("headline", ""), key=_k(slug, "imp_t"))
    if st.button("Metni parlat (1-2 dk)", key=_k(slug, "imp_go")):
        with st.spinner("Öneriler üretiliyor ve her biri CV'nizle karşılaştırılıyor..."):
            try:
                st.session_state[_k(slug, "sugg")] = cs.improve(p, original, target)
            except AIError as e:
                set_flash("cv", "error", str(e))
        st.rerun()
    sugg = st.session_state.get(_k(slug, "sugg"))
    if not sugg:
        st.caption("Başlık, özet ve zayıf maddeleri daha etkili yazar; bilgi eklemez. CV'de olmayan beceri, sayı veya "
                   "iddia içeren öneri otomatik reddedilir.")
        return
    if not sugg["accepted"]:
        st.info("Kabul edilebilir öneri çıkmadı.")
    picks = []
    for k, sgg in enumerate(sugg["accepted"]):
        ok = st.checkbox(f"Uygula · {sgg['where']}", value=True, key=_k(slug, f"imp_{k}"))
        _md(_diff(sgg["old"], sgg["new"], sgg["where"]))
        if ok:
            picks.append(sgg)
    if sugg["rejected"]:
        st.caption(f"{len(sugg['rejected'])} öneri uydurma ya da bilgi kaybı içerdiği için reddedildi.")
    if picks and st.button(f"Seçilen {len(picks)} öneriyi uygula", type="primary", key=_k(slug, "imp_apply")):
        for sgg in picks:
            cs.apply_suggestion(p, sgg)
        cs.save_profile(slug, p)
        st.session_state.pop(_k(slug, "sugg"), None)
        _reset_edit_widgets(slug)
        set_flash("cv", "success", f"{len(picks)} iyileştirme uygulandı.")
        st.rerun()


# ---------------------------------------------------------------- 05 indir
def _step_download(slug, p):
    t = p.get("template") or "modern"
    info = cs.TEMPLATE_INFO.get(t, {})
    _section(5, "İndirin", f"Format: {info.get('label', t)}. PDF ve başvuru sistemleri için sade Word (ATS).")
    if st.button("PDF ve Word üret", type="primary"):
        with st.spinner("PDF hazırlanıyor..."):
            st.session_state[_k(slug, "out")] = cs.export(slug, p, t, p.get("accent") or "#1f4e79")
        st.rerun()
    out = st.session_state.get(_k(slug, "out"))
    if out:
        d1, d2, d3 = st.columns(3)
        d1.download_button("PDF indir", open(out["pdf"], "rb").read(), file_name=os.path.basename(out["pdf"]),
                           mime="application/pdf", width="stretch")
        if out.get("docx"):
            d2.download_button("Word indir (ATS)", open(out["docx"], "rb").read(), file_name=os.path.basename(out["docx"]),
                               width="stretch")
        if d3.button("Bu CV'yi başvurularda kullan", help="İlan analizi ve başvurularda bu PDF kullanılır", width="stretch"):
            import shutil
            shutil.copyfile(out["pdf"], os.path.join(context.user_dir(), "cv.pdf"))
            set_flash("cv", "success", "Artık analiz ve başvurularda bu CV kullanılıyor.")
            st.rerun()


# ---------------------------------------------------------------- sayfa
def page_cv():
    _md(COMMON_CSS)
    _masthead(len(cs.TEMPLATE_INFO))
    show_flash("cv")
    slug = context.current()  # herkes sadece kendi CV'sini görür
    exists = slug in cs.list_profiles()
    current = st.session_state.get(_k(slug, "step"), 2 if exists else 1)
    if not exists:
        current = 1
    _stepper(slug, current, exists)
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
