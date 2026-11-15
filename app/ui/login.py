"""Giriş ekranı ve sağ üst kullanıcı menüsü (çok kullanıcılı yapı).

Her kullanıcının verisi ayrıdır (app/context.py). PIN isteğe bağlıdır; aynı bilgisayarı paylaşan
aile/arkadaşların birbirinin hesabına yanlışlıkla girmesini önler (güçlü bir güvenlik önlemi değildir).
"""
import os

import streamlit as st

from app import context
from app.ui.common import CSS


def _save_cv(slug, upload):
    if upload is None:
        return
    with open(os.path.join(context.user_dir(slug), "cv.pdf"), "wb") as f:
        f.write(upload.getvalue())
    try:  # CV Stüdyosu'na da aktar
        from ai_engine import cv_studio as cs
        text = cs.fix_pdf_artifacts(cs.extract_text(upload.getvalue(), upload.name))
        if slug not in cs.list_profiles():
            p = cs.profile_from_text(text)
            p["name"] = context.user(slug)["name"]
            cs.save_profile(slug, p, text)
    except Exception:
        pass


def login_screen():
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;margin-top:3rem'><h1>⚡ Kariyer Otonomu</h1>"
                "<p style='opacity:.75'>Yapay zekâ destekli iş arama ve CV asistanı</p></div>", unsafe_allow_html=True)
    users = context.load_users()
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        t1, t2 = st.tabs(["🔑 Giriş yap", "➕ Yeni kullanıcı"])
        with t1:
            slug = st.selectbox("Kullanıcı", list(users), format_func=lambda s: users[s]["name"])
            pin = st.text_input("PIN", type="password", disabled=not users[slug].get("pin"),
                                placeholder="PIN yok" if not users[slug].get("pin") else "")
            if st.button("Giriş yap", type="primary", width="stretch"):
                if context.verify_pin(slug, pin):
                    st.session_state["user"] = slug
                    st.rerun()
                st.error("PIN hatalı.")
        with t2:
            with st.form("new_user"):
                name = st.text_input("Ad Soyad *")
                field = st.selectbox("Alan", list(context.FIELDS), format_func=context.FIELDS.get)
                targets = st.text_area("Aranacak pozisyonlar (her satır bir unvan — boş bırakırsanız alana göre önerilir)")
                city = st.text_input("Şehir", "Ankara")
                pin = st.text_input("PIN (isteğe bağlı, 4+ hane)", type="password")
                cv = st.file_uploader("CV (PDF)", type=["pdf"])
                if st.form_submit_button("Kullanıcıyı oluştur", type="primary", width="stretch"):
                    if not name.strip():
                        st.error("Ad soyad gerekli.")
                    elif pin and len(pin) < 4:
                        st.error("PIN en az 4 hane olmalı.")
                    else:
                        slug = context.create_user(name, field, [t.strip() for t in targets.splitlines()] or None, city, pin or None)
                        _save_cv(slug, cv)
                        st.session_state["user"] = slug
                        st.rerun()
        st.caption("Her kullanıcının ilanları, CV'si, LinkedIn/Kariyer.net oturumu ve limitleri ayrı tutulur.")


def user_menu(pages):
    """Sağ üstteki kullanıcı menüsü."""
    u = context.user()
    st.markdown(CSS, unsafe_allow_html=True)  # üst boşluk her sayfada aynı olsun
    _, right = st.columns([5, 1.5])
    with right.popover(f"👤 {u['name']}", width="stretch"):
        st.caption(f"{context.FIELDS.get(u.get('field'), '')} · {u.get('city', '')}")
        st.page_link(pages["settings"], label="Profil ve ayarlar", icon="⚙️")
        others = {s: x["name"] for s, x in context.load_users().items() if s != context.current()}
        if others and st.button("🔁 Kullanıcı değiştir", width="stretch"):
            st.session_state.pop("user", None)
            st.query_params.pop("u", None)
            st.rerun()
        if st.button("🚪 Çıkış", width="stretch"):
            st.session_state.pop("user", None)
            st.query_params.pop("u", None)
            st.session_state["logged_out"] = True
            st.rerun()
