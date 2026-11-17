"""Sayfaların ortak yardımcıları: kısa başlık, bildirim (flash), boş değer temizleme, stil."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');
/* Kâğıt + mürekkep: ince çizgiler, keskin köşeler, gölgesiz kartlar */
div[data-testid="stMetric"] {background: transparent; border: 1px solid var(--border-color, #E2D9CA);
  border-radius: 4px; padding: 12px 16px;}
div[data-testid="stMetricLabel"] p {font-size: .72rem; letter-spacing: .12em; text-transform: uppercase; opacity: .7;}
div[data-testid="stMetricValue"] {font-family: 'Fraunces', Georgia, serif;}
.block-container {padding-top: 4.2rem; max-width: 1200px;}
.ko-sub {opacity: 0.75; margin-top: -0.6rem; margin-bottom: 1rem;}
.ko-step {font-weight: 600; margin: 0.6rem 0 0.2rem;}
h1, h2, h3, h4 {letter-spacing: -.01em;}
.ko-over {font-family: 'IBM Plex Mono', monospace; font-size: .72rem; letter-spacing: .16em; text-transform: uppercase;
  color: #6B6257; margin-bottom: -.4rem;}
.ko-sub {color: #3D362E; max-width: 48rem;}
hr {border-color: #E2D9CA !important;}
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
