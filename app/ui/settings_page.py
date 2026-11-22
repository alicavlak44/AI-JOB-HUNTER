"""⚙️ Ayarlar: yapay zeka durumu, hesap koruması limitleri, veritabanı, loglar."""
import os

import pandas as pd
import streamlit as st

from ai_engine import voice
from ai_engine.brain import check_lm_studio, fast_model
from app import context, guard, settings
from app.logger import read_recent_logs
from app.ui.common import header
from database.db_manager import reset_database


def page_settings():
    header("Ayarlar", "Sistem durumu, koruma limitleri ve bakım.")
    ok, msg = check_lm_studio()
    fast_note = f" · hızlı model: {fast_model()}" if settings.LM_FAST_MODEL else ""
    (st.success if ok else st.error)(f"🧠 Yapay zeka (LM Studio): {msg} · model: {settings.LM_MODEL}{fast_note}")
    tts_ok, stt_ok = voice.tts_available(), voice.stt_available()
    voice_msg = (f"Sesli mülakat: TTS ({voice.TTS_VOICE}) {'hazır' if tts_ok else 'yok'} · "
                 f"Whisper ({voice.WHISPER_MODEL}) {'hazır' if stt_ok else 'kurulu değil'}")
    (st.success if (tts_ok and stt_ok) else st.info)(f"🎤 {voice_msg}")
    cv = context.cv_path()
    (st.success if os.path.exists(cv) else st.error)(
        f"📄 Ana CV: {os.path.relpath(cv, settings.BASE_DIR) if os.path.exists(cv) else 'yok — aşağıdan yükleyin'}")

    st.subheader("Profilim")
    u = context.user()
    with st.form("profil"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Ad Soyad", u["name"])
        field = c2.selectbox("Alan", list(context.FIELDS), index=list(context.FIELDS).index(u.get("field", "genel")),
                             format_func=context.FIELDS.get)
        city = c3.text_input("Şehir", u.get("city", ""))
        targets = st.text_area("Aranacak pozisyonlar (her satır bir unvan)", "\n".join(u.get("targets", [])))
        only_large = st.checkbox("🏢 Sadece büyük / kurumsal şirketlere odaklan (küçük ve riskli şirketleri ele)",
                                 value=bool(u.get("only_large_companies")))
        new_pin = st.text_input("Yeni PIN (boş bırakırsanız değişmez; '-' yazarsanız PIN kaldırılır)", type="password")
        new_cv = st.file_uploader("Ana CV'yi değiştir (PDF)", type=["pdf"])
        st.markdown("**📝 Form cevaplarım** — başvuru formlarında sık sorulan, CV'de olmayan sorular. "
                    "Boş bırakılan soru çıkarsa bot durur ve size bırakır; asla tahmin etmez.")
        from ai_engine.form_answers import USER_FIELDS
        fa = dict(u.get("form_answers") or {})
        cols = st.columns(len(USER_FIELDS))
        for col, (k, label) in zip(cols, USER_FIELDS.items()):
            fa[k] = col.text_input(label, fa.get(k, ""), key=f"fa_{k}")
        if st.form_submit_button("Kaydet", type="primary"):
            upd = dict(name=name.strip() or u["name"], field=field, city=city,
                       targets=[t.strip() for t in targets.splitlines() if t.strip()],
                       only_large_companies=only_large,
                       form_answers={k: v.strip() for k, v in fa.items() if v.strip()})
            if new_pin and new_pin != "-" and len(new_pin) < 4:
                st.error("PIN en az 4 hane olmalı.")
                st.stop()
            if new_pin:
                upd["pin"] = None if new_pin == "-" else new_pin
            context.update_user(context.current(), **upd)
            if new_cv:
                with open(os.path.join(context.user_dir(), "cv.pdf"), "wb") as f:
                    f.write(new_cv.getvalue())
            st.session_state.pop(f"positions_{context.current()}", None)
            st.success("Kaydedildi.")

    st.subheader("Soru hafızası")
    st.caption("Başvuru formlarında çıkan soruların SİZİN cevaplarınız. Bot aynı soruyu gördüğünde bunu kullanır "
               "(Evet/Hayır, liste ve metin). Bot cevabını bilmediği soruda durur ve soruyu buraya ekler.")
    uq = context.user()
    pending = [q for q in uq.get("qa_pending", []) if context.norm_q(q) not in (uq.get("qa") or {})]
    rows = [{"Soru": q, "Cevabınız": ""} for q in pending] + \
           [{"Soru": q, "Cevabınız": a} for q, a in (uq.get("qa") or {}).items()]
    if pending:
        st.warning(f"⏸️ {len(pending)} soru cevabınızı bekliyor (tablonun başında, cevap sütunu boş).")
    if not rows:
        st.caption("Henüz kayıtlı soru yok; aşağıdaki tabloya kendiniz de soru ve cevap ekleyebilirsiniz.")
    edited = st.data_editor(pd.DataFrame(rows, columns=["Soru", "Cevabınız"]), hide_index=True, width="stretch",
                            num_rows="dynamic", key=f"qa_{context.current()}",
                            column_config={"Soru": st.column_config.TextColumn(width="large"),
                                           "Cevabınız": st.column_config.TextColumn(help="Evet/Hayır sorusunda: Yes/No veya Evet/Hayır")})
    if st.button("Cevapları kaydet", type="primary"):
        kept = {r["Soru"]: r["Cevabınız"] or "" for r in edited.to_dict("records") if r.get("Soru")}
        removed = [r["Soru"] for r in rows if r["Soru"] not in kept]  # tablodan silinen satırlar
        context.set_answers(kept, removed=removed)
        st.success("Kaydedildi; bot sonraki başvurularda kullanacak.")
        st.rerun()

    st.subheader("Hesap koruması")
    rows = []
    for plat in ("LinkedIn", "Kariyer.net"):
        g = guard.status(plat)
        for act, v in g.items():
            if act != "engel":
                rows.append({"Platform": plat, "İşlem": act, "Bugün": v["bugün"], "Bu hafta": v["hafta"]})
        if g["engel"]:
            st.error(f"{plat}: {g['engel']}")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Sınırlar .env dosyasından değiştirilebilir (MAX_DAILY_APPLICATIONS, MAX_DAILY_INVITES ...). "
               "Platform uyarı verirse o platformda bot işlemleri "
               f"{settings.BLOCK_COOLDOWN_HOURS:.0f} saat durur.")

    with st.expander("🪵 Loglar (son 200 satır)"):
        st.code(read_recent_logs(200) or "Henüz log yok.", language="text")

    with st.expander("🚨 Tehlikeli bölge"):
        sure = st.checkbox("Tüm ilan veritabanını sıfırlamayı onaylıyorum")
        if st.button("Veritabanını sıfırla", disabled=not sure):
            reset_database()
            st.success("Sıfırlandı (yedek .bak olarak saklandı).")
