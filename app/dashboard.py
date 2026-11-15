"""Kariyer Otonomu — giriş noktası. Sol menüden sayfalar arasında geçilir (app/ui/*).

Çalıştırma:  venv/bin/streamlit run app/dashboard.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

from ai_engine.brain import check_lm_studio  # noqa: E402
from app import guard  # noqa: E402
from app.ui.bulk import page_bulk  # noqa: E402
from app.ui.cv_page import page_cv  # noqa: E402
from app.ui.home import page_home  # noqa: E402
from app.ui.jobs import page_jobs  # noqa: E402
from app.ui.network import page_network  # noqa: E402
from app.ui.settings_page import page_settings  # noqa: E402
from app.ui.success import page_success  # noqa: E402
from browser.automator import session_status  # noqa: E402
from database.db_manager import init_db  # noqa: E402

st.set_page_config(page_title="Kariyer Otonomu", page_icon="⚡", layout="wide")
init_db()

PAGES = {
    "home": st.Page(page_home, title="Özet", icon="🏠", default=True, url_path="ozet"),
    "jobs": st.Page(page_jobs, title="İlanlar", icon="🔎", url_path="ilanlar"),
    "bulk": st.Page(page_bulk, title="Toplu Başvuru", icon="🚀", url_path="toplu-basvuru"),
    "network": st.Page(page_network, title="İK Ağı", icon="🤝", url_path="ik-agi"),
    "success": st.Page(page_success, title="Başarı", icon="📈", url_path="basari"),
    "cv": st.Page(page_cv, title="CV Stüdyosu", icon="📄", url_path="cv-studyosu"),
    "settings": st.Page(page_settings, title="Ayarlar", icon="⚙️", url_path="ayarlar"),
}
st.session_state["_pages"] = PAGES  # sayfalar arası bağlantılar için

nav = st.navigation({
    "İş arama": [PAGES["home"], PAGES["jobs"], PAGES["bulk"]],
    "Ağ ve gelişim": [PAGES["network"], PAGES["success"], PAGES["cv"]],
    "Sistem": [PAGES["settings"]],
})

with st.sidebar:
    # Kısa durum çubuğu (ayrıntılar ⚙️ Ayarlar'da)
    lm_ok, _ = check_lm_studio()
    sess = session_status()
    blocked = [p for p in ("LinkedIn", "Kariyer.net") if guard.is_blocked(p)]
    st.caption(" · ".join([
        f"{'🟢' if lm_ok else '🔴'} Yapay zeka",
        f"{'🟢' if sess['LinkedIn'] else '🔴'} LinkedIn",
        f"{'🟢' if sess['Kariyer.net'] else '🔴'} Kariyer.net",
    ]))
    if blocked:
        st.error("🛡️ Durduruldu: " + ", ".join(blocked))

nav.run()
