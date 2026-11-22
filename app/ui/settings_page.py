"""⚙️ Ayarlar: yapay zeka durumu, hesap koruması limitleri, veritabanı, loglar."""
import os

import pandas as pd
import streamlit as st

from ai_engine import voice
from ai_engine.brain import check_ai, ping_ai
from app import context, guard, settings
from app.logger import read_recent_logs
from app.ui.common import header
from database.db_manager import reset_database


def _ai_motor_section():
    cfg = settings.ai_config()
    st.subheader("Yapay zekâ motoru (Bulut API / Yerel)")
    st.caption(
        "Yerel LM Studio yerine Google Gemini API, OpenAI, Groq veya OpenRouter bağlayabilirsiniz. "
        "Değişiklik `.env` dosyasına kaydedilir (git'e girmez) ve arka plandaki İlan Avcısı yeniden başlatmadan algılar."
    )
    providers = list(settings.AI_PROVIDERS)
    cur_idx = providers.index(cfg["provider"]) if cfg["provider"] in providers else 0
    picked = st.selectbox(
        "Sağlayıcı",
        providers,
        index=cur_idx,
        format_func=lambda k: settings.AI_PROVIDERS[k]["label"],
        key="ai_provider_sel",
    )
    preset = settings.AI_PROVIDERS[picked]
    same = picked == cfg["provider"]
    if picked == "gemini":
        st.info(
            "Google AI Studio'dan (**aistudio.google.com/apikey**) ücretsiz Gemini API anahtarı oluşturup aşağıya yapıştırın. "
            "Not: Gemini web aboneliği ile AI Studio API anahtarı ayrıdır; ücretsiz katman günlük kullanım için fazlasıyla yeterlidir."
        )
    elif picked != "local":
        st.caption("Not: Bulut API seçildiğinde CV ve ilan metinleri seçtiğiniz API sağlayıcısına gönderilir.")

    c1, c2 = st.columns(2)
    url = c1.text_input("API adresi (Base URL)", value=cfg["url"] if same else preset["url"],
                        autocomplete="off", key=f"ai_url_{picked}")
    model = c2.text_input("Ana model", value=cfg["model"] if same else preset["model"],
                          autocomplete="off", key=f"ai_mod_{picked}")
    c3, c4 = st.columns(2)
    fast = c3.text_input("Hızlı model (CV Koçu / Mülakat — boşsa ana model)",
                         value=(cfg["fast_model"] if cfg["fast_model"] != cfg["model"] else "") if same else preset["fast_model"],
                         autocomplete="off", key=f"ai_fast_{picked}")
    key_help = "Kayıtlı anahtar mevcut; değiştirmeyecekseniz boş bırakın." if cfg["api_key"] else "Sağlayıcıdan aldığınız API anahtarı"
    api_key = c4.text_input("API Anahtarı" + (" (gerekli)" if preset["needs_key"] else " (yerelde boş)"),
                            value="", type="password", placeholder="••••••••" if cfg["api_key"] else "",
                            autocomplete="new-password", help=key_help, key=f"ai_key_{picked}")

    b1, b2 = st.columns(2)
    if b1.button("💾 Yapay zekâ ayarını kaydet", type="primary", width="stretch", key="ai_save_btn"):
        key_to_save = api_key.strip() if api_key.strip() else ("" if picked == "local" else None)
        settings.save_ai_env(picked, url=url, model=model, fast_model=fast, api_key=key_to_save)
        st.success(f"Kaydedildi: {preset['label']} · {model or preset['model']}")
        st.rerun()
    if b2.button("🔌 Bağlantıyı ve JSON yanıtını test et", width="stretch", key="ai_ping_btn"):
        with st.spinner("Test isteği gönderiliyor..."):
            ok_p, msg_p = ping_ai()
        (st.success if ok_p else st.error)(msg_p)


def page_settings():
    header("Ayarlar", "Sistem durumu, yapay zekâ motoru, koruma limitleri ve bakım.")
    cfg = settings.ai_config()
    ok, msg = check_ai()
    fast_note = f" · hızlı: {cfg['fast_model']}" if cfg["fast_model"] != cfg["model"] else ""
    (st.success if ok else st.error)(f"🧠 Yapay zekâ: {msg}{fast_note}")
    tts_ok, stt_ok = voice.tts_available(), voice.stt_available()
    voice_msg = (f"Sesli mülakat: TTS ({voice.TTS_VOICE}) {'hazır' if tts_ok else 'yok'} · "
                 f"Whisper ({voice.WHISPER_MODEL}) {'hazır' if stt_ok else 'kurulu değil'}")
    (st.success if (tts_ok and stt_ok) else st.info)(f"🎤 {voice_msg}")
    cv = context.cv_path()
    (st.success if os.path.exists(cv) else st.error)(
        f"📄 Ana CV: {os.path.relpath(cv, settings.BASE_DIR) if os.path.exists(cv) else 'yok — aşağıdan yükleyin'}")

    with st.container(border=True):
        _ai_motor_section()

    st.subheader("Profilim")
    u = context.user()
    with st.form("profil"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Ad Soyad", u["name"])
        field = c2.selectbox("Alan", list(context.FIELDS), index=list(context.FIELDS).index(u.get("field", "genel")),
                             format_func=context.FIELDS.get)
        city = c3.text_input("Şehir", u.get("city", ""))
        targets = st.text_area("Aranacak pozisyonlar (her satır bir unvan)", "\n".join(u.get("targets", [])))
        from ai_engine.brain import read_cv_text
        from ai_engine.role_class import ALL_ROLE_CLASSES, ROLE_BADGE, detect_candidate_role_profile
        rp = detect_candidate_role_profile(read_cv_text())
        st.caption(f"CV'nizden algılanan kadro profili: **{rp['summary']}**")
        cur_roles = u.get("allowed_role_classes") or rp["suggested_classes"]
        allowed_roles = st.multiselect(
            "Hedef kadro sınıfları (Mühendis değilseniz 'Mühendis'i seçili bırakmayın)",
            ALL_ROLE_CLASSES,
            default=[r for r in cur_roles if r in ALL_ROLE_CLASSES],
            format_func=lambda r: f"{ROLE_BADGE[r]} ({r})",
        )
        f_col1, f_col2 = st.columns(2)
        only_large = f_col1.checkbox("🏢 Sadece büyük / kurumsal şirketlere odaklan (küçük/riskli şirketleri ele)",
                                     value=bool(u.get("only_large_companies")))
        fresh_only = f_col2.checkbox("🎓 Yeni mezun / junior / yetiştirilmek üzere ilanlar",
                                     value=bool(u.get("fresh_grad_only")))
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
                       allowed_role_classes=allowed_roles,
                       only_large_companies=only_large,
                       fresh_grad_only=fresh_only,
                       form_answers={k: v.strip() for k, v in fa.items() if v.strip()})
            if new_pin and new_pin != "-" and len(new_pin) < 4:
                st.error("PIN en az 4 hane olmalı.")
            else:
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
            ec1, ec2 = st.columns([3.2, 1])
            ec1.error(f"{plat}: {g['engel']}")
            if ec2.button(f"Beklemeyi kaldır ({plat})", key=f"clr_blk_{plat}", width="stretch",
                          help="Yalnızca platform hesabınızda kısıtlama olmadığını kontrol ettiyseniz kullanın"):
                guard.clear_block(plat)
                st.success(f"{plat} yerel bekleme kaydı temizlendi.")
                st.rerun()
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"Geçici hız sınırında (HTTP 429) bekleme {settings.RATE_LIMIT_COOLDOWN_HOURS:.0f} saat, "
               f"ciddi platform uyarısında (doğrulama/999) {settings.BLOCK_COOLDOWN_HOURS:.0f} saattir "
               "(.env: RATE_LIMIT_COOLDOWN_HOURS, BLOCK_COOLDOWN_HOURS).")

    with st.expander("🪵 Loglar (son 200 satır)"):
        st.code(read_recent_logs(200) or "Henüz log yok.", language="text")

    with st.expander("🚨 Tehlikeli bölge"):
        sure = st.checkbox("Tüm ilan veritabanını sıfırlamayı onaylıyorum")
        if st.button("Veritabanını sıfırla", disabled=not sure):
            reset_database()
            st.success("Sıfırlandı (yedek .bak olarak saklandı).")
