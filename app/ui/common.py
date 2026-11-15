"""Sayfaların ortak yardımcıları: kısa başlık, bildirim (flash), boş değer temizleme, stil."""
import streamlit as st

CSS = """
<style>
/* Daha sade görünüm: kart benzeri metrikler, sıkı boşluklar */
div[data-testid="stMetric"] {background: var(--secondary-background-color); border-radius: 12px; padding: 12px 16px;}
div[data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.8;}
.block-container {padding-top: 4.2rem; max-width: 1200px;}
.ko-sub {opacity: 0.75; margin-top: -0.6rem; margin-bottom: 1rem;}
.ko-step {font-weight: 600; margin: 0.6rem 0 0.2rem;}
</style>
"""


def txt(value):
    """Veritabanındaki boş hücre pandas'ta NaN gelir; metin değilse '' döndür."""
    return value.strip() if isinstance(value, str) else ""


def header(title, subtitle=""):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f"<div class='ko-sub'>{subtitle}</div>", unsafe_allow_html=True)


def step(text):
    """Sayfa içindeki adım başlığı (1, 2, 3...)."""
    st.markdown(f"<div class='ko-step'>{text}</div>", unsafe_allow_html=True)


def set_flash(key, kind, msg):
    st.session_state[f"flash_{key}"] = (kind, msg)


def show_flash(key):
    f = st.session_state.pop(f"flash_{key}", None)
    if f and f[1]:
        getattr(st, f[0])(f[1])


def msg_kind(msg):
    """Mesajın başındaki işarete göre Streamlit kutusu türü."""
    m = msg or ""
    if m.startswith(("❌", "🛡️", "LinkedIn girişi", "Kariyer.net girişi", "Tarayıcı")):
        return "error"
    if m.startswith("⚠️"):
        return "warning"
    if m.startswith(("🎯", "✅")):
        return "success"
    return "info"
