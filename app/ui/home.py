"""🏠 Özet: tek bakışta durum — hesaplar, bugün ne oldu, başarı oranı, en önemli 3 öneri, sıradaki adım."""
import streamlit as st

from app import account, context, guard
from app.settings import MAX_DAILY_APPLICATIONS
from app.ui.common import header, show_flash
from browser.automator import save_login_session, session_status
from database import stats
from database.db_manager import get_all_jobs


def _connections():
    sessions = session_status()
    cols = st.columns(2)
    for col, plat in zip(cols, ("LinkedIn", "Kariyer.net")):
        with col:
            c1, c2 = st.columns([1.4, 1])
            c1.markdown(f"**{plat}** · :{'green' if sessions[plat] else 'red'}[{'bağlı' if sessions[plat] else 'bağlı değil'}]")
            label = "Yeniden bağlan" if sessions[plat] else f"{plat}'e bağlan"
            if c2.button(label, key=f"connect_{plat}", width="stretch", type="secondary" if sessions[plat] else "primary"):
                with st.spinner(f"Açılan Chrome penceresinde {plat} hesabınıza giriş yapın (en fazla 5 dk)."):
                    ok = save_login_session(plat)
                st.session_state["flash_home"] = (
                    ("success", f"✅ {plat} oturumu kaydedildi; bir daha giriş istenmeyecek.") if ok else
                    ("warning", f"⚠️ {plat} girişi algılanmadı. Tekrar deneyin."))
                st.rerun()


def page_home():
    header("Bugün ne yapıyoruz?", "İlan bul → analiz et → isabetli başvur → İK ağını büyüt. Üst menüden ilerleyin; sağ üstte kullanıcı menünüz var.")
    show_flash("home")

    st.subheader("Hesaplar")
    _connections()

    jobs = get_all_jobs()
    st.subheader("Bugün")
    today = stats.summary(jobs)["today"]
    g_li, g_kn = guard.status("LinkedIn"), guard.status("Kariyer.net")
    c = st.columns(4)
    c[0].metric("Bulunan ilan", today["Bulunan ilan"])
    c[1].metric("Analiz edilen", today["Analiz edilen"])
    c[2].metric("Başvuru bugün", f"{g_li['başvuru']['bugün'].split('/')[0]} + {g_kn['başvuru']['bugün'].split('/')[0]}",
                help=f"LinkedIn + Kariyer.net (platform başına günlük sınır {MAX_DAILY_APPLICATIONS})")
    c[3].metric("Davet (son 24 saat)", g_li["bağlantı daveti"]["bugün"].split("/")[0],
                help="LinkedIn bağlantı davetleri (bot + elle). Ağ botunun sınırları için 'Botu yönet'e bakın.")
    for plat, g in (("LinkedIn", g_li), ("Kariyer.net", g_kn)):
        if g["engel"]:
            st.error(f"{plat} bot işlemleri durduruldu: {g['engel']}")
    from app import jobbot, netbot
    from app.ui.jobbot_card import STATE_STYLE as JB_STYLE
    from app.ui.netbot_card import STATE_STYLE
    nb = netbot.status(context.current())
    color, label = STATE_STYLE.get(nb["state"], ("gray", nb["state"]))
    b1, b2 = st.columns([3, 1])
    b1.markdown(f"**LinkedIn ağ botu** :{color}[● {label}] · son 24 saatte {nb['today']}, son 7 günde {nb['week']}/{netbot.WEEKLY} davet")
    if "network" in st.session_state.get("_pages", {}):
        b2.page_link(st.session_state["_pages"]["network"], label="Ağ botunu yönet", icon=":material/tune:")

    jb = jobbot.status(context.current())
    jcolor, jlabel = JB_STYLE.get(jb["state"], ("gray", jb["state"]))
    opps = jobbot.ready_opportunities(jobs)
    j1, j2 = st.columns([3, 1])
    j1.markdown(f"**Otomatik ilan avcısı** :{jcolor}[● {jlabel}] · %{jobbot.PREP_MIN_SCORE}+ hazır fırsat: **{len(opps)}**"
                + (f" · sonraki tarama: {jb['next_run']}" if jb["running"] and jb["next_run"] else ""))
    if "bulk" in st.session_state.get("_pages", {}):
        j2.page_link(st.session_state["_pages"]["bulk"], label="Avcıyı yönet", icon=":material/smart_toy:")

    st.subheader("Başarı oranı")
    metrics = account.success_metrics()
    if metrics:
        for col, (label, (value, frac)) in zip(st.columns(len(metrics)), metrics.items()):
            col.metric(label, "—" if value is None else f"%{value}", help=frac)
    else:
        st.info("Henüz hesap senkronu yapılmadı → **📈 Başarı** sayfasından 'Hesaplarımdan senkronla'.")

    scores = [x for x in jobs["ATS Uyum"].map(stats.parse_score).dropna()] if not jobs.empty else []
    recs = account.recommendations(avg_score=round(sum(scores) / len(scores)) if scores else None)
    if recs:
        st.subheader("Şimdi yapılacaklar")
        for prio, title, body in recs[:3]:
            st.markdown(f":{'red' if prio == 1 else 'orange' if prio == 2 else 'gray'}[**{('Önce bu', 'Sonra', 'İsterseniz')[min(prio, 3) - 1]}**] · **{title}** — {body}")
        if len(recs) > 3:
            st.caption(f"+{len(recs) - 3} öneri daha → 📈 Başarı sayfası")

    st.subheader("Sıradaki adım")
    from app import campaign
    pending, ready = campaign.unanalyzed_jobs(jobs), campaign.eligible_jobs(jobs)
    if jobs.empty:
        st.page_link(st.session_state["_pages"]["jobs"], label="İlan arayın", icon="🔎")
    elif not ready.empty:
        st.success(f"{len(ready)} ilan başvuruya hazır (uyum %65+).")
        st.page_link(st.session_state["_pages"]["bulk"], label="Toplu Başvuru'ya git", icon="🚀")
    elif not pending.empty:
        st.info(f"{len(pending)} ilan analiz bekliyor.")
        st.page_link(st.session_state["_pages"]["bulk"], label="Analiz et", icon="🧠")
    else:
        st.page_link(st.session_state["_pages"]["jobs"], label="Yeni ilan arayın", icon="🔎")
