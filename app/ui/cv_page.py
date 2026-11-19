"""CV Stüdyosu — adım adım:
1 Yükle → 2 Format (7 şablon) → 3 Koç: CV'yi okur, eksikleri SORAR, cevaplarla günceller → 4 Kontrol → 5 İndir.

Görünüm: beyaz, modern kartlar. Tema renkleri .streamlit/config.toml'da; sayfaya özel stil aşağıdaki CSS'te.
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
INK, MUTED, RULE, ACCENT = "#0F172A", "#64748B", "#E5E8EF", "#0A66FF"
LEVEL = {"kritik": ("Kritik", "#DC2626", "#FEF2F2"), "önemli": ("Önemli", "#D97706", "#FFFBEB"),
         "öneri": ("Öneri", "#0A66FF", "#EFF5FF")}

CSS = f"""<style>
.cvx-mast {{padding: 4px 0 20px;}}
.cvx-over {{font-size: .8rem; font-weight: 700; color: {ACCENT};}}
.cvx-mast h1 {{font-weight: 800; font-size: 2.7rem; line-height: 1.08; letter-spacing: -.035em; margin: 6px 0 10px;
  padding: 0; color: {INK};}}
.cvx-mast h1 span {{color: {ACCENT};}}
.cvx-lede {{font-size: 1.06rem; max-width: 44rem; color: #475569; margin: 0;}}
.cvx-facts {{margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px 22px;}}
.cvx-facts span {{font-size: .86rem; font-weight: 600; color: #334155;}}
.cvx-facts span::before {{content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: {ACCENT}; margin-right: 8px; vertical-align: middle;}}
.cvx-sect {{margin: 22px 0 8px;}}
.cvx-sect .n {{display: inline-block; font-size: .74rem; font-weight: 700; color: {ACCENT}; background: #EFF5FF;
  border-radius: 999px; padding: 3px 10px; margin-bottom: 6px;}}
.cvx-sect h3 {{font-weight: 800; margin: 0; padding: 0; font-size: 1.6rem; letter-spacing: -.02em;}}
.cvx-sect p {{margin: 4px 0 0; color: {MUTED}; font-size: .95rem; max-width: 52rem;}}
.cvx-q {{display: grid; grid-template-columns: 34px 1fr; gap: 12px; padding: 16px 0 6px; border-top: 1px solid {RULE};}}
.cvx-q:first-child {{border-top: none;}}
.cvx-q .num {{width: 30px; height: 30px; border-radius: 50%; background: {ACCENT}; color: #fff; font-weight: 700;
  font-size: .8rem; display: flex; align-items: center; justify-content: center;}}
.cvx-q .q {{font-size: 1.06rem; font-weight: 700; line-height: 1.4; color: {INK};}}
.cvx-q .why {{font-size: .86rem; color: {MUTED}; margin-top: 3px;}}
.cvx-q .src {{font-size: .7rem; font-weight: 600; color: {MUTED}; background: #F1F5F9; border-radius: 999px;
  padding: 2px 8px; margin-left: 8px;}}
.cvx-note {{background: #EFF5FF; border: 1px solid #D6E4FF; border-radius: 14px; padding: 14px 18px; margin: 10px 0 16px;
  color: #1E3A8A; font-size: .98rem;}}
.cvx-diff {{border: 1px solid {RULE}; border-radius: 12px; overflow: hidden; margin: 4px 0 10px; background: #fff;}}
.cvx-diff .tag {{display: block; font-size: .74rem; font-weight: 700; color: {MUTED}; padding: 8px 14px;
  border-bottom: 1px solid {RULE}; background: #F8FAFC;}}
.cvx-diff .old {{background: #FEF2F2; color: #991B1B; padding: 8px 14px; text-decoration: line-through;
  text-decoration-color: rgba(153,27,27,.45);}}
.cvx-diff .old::before {{content: "− "; text-decoration: none; font-weight: 700;}}
.cvx-diff .new {{background: #ECFDF5; color: #065F46; padding: 8px 14px; font-weight: 500;}}
.cvx-diff .new::before {{content: "+ "; font-weight: 700;}}
.cvx-qn {{font-size: .74rem; font-weight: 700; color: {ACCENT}; margin-bottom: 2px;}}
.cvx-qq {{font-size: 1.04rem; font-weight: 700; line-height: 1.42; color: {INK};}}
.cvx-why {{font-size: .86rem; color: {MUTED}; margin-top: 4px;}}
.cvx-why .src {{font-size: .7rem; font-weight: 600; color: {MUTED}; background: #F1F5F9; border-radius: 999px;
  padding: 2px 8px; margin-left: 8px;}}
div[data-testid="stChatMessage"] {{background: #fff; border: 1px solid {RULE}; border-radius: 16px; padding: 12px 16px 16px;
  margin-bottom: 10px; box-shadow: 0 1px 2px rgba(15,23,42,.03);}}
div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
div[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {{background: #EFF5FF; border-color: #D6E4FF;
  max-width: 85%; margin-left: auto;}}
.cvx-live {{font-size: .8rem; font-weight: 700; color: {ACCENT}; margin-bottom: 6px;}}
.cvx-live span {{display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22C55E; margin-right: 6px;
  box-shadow: 0 0 0 3px rgba(34,197,94,.18);}}
.cvx-score {{display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px;}}
.cvx-score b {{font-size: 2rem; font-weight: 800; letter-spacing: -.03em; color: {INK};}}
.cvx-score span {{font-size: .88rem; font-weight: 600; color: {MUTED};}}
.cvx-card-title {{font-size: 1.05rem; font-weight: 800; color: {INK}; letter-spacing: -.01em;}}
.cvx-picked {{font-size: .7rem; font-weight: 700; color: #fff; background: {ACCENT}; border-radius: 999px;
  padding: 2px 9px; margin-left: 8px; vertical-align: middle;}}
.cvx-meta {{font-size: .82rem; color: {MUTED}; line-height: 1.5;}}
.cvx-chk {{display: grid; grid-template-columns: 76px 1fr; gap: 10px; padding: 7px 0; border-bottom: 1px solid #F1F5F9;
  font-size: .92rem; align-items: start;}}
.cvx-chk .lv {{font-size: .72rem; font-weight: 700; border-radius: 999px; padding: 2px 8px; text-align: center;}}
.cvx-chk .tip {{display: block; color: {MUTED}; font-size: .82rem; margin-top: 2px;}}
.cvx-chk.ok {{color: {MUTED};}}
</style>"""


def _md(html_str):
    st.markdown(html_str, unsafe_allow_html=True)


def _masthead(n_templates):
    _md(CSS)
    _md(f"""<div class="cvx-mast"><div class="cvx-over">CV Stüdyosu</div>
<h1>Daha güçlü bir CV, <span>birlikte.</span></h1>
<p class="cvx-lede">CV'nizi yükleyin, formatını seçin. Koç eksik kalan yerleri size sorar; CV'ye yalnızca sizin
söyledikleriniz girer.</p>
<div class="cvx-facts"><span>{n_templates} format</span><span>Size soru soran koç</span><span>Uydurma bilgi yok</span>
<span>Veriler bilgisayarınızda</span></div></div>""")


def _section(n, title, note=""):
    _md(f"""<div class="cvx-sect"><span class="n">Adım {n} / {len(STEPS)}</span><h3>{_html.escape(title)}</h3>
{f'<p>{note}</p>' if note else ''}</div>""")


def _diff(old, new, label):
    old_html = f"<div class='old'>{_html.escape(old[:500])}</div>" if old else ""
    return (f"<div class='cvx-diff'><span class='tag'>{_html.escape(label)}</span>{old_html}"
            f"<div class='new'>{_html.escape(new)}</div></div>")


def _k(slug, name):
    return f"cv_{name}_{slug}"


def _reset_pending(slug):
    """CV değişti (yeni CV, elle kayıt): eski indekslere dayanan bekleyen öneriler geçersiz."""
    for name in ("questions", "props", "answers", "sugg", "out", "last_round"):
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
    labels = {i: f"{i}. {name}" + ("  ✓" if i < current else "") for i, name in enumerate(STEPS, 1)}
    picked = st.segmented_control("Adımlar", list(labels), default=current, format_func=labels.get,
                                  key=_k(slug, f"seg{current}"), label_visibility="collapsed", disabled=not enabled,
                                  width="stretch")
    if picked and picked != current:
        _go(slug, picked)


def _checks(slug, p, job=""):
    return ca.audit(p, job_text=job, has_photo=cs.photo_data_uri(slug) is not None,
                    template=p.get("template") or "modern", field=context.field())


def _level(c):
    name, color, bg = LEVEL[c["level"]]
    return f"<span class='lv' style='color:{color};background:{bg}'>{name}</span>"


def _score_box(slug, p, job="", compact=False):
    checks = _checks(slug, p, job)
    score, bad = ca.score(checks), ca.failing(checks)
    if compact:  # dar sütun (koç ekranı): tek satır puan + ilk eksikler
        _md(f"<div class='cvx-score'><b>{score}</b><span>/100 CV kalite puanı</span></div>")
        st.progress(score / 100)
        _md("".join(f"<div class='cvx-chk'>{_level(c)}<div>{_html.escape(c['msg'])}</div></div>" for c in bad[:3]))
        return score
    c1, c2 = st.columns([1, 3])
    c1.metric("CV kalite puanı", f"{score}/100", help=f"{len(checks)} maddelik kontrol listesine göre")
    with c2:
        st.progress(score / 100)
        rows = "".join(f"<div class='cvx-chk'>{_level(c)}<div>{_html.escape(c['area'])} — {_html.escape(c['msg'])}</div></div>"
                       for c in bad[:3])
        more = f"<div class='cvx-meta' style='margin-top:6px'>ve {len(bad) - 3} madde daha · 4. Kontrol → Kontrol listesi</div>" \
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
                    rows.append(f"<div class='cvx-chk ok'><span class='lv' style='color:#059669;background:#ECFDF5'>Tamam</span><div>{_html.escape(c['msg'])}</div></div>")
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
background:#fff;margin:auto;border-radius:10px;box-shadow:0 4px 18px rgba(15,23,42,.06)"><iframe srcdoc="{src}" style="width:794px;height:1123px;border:0;transform:scale({scale});
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
                        f"{'<span class=cvx-picked>Seçili</span>' if chosen else ''}</div>")
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


# ---------------------------------------------------------------- 3) koç: sohbet
COACH, USER = ":material/auto_awesome:", ":material/person:"


def _say(text, html=False):
    with st.chat_message("assistant", avatar=COACH):
        st.markdown(text, unsafe_allow_html=html)


def _ask_bubble(q, i, n):
    src = "Kontrol listesi" if q["source"] == "kural" else "Koç"
    why = f"<div class='cvx-why'>{_html.escape(q['why'])}<span class='src'>{src}</span></div>" if q.get("why") else ""
    _say(f"<div class='cvx-qn'>Soru {i} / {n}</div><div class='cvx-qq'>{_html.escape(q['question'])}</div>{why}", html=True)


def _clear_round(slug):
    for name in ("questions", "props", "answers"):
        st.session_state.pop(_k(slug, name), None)


def _live_preview(slug, p, original):
    """Sağdaki canlı CV: cevaplar geldikçe taslak düzenlemeler (model çağırmadan) uygulanmış hali."""
    import copy
    view = copy.deepcopy(p)
    props = st.session_state.get(_k(slug, "props"))
    qs = st.session_state.get(_k(slug, "questions")) or []
    answers = st.session_state.get(_k(slug, "answers")) or {}
    if props is not None:
        picked = [e for k, e in enumerate(props["accepted"])
                  if st.session_state.get(_k(slug, f"pk{st.session_state.get(_k(slug, 'round'), 1)}_{k}"), True)]
        ci.apply_edits(view, picked)
        note = "Onaylarsanız CV'niz böyle olacak"
    elif answers:
        qa = [{**q, "answer": answers[q["key"]]} for q in qs if q["key"] in answers]
        ci.apply_edits(view, ci.propose_edits(view, original, qa, use_ai=False)["accepted"])
        note = f"Taslak — {len(answers)} cevabınız işlendi"
    else:
        note = "Cevap verdikçe burada güncellenir"
    _md(f"<div class='cvx-live'><span></span>Canlı önizleme · {note}</div>")
    t = view.get("template") or "modern"
    st.iframe(cs.render_html(view, t, cs.template_photo(slug, t), view.get("accent") or "#1f4e79"), height=860)


def _step_coach(slug, p, original):
    chat, preview = st.columns([11, 9], gap="large")
    with preview:
        _live_preview(slug, p, original)
    with chat:
        if not _round_result(slug):
            _coach_chat(slug, p, original)


def _coach_chat(slug, p, original):
    _section(3, "Koçla konuşun", "Koç CV'nizi bir İK uzmanı gözüyle okur ve eksik kalan yerleri tek tek sorar. "
                                 "Kendisi bilgi eklemez: CV'de ya da cevaplarınızda olmayan sayı, beceri ve iddialar "
                                 "otomatik reddedilir. Her değişikliği siz onaylarsınız.")
    rnd = st.session_state.get(_k(slug, "round"), 1)
    qs = st.session_state.get(_k(slug, "questions"))
    first = (p.get("name") or "").split(" ")[0] or "Merhaba"

    if qs is None:  # sohbet başlamadı
        before = _score_box(slug, p, compact=True)
        st.session_state[_k(slug, "score_before")] = before
        done = len(p.get("qa_log", []))
        _say(f"Merhaba {first}! CV'nizi okuyup işverenin soracağı ama CV'de bulamayacağı şeyleri size sorabilirim. "
             + (f"Daha önce {done} soruyu cevapladınız, onları tekrar sormayacağım. " if done else "")
             + "Belirli bir ilana göre hazırlanmak isterseniz aşağıya ekleyin; yoksa doğrudan başlayalım.")
        with st.expander("Hedef unvan ve ilan (isteğe bağlı)"):
            target = st.text_input("Hedef unvan", p.get("headline", ""), key=_k(slug, "target"))
            job = st.text_area("Hedef ilan metni — yapıştırırsanız sorular bu ilana göre olur", key=_k(slug, "job"), height=100)
        if st.button(f"{rnd}. tur: CV'mi oku ve sorularını sor", type="primary", icon=":material/play_arrow:"):
            with st.chat_message("assistant", avatar=COACH):
                with st.spinner("CV'nizi okuyorum, işverenin soracaklarını çıkarıyorum (genelde 1-2 dk, en fazla 3 dk)..."):
                    qs, err = ci.build_questions(p, original, target, job)
            st.session_state[_k(slug, "questions")] = qs
            st.session_state[_k(slug, "answers")] = {}
            if err:
                set_flash("cv", "warning", "Koçun yapay zekâ kısmı bu sefer cevap vermedi; şimdilik kontrol listesinden "
                                           f"çıkan sorular soruluyor. Ayrıntı: {err[:160]}")
            st.rerun()
        return

    if not qs:
        _say("Sorulacak yeni bir şey kalmadı; CV'niz güçlü görünüyor. Kontrol adımına geçebilirsiniz.")
        if st.button("Devam: kontrol →", type="primary"):
            _clear_round(slug)
            _go(slug, 4)
        return

    answers = st.session_state.setdefault(_k(slug, "answers"), {})
    n = len(qs)
    _say(f"{first}, CV'nizi okudum ve {n} sorum var. Bilmediğiniz ya da CV'de görünmesini istemediğiniz soruyu "
         "**Geç** ile atlayabilirsiniz. Cevaplarınızı CV diline ben çeviririm, son söz sizin.")
    for i, q in enumerate(qs[:len(answers)], 1):  # geçmiş
        _ask_bubble(q, i, n)
        with st.chat_message("user", avatar=USER):
            a = answers.get(q["key"], "")
            st.markdown(_html.escape(a) if a else "_Geçildi_")

    props = st.session_state.get(_k(slug, "props"))
    if props is not None:
        return _coach_review(slug, p, props, rnd)

    idx = len(answers)
    if idx < n:  # sıradaki soru
        q = qs[idx]
        _ask_bubble(q, idx + 1, n)
        st.progress(idx / n, text=f"{idx} / {n} cevaplandı")

        def answer(value):
            answers[q["key"]] = value
            st.rerun()

        if q["kind"] == "yesno":
            c1, c2, c3, _ = st.columns([1, 1, 1, 5])
            if c1.button("Evet", type="primary", key=_k(slug, f"y{rnd}_{idx}"), width="stretch"):
                answer("Evet")
            if c2.button("Hayır", key=_k(slug, f"n{rnd}_{idx}"), width="stretch"):
                answer("Hayır")
            if c3.button("Geç", key=_k(slug, f"s{rnd}_{idx}"), width="stretch"):
                answer("")
        else:
            c1, c2, _ = st.columns([1, 1, 5])
            if c1.button("Geç", key=_k(slug, f"s{rnd}_{idx}"), width="stretch", icon=":material/skip_next:"):
                answer("")
            if c2.button("Turu bitir", key=_k(slug, f"end{rnd}_{idx}"), width="stretch",
                         help="Kalan soruları atla, şimdiye kadarki cevapları CV'ye işle"):
                for rest in qs[idx:]:
                    answers.setdefault(rest["key"], "")
                st.rerun()
            hint = ("Örn: " + q["example"]) if q.get("example") else "Cevabınızı yazın"
            msg = st.chat_input(hint, key=_k(slug, f"chat{rnd}"))
            if msg is not None:
                answer(msg.strip())
        return

    # bütün sorular cevaplandı → cevapları CV'ye işle
    qa = [{**q, "answer": answers.get(q["key"], "")} for q in qs]
    with st.chat_message("assistant", avatar=COACH):
        with st.spinner("Cevaplarınızı CV diline çeviriyor ve her birini denetliyorum..."):
            props = ci.propose_edits(p, original, qa)
    st.session_state[_k(slug, "props")] = {**props, "qa": qa}
    st.rerun()


def _coach_review(slug, p, props, rnd):
    with st.chat_message("assistant", avatar=COACH):
        if props.get("ai_error"):
            st.warning("Yerel model cevapları düzenleyemedi; cevaplarınız olduğu gibi eklenmek üzere hazırlandı.")
        n_ok = len(props["accepted"])
        st.markdown(f"Cevaplarınızdan **{n_ok} değişiklik** çıkardım ve her birini CV'nize ve cevaplarınıza karşı "
                    "denetledim. Uygulamak istemediklerinizin işaretini kaldırın." if n_ok else
                    "Cevaplarınızdan CV'ye eklenecek bir değişiklik çıkmadı.")
        picks = []
        for k, e in enumerate(props["accepted"]):
            c1, c2 = st.columns([1, 16])
            ok = c1.checkbox("Uygula", value=True, key=_k(slug, f"pk{rnd}_{k}"), label_visibility="collapsed")
            c2.markdown(_diff(e.get("old") or "", e["new"], e["label"]), unsafe_allow_html=True)
            if ok:
                picks.append(e)
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
            _clear_round(slug)
            st.session_state[_k(slug, "round")] = rnd + 1
            st.session_state[_k(slug, "last_round")] = {"n": len(picks), "before": before, "after": after}
            st.rerun()
        if c2.button("Vazgeç (hiçbir şey değişmesin)", width="stretch"):
            _clear_round(slug)
            st.rerun()


def _round_result(slug):
    last = st.session_state.get(_k(slug, "last_round"))
    if not last:
        return
    diff = last["after"] - last["before"]
    _say(f"Tamamdır: **{last['n']} değişiklik** CV'nize işlendi. CV kalite puanınız **{last['before']} → {last['after']}**"
         + (f" (+{diff})." if diff > 0 else ".") + " İsterseniz yeni sorularla bir tur daha yapalım ya da CV'yi "
         "birlikte kontrol edelim.")
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
        st.caption(f"Önizleme · {cs.TEMPLATE_INFO.get(t, {}).get('label', t)} (formatı 2. adımdan değiştirebilirsiniz)")
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
    skills = []
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        group, items = line.split(":", 1) if ":" in line else ("Diğer", line)  # grupsuz satır silinmesin
        skills.append({"group": group.strip() or "Diğer", "items": [x.strip() for x in items.split(",") if x.strip()]})
    p["skills"] = [g for g in skills if g["items"]]
    p["education"] = [x for x in st.text_area("Eğitim (her satır bir okul)", "\n".join(p["education"]), key=_k(slug, "e_ed")).splitlines() if x.strip()]
    p["certificates"] = [x for x in st.text_area("Sertifikalar", "\n".join(p["certificates"]), key=_k(slug, "e_ce")).splitlines() if x.strip()]
    p["languages"] = st.text_input("Diller", p["languages"], key=_k(slug, "e_la"))
    p["extras"] = [x for x in st.text_area("Ek bilgiler (ehliyet, askerlik, projeler...)", "\n".join(p["extras"]), key=_k(slug, "e_ex")).splitlines() if x.strip()]
    st.caption("CV'de olmayan yeni bir madde eklerseniz 'sizin beyanınız' olarak işaretlenir ve denetimde kaynak sayılır.")
    if st.button("Kaydet", type="primary", key=_k(slug, "e_save")):
        cs.save_profile(slug, p)
        for name in ("questions", "props", "answers", "sugg"):  # eski maddelere dayanan bekleyen öneriler geçersiz
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
        _step_coach(slug, p, original)
    elif current == 4:
        _step_review(slug, p, original)
    else:
        _step_download(slug, p)
