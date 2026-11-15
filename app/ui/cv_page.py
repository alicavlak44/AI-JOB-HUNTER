"""📄 CV Stüdyosu: 1) kaynak (yükle / mevcut CV) → 2) düzenle → 3) yapay zeka ile iyileştir → 4) şablon seç, indir.

Çok kişili: her kişinin verisi profiles/<ad>/ altında ayrı tutulur.
"""
import os

import streamlit as st

from ai_engine import cv_studio as cs
from ai_engine.brain import AIError
from app import context
from app.ui.common import header, step, show_flash, set_flash


def _import(slug):
    c1, c2 = st.columns(2)
    up = c1.file_uploader("CV yükle (PDF / DOCX)", type=["pdf", "docx", "txt"], key=f"up_{slug}")
    if up and c1.button("📥 Bu CV'yi içe aktar", type="primary", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(up.getvalue(), up.name))
        p = cs.profile_from_text(text)
        cs.save_profile(slug, p, text)
        set_flash("cv", "success", f"✅ İçe aktarıldı: {len(p['experience'])} deneyim, "
                                    f"{sum(len(g['items']) for g in p['skills'])} beceri." +
                  ("  \n⚠️ " + "  \n⚠️ ".join(p["_warnings"]) if p.get("_warnings") else ""))
        st.rerun()
    main_cv = context.cv_path()
    if os.path.exists(main_cv) and c2.button("📄 Kayıtlı CV'mi kullan", width="stretch"):
        text = cs.fix_pdf_artifacts(cs.extract_text(open(main_cv, "rb").read(), main_cv))
        p = cs.profile_from_text(text)
        p["name"] = p["name"] or context.name()
        cs.save_profile(slug, p, text)
        set_flash("cv", "success", "✅ Sistemdeki CV içe aktarıldı.")
        st.rerun()
    c2.caption("LinkedIn / Kariyer.net'ten içe aktarma: profilinizin PDF'ini indirip (LinkedIn → Profil → "
               "Daha fazla → PDF olarak kaydet) buradan yükleyin.")


def _edit(slug, p):
    with st.expander("👤 Kişisel bilgiler ve özet", expanded=True):
        c = st.columns(3)
        p["name"] = c[0].text_input("Ad Soyad", p["name"])
        p["headline"] = c[1].text_input("Başlık (hedef unvan)", p["headline"])
        p["city"] = c[2].text_input("Şehir", p["city"])
        c = st.columns(3)
        p["email"] = c[0].text_input("E-posta", p["email"])
        p["phone"] = c[1].text_input("Telefon", p["phone"])
        p["links"] = [x.strip() for x in c[2].text_input("Bağlantılar (virgülle)", ", ".join(p["links"])).split(",") if x.strip()]
        p["summary"] = st.text_area("Özet", p["summary"], height=120)
        photo = st.file_uploader("Fotoğraf (isteğe bağlı)", type=["jpg", "jpeg", "png"], key=f"ph_{slug}")
        if photo:
            cs.save_photo(slug, photo.getvalue(), photo.name)
    with st.expander(f"💼 Deneyim ({len(p['experience'])})"):
        for i, e in enumerate(p["experience"]):
            st.markdown(f"**{e['title']}** — {e['company']} · {e['dates']}")
            text = st.text_area("Maddeler (her satır bir madde)", "\n".join(b["text"] for b in e["bullets"]),
                                key=f"b_{slug}_{i}", height=150)
            old = {b["text"]: b.get("user", False) for b in e["bullets"]}
            e["bullets"] = [{"text": t.strip(), "user": old.get(t.strip(), True)} for t in text.splitlines() if t.strip()]
        st.caption("CV'de olmayan yeni bir madde eklerseniz 'sizin beyanınız' olarak işaretlenir ve yapay zeka denetiminde kaynak sayılır.")
    with st.expander(f"🧰 Beceriler ({sum(len(g['items']) for g in p['skills'])})"):
        text = st.text_area("Her satır: Grup: beceri1, beceri2", "\n".join(f"{g['group']}: {', '.join(g['items'])}" for g in p["skills"]),
                            height=180, key=f"sk_{slug}")
        p["skills"] = [{"group": l.split(":", 1)[0].strip(), "items": [x.strip() for x in l.split(":", 1)[1].split(",") if x.strip()]}
                       for l in text.splitlines() if ":" in l]
    with st.expander("🎓 Eğitim, sertifika, dil, ek bilgiler"):
        p["education"] = [x for x in st.text_area("Eğitim (her satır bir okul)", "\n".join(p["education"]), key=f"ed_{slug}").splitlines() if x.strip()]
        p["certificates"] = [x for x in st.text_area("Sertifikalar", "\n".join(p["certificates"]), key=f"ce_{slug}").splitlines() if x.strip()]
        p["languages"] = st.text_input("Diller", p["languages"], key=f"la_{slug}")
        p["extras"] = [x for x in st.text_area("Ek bilgiler (ehliyet, askerlik, projeler...)", "\n".join(p["extras"]), key=f"ex_{slug}").splitlines() if x.strip()]
    if st.button("💾 Kaydet", type="primary"):
        cs.save_profile(slug, p)
        set_flash("cv", "success", "✅ Kaydedildi.")
        st.rerun()


def _improve(slug, p, original):
    target = st.text_input("Hedef unvan (isteğe bağlı)", p.get("headline", ""), key=f"tg_{slug}")
    if st.button("✨ Yapay zeka ile iyileştir (1-2 dk)"):
        with st.spinner("Öneriler üretiliyor ve her biri CV'nizle karşılaştırılıyor..."):
            try:
                st.session_state[f"sugg_{slug}"] = cs.improve(p, original, target)
            except AIError as e:
                set_flash("cv", "error", f"❌ {e}")
        st.rerun()
    sugg = st.session_state.get(f"sugg_{slug}")
    if not sugg:
        st.caption("Yapay zeka başlık, özet ve zayıf maddeleri daha etkili yazar. CV'de olmayan beceri, sayı veya "
                   "iddia içeren her öneri kod tarafından otomatik reddedilir.")
        return
    if not sugg["accepted"]:
        st.info("Kabul edilebilir öneri çıkmadı.")
    picks = []
    for k, sgg in enumerate(sugg["accepted"]):
        with st.container(border=True):
            ok = st.checkbox(f"Uygula · {sgg['where']}", value=True, key=f"pick_{slug}_{k}")
            st.markdown(f"~~{sgg['old'][:300]}~~")
            st.markdown(f"**→ {sgg['new']}**")
            if ok:
                picks.append(sgg)
    if sugg["rejected"]:
        with st.expander(f"🚫 {len(sugg['rejected'])} öneri uydurma içerdiği için reddedildi"):
            for r in sugg["rejected"]:
                st.markdown(f"- _{r['new'][:200]}_ → {'; '.join(r['why'])}")
    if picks and st.button(f"✅ Seçilen {len(picks)} öneriyi uygula ve kaydet", type="primary"):
        for sgg in picks:
            cs.apply_suggestion(p, sgg)
        cs.save_profile(slug, p)
        st.session_state.pop(f"sugg_{slug}", None)
        set_flash("cv", "success", f"✅ {len(picks)} iyileştirme uygulandı.")
        st.rerun()


def _render(slug, p):
    c1, c2 = st.columns([2, 1])
    tpl = c1.radio("Şablon", list(cs.TEMPLATES), format_func=cs.TEMPLATES.get, key=f"tpl_{slug}")
    accent = c2.color_picker("Vurgu rengi", "#1f4e79", key=f"ac_{slug}")
    photo = None if tpl == "ats" else cs.photo_data_uri(slug, portrait=tpl == "klasik")
    st.components.v1.html(cs.render_html(p, tpl, photo, accent), height=900, scrolling=True)
    if st.button("⬇️ PDF üret", type="primary"):
        with st.spinner("PDF hazırlanıyor..."):
            st.session_state[f"out_{slug}"] = cs.export(slug, p, tpl, accent)
        st.rerun()
    out = st.session_state.get(f"out_{slug}")
    if out:
        d1, d2, d3 = st.columns(3)
        d1.download_button("📄 PDF indir", open(out["pdf"], "rb").read(), file_name=os.path.basename(out["pdf"]), mime="application/pdf")
        if out.get("docx"):
            d2.download_button("📝 Word indir (ATS)", open(out["docx"], "rb").read(), file_name=os.path.basename(out["docx"]))
        if d3.button("⭐ Bu CV'yi başvurularda kullan", help="İlan analizi ve başvurularda bu PDF kullanılır"):
            import shutil
            shutil.copyfile(out["pdf"], os.path.join(context.user_dir(), "cv.pdf"))
            set_flash("cv", "success", "✅ Artık analiz ve başvurularda bu CV kullanılıyor.")
            st.rerun()


def page_cv():
    header("📄 CV Stüdyosu", "CV'nizi yükleyin, düzenleyin, yapay zekayla güçlendirin, 4 şablondan birini seçip indirin.")
    show_flash("cv")
    slug = context.current()  # herkes sadece kendi CV'sini görür
    exists = slug in cs.list_profiles()

    step("1️⃣ Kaynak")
    with st.container(border=True):
        _import(slug)
    if not exists:
        return
    p, original = cs.load_profile(slug)

    score, missing = cs.completeness(p, has_photo=cs.photo_data_uri(slug) is not None)
    c1, c2 = st.columns([1, 3])
    c1.metric("CV doluluk puanı", f"{score}/100")
    with c2:
        st.progress(score / 100)
        for m in missing[:4]:
            st.caption("• " + m)
    warns = cs.typo_warnings(original)
    if warns:
        st.warning("Olası yazım hatası (otomatik düzeltilmez, isterseniz Düzenle'den değiştirin): " + "; ".join(warns))

    t1, t2, t3 = st.tabs(["2️⃣ Düzenle", "3️⃣ Yapay zeka ile iyileştir", "4️⃣ Şablon ve indir"])
    with t1:
        _edit(slug, p)
    with t2:
        _improve(slug, p, original)
    with t3:
        _render(slug, p)
