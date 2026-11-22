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


@st.fragment(run_every="15s")
def _live_center():
    """Arka plan botlarının canlı durumu ve son hareketleri (sayfa yenilemeden 15 sn'de bir güncellenir)."""
    import pandas as pd
    from app import jobbot, netbot
    from app.ui.jobbot_card import STATE_STYLE as JB_STYLE
    from app.ui.netbot_card import STATE_STYLE as NB_STYLE

    slug = context.current()
    nb = netbot.status(slug)
    jb = jobbot.status(slug)
    opps = jobbot.ready_opportunities(get_all_jobs(), only_large=bool(context.user().get("only_large_companies")))
    n_col, n_lbl = NB_STYLE.get(nb["state"], ("gray", nb["state"]))
    j_col, j_lbl = JB_STYLE.get(jb["state"], ("gray", jb["state"]))

    with st.container(border=True):
        st.markdown("#### Arka Plan Otomasyonu — Canlı Durum  `15 sn'de bir güncellenir · penceresiz çalışır`")
        left, right = st.columns(2)
        with left:
            st.markdown(f"**LinkedIn Ağ Botu**  :{n_col}[● {n_lbl}]")
            st.caption(f"Son 24 saat: **{nb['today']}/{netbot.DAILY}** · Son 7 gün: **{nb['week']}/{netbot.WEEKLY}** · Toplam: **{nb['total']}**")
            if nb["detail"]:
                st.caption(f"Son işlem ({nb['updated'][11:16]}): {nb['detail']}")
            if nb["state"] == "giriş gerekli":
                st.error("LinkedIn oturumu kapalı — yukarıdan 'Yeniden bağlan' yapın.")
            b1, b2, b3 = st.columns([1, 1, 1.3])
            if b1.button("Başlat", key="home_nb_start", disabled=nb["running"], width="stretch", type="primary"):
                _, msg = netbot.start(slug)
                st.toast(msg)
                st.rerun()
            if b2.button("Durdur", key="home_nb_stop", disabled=not nb["running"], width="stretch"):
                _, msg = netbot.stop(slug)
                st.toast(msg)
                st.rerun()
            if "network" in st.session_state.get("_pages", {}):
                b3.page_link(st.session_state["_pages"]["network"], label="Detaylar", icon=":material/tune:")

        with right:
            st.markdown(f"**Otomatik İlan Avcısı**  :{j_col}[● {j_lbl}]")
            nxt = f" · Sonraki tur: **{jb['next_run']}**" if jb["running"] and jb["next_run"] else ""
            st.caption(f"Bulunan: **{jb['found_total']}** · Analiz: **{jb['analyzed_total']}** · %{jobbot.PREP_MIN_SCORE}+ hazır fırsat: **{len(opps)}**{nxt}")
            if jb["detail"]:
                st.caption(f"Son işlem ({jb['updated'][11:16]}): {jb['detail']}")
            if jb["state"] == "lm kapalı":
                st.warning("LM Studio kapalı: tarama sürüyor, otomatik analiz için LM Studio sunucusunu açın.")
            b1, b2, b3 = st.columns([1, 1, 1.3])
            if b1.button("Başlat", key="home_jb_start", disabled=jb["running"], width="stretch", type="primary"):
                _, msg = jobbot.start(slug)
                st.toast(msg)
                st.rerun()
            if b2.button("Durdur", key="home_jb_stop", disabled=not jb["running"], width="stretch"):
                _, msg = jobbot.stop(slug)
                st.toast(msg)
                st.rerun()
            if "bulk" in st.session_state.get("_pages", {}):
                b3.page_link(st.session_state["_pages"]["bulk"], label="Fırsatlar", icon=":material/smart_toy:")

        t1, t2 = st.tabs(["📡 Canlı hareket akışı", "🤝 Son gönderilen davetler"])
        with t1:
            nb_logs = [f"[Ağ Botu] {l}" for l in netbot.recent_log(slug, 6)]
            jb_logs = [f"[İlan Avcısı] {l}" for l in jobbot.recent_log(slug, 6)]
            merged = sorted(nb_logs + jb_logs, key=lambda s: s.split("] ", 1)[-1][:11], reverse=True)[:10]
            st.code("\n".join(merged) if merged else "Henüz arka plan kaydı yok.", language=None)
        with t2:
            inv_rows = netbot.recent_invites(8)
            if inv_rows:
                st.dataframe(pd.DataFrame(inv_rows), hide_index=True, width="stretch",
                             column_config={"Profil": st.column_config.LinkColumn("Profil", display_text="Aç")})
            else:
                st.caption("Henüz davet kaydı yok.")


def page_home():
    header("Bugün ne yapıyoruz?", "İlan bul → analiz et → isabetli başvur → İK ağını büyüt. Üst menüden ilerleyin; sağ üstte kullanıcı menünüz var.")
    show_flash("home")

    st.subheader("Hesaplar")
    _connections()

    jobs = get_all_jobs()
    from app import followup
    upcoming = followup.upcoming_interviews(jobs)
    if upcoming:
        st.subheader("Yaklaşan mülakatlar")
        for iv_item in upcoming[:3]:
            c1, c2 = st.columns([3, 1])
            c1.info(f"📅 **{iv_item['Tarih']}** · **{iv_item['Şirket']}** — {iv_item['Pozisyon']} ({iv_item['Aşama']})")
            if c2.button("🎤 Prova yap", key=f"home_iv_{iv_item['id']}", width="stretch"):
                st.session_state["iv_preselect_job_id"] = iv_item["id"]
                if "interview" in st.session_state.get("_pages", {}):
                    st.switch_page(st.session_state["_pages"]["interview"])

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
    _live_center()

    due_fu = followup.due_followups(jobs)
    if due_fu and "success" in st.session_state.get("_pages", {}):
        f1, f2 = st.columns([3, 1])
        f1.markdown(f"**Takip bekleyen başvurular:** {len(due_fu)} ilanda 7+ gündür dönüş yok (hazır takip mesajları oluşturuldu).")
        f2.page_link(st.session_state["_pages"]["success"], label="Takip kuyruğu", icon=":material/mark_email_unread:")

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
