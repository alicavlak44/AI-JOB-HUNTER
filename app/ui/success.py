"""📈 Başarı: hesaplardan senkron → oranlar → öneriler → takip kuyruğu → LinkedIn profil optimizasyonu."""
import pandas as pd
import streamlit as st

from ai_engine import linkedin_opt
from app import account, context, followup
from app.ui.common import header, show_flash, set_flash
from browser.automator import sync_linkedin_account, sync_kariyernet_account
from database import stats
from database.db_manager import get_all_jobs, update_job_tracking


def _load_cv_profile():
    from ai_engine import cv_studio as cs
    from ai_engine.cv_builder import profile_text
    try:
        p, original = cs.load_profile(context.current())
        return p, profile_text(p) + "\n" + (original or "")
    except FileNotFoundError:
        from ai_engine.brain import read_cv_text
        text = read_cv_text() or ""
        return (cs.profile_from_text(text) if text else cs.empty_profile()), text


def _followup_section(jobs):
    st.subheader("Takip kuyruğu ve kabul edilen bağlantılar")
    due = followup.due_followups(jobs)
    accepted = followup.accepted_contacts(limit=15)
    t1, t2 = st.tabs([f"📬 Dönüş bekleyenler ({len(due)})", f"🤝 Kabul edilen bağlantılar ({len(accepted)})"])
    with t1:
        if not due:
            st.caption("7+ gündür dönüş bekleyen başvuru yok.")
        for item in due[:8]:
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"**{item['Şirket']}** — {item['Pozisyon']} · %{item['Puan']} uyum · _{item['Gün']} gün oldu_")
                if c2.button("Takip edildi ✓", key=f"fu_done_{item['id']}", width="stretch"):
                    row = jobs[jobs["id"] == item["id"]].iloc[0]
                    update_job_tracking(item["id"], row.get("pipeline_stage") or "Başvuruldu",
                                        row.get("interview_date") or "", row.get("notes") or "", mark_followed_up=True)
                    st.toast("Takip kaydedildi")
                    st.rerun()
                with st.expander("Hazır takip mesajı"):
                    st.code(followup.followup_message(item["Pozisyon"], item["Şirket"], context.name(), item["Gün"]),
                            language="text")
    with t2:
        if not accepted:
            st.caption("Botun davet edip bağlantıya dönen kişi henüz yok (hesapları senkronladıkça güncellenir).")
        else:
            st.dataframe(pd.DataFrame(accepted), hide_index=True, width="stretch",
                         column_config={"Profil": st.column_config.LinkColumn("Profil", display_text="Aç")})
            picked = st.selectbox("Tanışma mesajı taslağı hazırla", [a["Kişi"] for a in accepted], key="acc_pick")
            headline = (context.user().get("targets") or [""])[0]
            st.code(followup.welcome_connection_message(picked, context.name(), headline), language="text")


def _linkedin_opt_section():
    st.subheader("LinkedIn profil metinleri (uydurmasız)")
    st.caption("CV'nizdeki gerçek bilgilerden işe alımcı aramalarında öne çıkacak Başlık, Hakkında ve Yetenekler üretir; "
               "CV'de olmayan beceri veya sayı içeren her öneri otomatik reddedilir.")
    key = f"li_pack_{context.current()}"
    if st.button("✨ CV'imden LinkedIn profil metinleri üret", key="li_opt_btn"):
        profile, cv_text = _load_cv_profile()
        with st.spinner("CV'niz okunuyor, LinkedIn Başlık ve Hakkında metinleri üretilip denetleniyor..."):
            st.session_state[key] = linkedin_opt.generate_linkedin_pack(profile, cv_text, field=context.field())
    pack = st.session_state.get(key)
    if not pack:
        return
    if pack.get("ai_error"):
        st.warning("Yerel model cevap vermedi; doğrudan CV'nizden güvenli metinler oluşturuldu.")
    if pack.get("rejected"):
        st.caption(f"Uydurma denetimi: {len(pack['rejected'])} öneri CV'de olmayan bilgi içerdiği için reddedildi.")
    st.markdown("**Başlık (Headline) alternatifleri** _(en fazla 220 karakter)_")
    for h in pack["headlines"]:
        st.code(h, language="text")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Hakkında (Türkçe)**")
        st.text_area("Hakkında TR", value=pack["about_tr"], height=220, label_visibility="collapsed")
    with c2:
        st.markdown("**About (İngilizce)**")
        st.text_area("About EN", value=pack["about_en"] or "(Model kapalıyken yalnızca Türkçe taslak üretilir.)",
                     height=220, label_visibility="collapsed")
    if pack["skills"]:
        st.markdown("**LinkedIn 'Yetenekler' bölümüne eklenecek beceriler:** " + " · ".join(pack["skills"]))


def page_success():
    header("Başarı ve Öneriler", "Hesaplarınızdan sadece okuyarak: başvurular, görüntülenmeler, mülakatlar, bağlantılar.")
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
    st.subheader("Başarı oranını artırmak için")
    if not recs:
        st.success("Göstergeler iyi görünüyor." if li else "Önce senkronlayın.")
    for prio, title, body in recs:
        with st.container(border=True):
            st.markdown(f"{'🔴 Önemli' if prio == 1 else '🟠 Orta' if prio == 2 else '🟡 Düşük'} · **{title}**")
            st.caption(body)

    _followup_section(jobs)
    _linkedin_opt_section()

    with st.expander("📊 Grafikler"):
        g1, g2 = st.columns([3, 2])
        g1.caption("Son 14 gün")
        g1.altair_chart(stats.daily_chart(jobs), width="stretch")
        g2.caption("Süreç hunisi")
        g2.bar_chart(stats.funnel(jobs), horizontal=True, height=260)
        st.caption("Uyum puanı dağılımı")
        st.bar_chart(stats.score_distribution(jobs), height=200)
