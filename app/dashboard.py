"""Kariyer Otonomu — giriş noktası.

Üst menü: 💼 İş Ara · 📄 CV Oluştur. Sağ üstte kullanıcı menüsü. Çok kullanıcılı (app/context.py).
Çalıştırma:  venv/bin/streamlit run app/dashboard.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

from app import context  # noqa: E402
from app.ui.bulk import page_bulk  # noqa: E402
from app.ui.cv_page import page_cv  # noqa: E402
from app.ui.interview_page import page_interview  # noqa: E402
from app.ui.home import page_home  # noqa: E402
from app.ui.jobs import page_jobs  # noqa: E402
from app.ui.login import login_screen, user_menu  # noqa: E402
from app.ui.network import page_network  # noqa: E402
from app.ui.settings_page import page_settings  # noqa: E402
from app.ui.success import page_success  # noqa: E402
from database.db_manager import init_db  # noqa: E402

st.set_page_config(page_title="Kariyer Otonomu", page_icon="⚡", layout="wide")

# --- Kullanıcı: tek kullanıcı varsa ve PIN'i yoksa doğrudan girer; aksi halde giriş ekranı
users = context.load_users()
if "user" not in st.session_state and not st.session_state.get("logged_out"):
    remembered = st.query_params.get("u")  # sayfa yenilenince PIN'siz kullanıcı hatırlanır
    if remembered in users and not context.has_pin(remembered):
        st.session_state["user"] = remembered
    elif len(users) == 1 and not context.has_pin(next(iter(users))):
        st.session_state["user"] = next(iter(users))
if st.session_state.get("user") not in users:
    st.session_state.pop("user", None)
    st.query_params.pop("u", None)
    st.navigation([st.Page(login_screen, title="Giriş", icon="🔑")], position="hidden").run()
    st.stop()

slug = st.session_state["user"]
context.set_user(slug)
if context.has_pin(slug):
    st.query_params.pop("u", None)  # PIN'li kullanıcı adres satırında hatırlanmaz
else:
    st.query_params["u"] = slug
init_db()

PAGES = {
    "home": st.Page(page_home, title="Özet", icon=":material/home:", default=True),
    "jobs": st.Page(page_jobs, title="İlanlar", icon=":material/work:", url_path="ilanlar"),
    "bulk": st.Page(page_bulk, title="Toplu Başvuru", icon=":material/send:", url_path="toplu-basvuru"),
    "network": st.Page(page_network, title="İK Ağı", icon=":material/group:", url_path="ik-agi"),
    "success": st.Page(page_success, title="Başarı ve Öneriler", icon=":material/insights:", url_path="basari"),
    "settings": st.Page(page_settings, title="Profil ve Ayarlar", icon=":material/settings:", url_path="ayarlar"),
    "cv": st.Page(page_cv, title="CV Stüdyosu", icon=":material/description:", url_path="cv-studyosu"),
    "interview": st.Page(page_interview, title="Mülakat Provası", icon=":material/record_voice_over:", url_path="mulakat"),
}
st.session_state["_pages"] = PAGES  # sayfalar arası bağlantılar için

nav = st.navigation({
    "İş Ara": [PAGES["home"], PAGES["jobs"], PAGES["bulk"], PAGES["network"], PAGES["success"], PAGES["settings"]],
    "CV ve Mülakat": [PAGES["cv"], PAGES["interview"]],
}, position="top")

user_menu(PAGES)
nav.run()
