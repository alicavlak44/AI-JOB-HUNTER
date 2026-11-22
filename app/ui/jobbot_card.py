"""Paneldeki 'Otomatik ilan avcısı' kartı: durum, başlat/durdur, hazır fırsatlar (%75+) ve kayıtlar."""
import pandas as pd
import streamlit as st

from app import context, jobbot
from database.db_manager import get_all_jobs

STATE_STYLE = {
    "çalışıyor": ("green", "Çalışıyor"),
    "beklemede": ("blue", "Sonraki turu bekliyor"),
    "mesai dışı": ("blue", "Mesai dışı (08:00–23:00 çalışır)"),
    "lm kapalı": ("orange", "Tarama açık · LM Studio kapalı"),
    "durduruldu": ("gray", "Durduruldu"),
    "başlatılıyor": ("green", "Başlatılıyor"),
}


@st.fragment(run_every="30s")
def jobbot_card():
    slug = context.current()
    s = jobbot.status(slug)
    color, label = STATE_STYLE.get(s["state"], ("gray", s["state"]))
    opts = s["options"]
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        c1.markdown(f"#### Otomatik ilan avcısı  :{color}[● {label}]")
        c1.caption(
            f"Her {jobbot.INTERVAL_MIN} dakikada hedef pozisyonlarınızı tarar, yeni ilanları analiz eder, "
            f"%{jobbot.PREP_MIN_SCORE}+ uyumlu fırsatlar için ön yazı ve ilana özel CV'yi önceden hazırlar. "
            "Onayınız olmadan başvuru göndermez; panel kapansa da çalışır."
        )
        b1, b2 = c2.columns(2)
        o1, o2, o3 = st.columns(3)
        inc_kn = o1.checkbox("Kariyer.net'i de tara", value=bool(opts.get("kariyernet", True)),
                             disabled=s["running"], key="jb_kn")
        auto_cv = o2.checkbox(f"%{jobbot.PREP_MIN_SCORE}+ için özel CV hazırla", value=bool(opts.get("auto_cv", True)),
                              disabled=s["running"], key="jb_cv")
        auto_sync = o3.checkbox("Günde 1 kez LinkedIn senkronla", value=bool(opts.get("auto_sync", True)),
                                disabled=s["running"], key="jb_sync")
        if b1.button("Başlat", type="primary", width="stretch", disabled=s["running"], key="jb_start",
                     icon=":material/play_arrow:"):
            ok, msg = jobbot.start(slug, include_kariyernet=inc_kn, auto_cv=auto_cv, auto_sync=auto_sync)
            st.toast(msg)
            st.rerun()
        if b2.button("Durdur", width="stretch", disabled=not s["running"], key="jb_stop", icon=":material/stop:"):
            ok, msg = jobbot.stop(slug)
            st.toast(msg)
            st.rerun()

        u = context.user()
        opps = jobbot.ready_opportunities(
            get_all_jobs(),
            only_large=bool(u.get("only_large_companies")),
            allowed_roles=u.get("allowed_role_classes") or None,
            fresh_grad_only=bool(u.get("fresh_grad_only")),
        )
        m = st.columns(4)
        m[0].metric("Bulunan ilan", s["found_total"])
        m[1].metric("Analiz edilen", s["analyzed_total"])
        m[2].metric(f"Hazır fırsat (%{jobbot.PREP_MIN_SCORE}+)", len(opps))
        m[3].metric("Sonraki tarama", s["next_run"] if s["running"] and s["next_run"] else "—")
        if s["detail"]:
            st.caption(f"Son işlem ({s['updated'][11:16]}): {s['detail']}")

        with st.expander(f"Başvuruya hazır fırsatlar ({len(opps)})", expanded=bool(opps)):
            if opps:
                df = pd.DataFrame(opps).drop(columns=["id"])
                st.dataframe(df, hide_index=True, width="stretch",
                             column_config={
                                 "Puan": st.column_config.ProgressColumn("Puan", min_value=0, max_value=100, format="%d"),
                                 "İlan": st.column_config.LinkColumn("İlan", display_text="Aç"),
                             })
            else:
                st.caption(f"Henüz %{jobbot.PREP_MIN_SCORE}+ uyumlu bekleyen fırsat yok.")
        with st.expander("Avcı kayıtları"):
            lines = jobbot.recent_log(slug, 15)
            st.code("\n".join(lines) if lines else "Kayıt yok.", language=None)
