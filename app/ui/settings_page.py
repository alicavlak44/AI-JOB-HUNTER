"""⚙️ Ayarlar: yapay zeka durumu, hesap koruması limitleri, veritabanı, loglar."""
import os

import pandas as pd
import streamlit as st

from ai_engine.brain import check_lm_studio
from app import guard, settings
from app.logger import read_recent_logs
from app.ui.common import header
from database.db_manager import reset_database


def page_settings():
    header("⚙️ Ayarlar", "Sistem durumu, koruma limitleri ve bakım.")
    ok, msg = check_lm_studio()
    (st.success if ok else st.error)(f"🧠 Yapay zeka (LM Studio): {msg} · model: {settings.LM_MODEL}")
    (st.success if os.path.exists(settings.CV_PATH) else st.error)(
        f"📄 CV: {os.path.basename(settings.CV_PATH) if os.path.exists(settings.CV_PATH) else 'bulunamadı (documents/Cv.pdf)'}")

    st.subheader("🛡️ Hesap koruması")
    rows = []
    for plat in ("LinkedIn", "Kariyer.net"):
        g = guard.status(plat)
        for name, v in g.items():
            if name != "engel":
                rows.append({"Platform": plat, "İşlem": name, "Bugün": v["bugün"], "Bu hafta": v["hafta"]})
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
