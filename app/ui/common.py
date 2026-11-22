"""Sayfaların ortak yardımcıları: kısa başlık, altbilgi (telif), bildirim (flash), boş değer temizleme, stil.

Copyright (c) 2026 Ali Cavlak. Tüm telif hakları Ali Cavlak'a aittir.
"""
import streamlit as st

COPYRIGHT_TEXT = "© 2026 Ali Cavlak tarafından yapılmıştır. Tüm telif hakları Ali Cavlak'a aittir."

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
/* Modern ve ferah: beyaz zemin, ince çizgili yuvarlak kartlar, hafif gölge */
div[data-testid="stMetric"] {background: #fff; border: 1px solid #E5E8EF; border-radius: 14px; padding: 14px 18px;
  box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 16px rgba(15,23,42,.04);}
div[data-testid="stMetricLabel"] p {font-size: .8rem; font-weight: 600; color: #64748B;}
div[data-testid="stMetricValue"] {font-weight: 800; letter-spacing: -.02em;}
.block-container {padding-top: 4.2rem; max-width: 1200px;}
.ko-sub {color: #475569; max-width: 48rem; margin-top: -0.6rem; margin-bottom: 1rem;}
.ko-step {font-weight: 600; margin: 0.6rem 0 0.2rem;}
h1 {letter-spacing: -.03em !important;} h2, h3, h4 {letter-spacing: -.02em;}
.ko-over {font-size: .78rem; font-weight: 700; color: #0A66FF; margin-bottom: -.5rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}
.ko-footer {margin-top: 3rem; padding: 1.1rem 0 0.5rem; border-top: 1px solid #E5E8EF;
  text-align: center; font-size: .82rem; color: #64748B;}
</style>
"""


def txt(value):
    """Veritabanındaki boş hücre pandas'ta NaN gelir; metin değilse '' döndür."""
    return value.strip() if isinstance(value, str) else ""


def header(title, subtitle="", over="Kariyer Otonomu"):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f"<div class='ko-over'>{over}</div>", unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f"<div class='ko-sub'>{subtitle}</div>", unsafe_allow_html=True)


def footer():
    """Her sayfanın en altında görünen telif hakkı altbilgisi."""
    st.markdown(f"<div class='ko-footer'>{COPYRIGHT_TEXT}</div>", unsafe_allow_html=True)


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
