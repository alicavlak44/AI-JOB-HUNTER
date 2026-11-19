"""Paneldeki 'LinkedIn ağ botu' kartı: durum, sayılar, başlat/durdur, son davetler ve kayıtlar (30 sn'de bir yenilenir)."""
import pandas as pd
import streamlit as st

from app import context, netbot

STATE_STYLE = {"çalışıyor": ("green", "Çalışıyor"), "beklemede": ("orange", "Sırasını bekliyor"),
               "mesai dışı": ("blue", "Mesai dışı (08:00–23:00 çalışır)"), "durduruldu": ("gray", "Durduruldu"),
               "giriş gerekli": ("red", "LinkedIn girişi gerekli"), "bitti": ("gray", "Bitti"),
               "başlatılıyor": ("green", "Başlatılıyor")}


@st.fragment(run_every="30s")
def netbot_card():
    slug = context.current()
    s = netbot.status(slug)
    color, label = STATE_STYLE.get(s["state"], ("gray", s["state"]))
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        c1.markdown(f"#### LinkedIn ağ botu  :{color}[● {label}]")
        c1.caption(f"Ankara'daki şirketlerin İK ve BT yöneticilerine, işe alımcılara ve BT çalışanlarına notsuz bağlantı "
                   f"daveti. {netbot.WORK_HOURS[0]:02d}:00–{netbot.WORK_HOURS[1]:02d}:00 arası, günde en fazla "
                   f"{netbot.DAILY}, haftada en fazla {netbot.WEEKLY} davet. Panel kapansa da çalışmaya devam eder.")
        b1, b2 = c2.columns(2)
        if b1.button("Başlat", type="primary", width="stretch", disabled=s["running"], key="nb_start",
                     icon=":material/play_arrow:"):
            ok, msg = netbot.start(slug)
            st.toast(msg)
            st.rerun()
        if b2.button("Durdur", width="stretch", disabled=not s["running"], key="nb_stop", icon=":material/stop:"):
            ok, msg = netbot.stop(slug)
            st.toast(msg)
            st.rerun()

        m = st.columns(3)
        m[0].metric("Son 24 saat", f"{s['today']} / {netbot.DAILY}")
        m[1].metric("Son 7 gün", f"{s['week']} / {netbot.WEEKLY}",
                    help="LinkedIn ücretsiz hesaplarda haftalık sınır ~100 davet; 7 günlük pencere kaydıkça hak açılır")
        m[2].metric("Toplam davet", s["total"])
        st.progress(min(1.0, s["week"] / netbot.WEEKLY), text=f"Haftalık hak: {max(0, netbot.WEEKLY - s['week'])} kaldı")
        if s["state"] == "giriş gerekli":
            st.error("Bot durdu çünkü LinkedIn oturumu kapalı. Özet sayfasından 'LinkedIn → Yeniden bağlan' ile giriş "
                     "yapın, sonra botu yeniden başlatın.")
        if s["detail"]:
            st.caption(f"Son işlem ({s['updated'][11:16]}): {s['detail']}")

        with st.expander("Son davetler"):
            rows = netbot.recent_invites(20)
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                             column_config={"Profil": st.column_config.LinkColumn("Profil", display_text="Aç")})
            else:
                st.caption("Henüz davet yok.")
        with st.expander("Bot kayıtları"):
            lines = netbot.recent_log(slug, 15)
            st.code("\n".join(lines) if lines else "Kayıt yok.", language=None)
