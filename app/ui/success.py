"""📈 Başarı: hesaplardan senkron → oranlar → tüm öneriler."""
import streamlit as st

from app import account
from app.ui.common import header, show_flash, set_flash
from browser.automator import sync_linkedin_account, sync_kariyernet_account
from database import stats
from database.db_manager import get_all_jobs


def page_success():
    header("📈 Başarı ve Öneriler", "Hesaplarınızdan sadece okuyarak: başvurular, görüntülenmeler, mülakatlar, bağlantılar.")
    li, kn = account.latest_snapshot("LinkedIn"), account.latest_snapshot("Kariyer.net")
    c1, c2 = st.columns([1, 2])
    if c1.button("🔄 Hesaplarımdan senkronla", type="primary" if not li else "secondary", width="stretch",
                 help="LinkedIn + Kariyer.net, 2-4 dk. Zaten başvurduğunuz ilanlar işaretlenir."):
        out = []
        with st.spinner("LinkedIn okunuyor..."):
            out.append(("LinkedIn", sync_linkedin_account()))
        with st.spinner("Kariyer.net okunuyor..."):
            out.append(("Kariyer.net", sync_kariyernet_account()))
        set_flash("success", "success" if all(r["ok"] for _, r in out) else "warning",
                  "  \n".join(f"**{p}:** {r.get('summary') or r.get('error')}" for p, r in out))
        st.rerun()
    c2.caption(f"Son senkron — LinkedIn: **{li['_synced_at'] if li else 'hiç'}** · "
               f"Kariyer.net: **{kn['_synced_at'] if kn else 'hiç'}**")
    show_flash("success")

    metrics = account.success_metrics(li, kn)
    if metrics:
        for col, (label, (value, frac)) in zip(st.columns(len(metrics)), metrics.items()):
            col.metric(label, "—" if value is None else f"%{value}", help=frac)

    jobs = get_all_jobs()
    scores = [x for x in jobs["ATS Uyum"].map(stats.parse_score).dropna()] if not jobs.empty else []
    recs = account.recommendations(li, kn, avg_score=round(sum(scores) / len(scores)) if scores else None)
    st.subheader("🎯 Başarı oranını artırmak için")
    if not recs:
        st.success("Göstergeler iyi görünüyor." if li else "Önce senkronlayın.")
    for prio, title, body in recs:
        with st.container(border=True):
            st.markdown(f"{'🔴 Önemli' if prio == 1 else '🟠 Orta' if prio == 2 else '🟡 Düşük'} · **{title}**")
            st.caption(body)

    with st.expander("📊 Grafikler"):
        g1, g2 = st.columns([3, 2])
        g1.caption("Son 14 gün")
        g1.altair_chart(stats.daily_chart(jobs), width="stretch")
        g2.caption("Süreç hunisi")
        g2.bar_chart(stats.funnel(jobs), horizontal=True, height=260)
        st.caption("Uyum puanı dağılımı")
        st.bar_chart(stats.score_distribution(jobs), height=200)
