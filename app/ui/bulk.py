"""🚀 Toplu Başvuru: 1) bekleyenleri analiz et → 2) uygunları seç → 3) başvur (+ İK daveti)."""
import pandas as pd
import streamlit as st

from app import campaign, context, guard
from app.settings import AUTO_APPLY_MIN_SCORE, MAX_DAILY_APPLICATIONS
from app.ui.common import header, step
from app.ui.jobbot_card import jobbot_card
from database.db_manager import get_all_jobs


def page_bulk():
    header("Toplu Başvuru", "Sadece işaretlediğiniz ilanlara başvurulur. Hesap koruması her adımda uygulanır.")
    jobbot_card()
    jobs = get_all_jobs()
    if jobs.empty:
        st.info("Henüz ilan yok → 🔎 İlanlar sayfasından ilan getirin ya da yukarıdan Otomatik ilan avcısını başlatın.")
        return

    step("1️⃣ Bekleyen ilanları analiz et")
    pending = campaign.unanalyzed_jobs(jobs)
    if pending.empty:
        st.caption("✅ Analiz bekleyen ilan yok.")
    else:
        c1, c2 = st.columns([1, 2])
        n = c1.number_input("Kaç ilan?", 1, len(pending), min(5, len(pending)), help="Hızlı analiz: ilan başına ~1-2 dk")
        c2.markdown("<br>", unsafe_allow_html=True)
        if c2.button(f"🧠 {len(pending)} bekleyenden {n} tanesini analiz et", width="stretch"):
            bar = st.progress(0.0, text="Analiz başlıyor...")
            for k, (_, r) in enumerate(pending.head(int(n)).iterrows(), 1):
                bar.progress((k - 1) / n, text=f"[{k}/{n}] {r['Şirket']} — {r['Pozisyon']}")
                ok, m = campaign.analyze_job(r)
                (st.success if ok else st.warning)(f"{r['Şirket']} — {r['Pozisyon']}: {m}")
            bar.progress(1.0, text="Bitti")
            st.rerun()

    step("2️⃣ Başvurulacak ilanları seç")
    s1, s2 = st.columns([2, 1])
    min_score = s1.slider("En düşük uyum puanı", 0, 100, AUTO_APPLY_MIN_SCORE, 5,
                          help="Düşük puanlı ilanlara başvurmak görüntülenme oranınızı düşürür.")
    s2.markdown("<br>", unsafe_allow_html=True)
    only_large = s2.checkbox("🏢 Sadece büyük/kurumsal şirketler",
                             value=bool(context.user().get("only_large_companies")),
                             help="Küçük, butik veya ölçeği doğrulanmayan şirketleri gizler.")
    cand = campaign.eligible_jobs(jobs, min_score, only_large=only_large, exclude_small=True)
    if cand.empty:
        st.info(f"Uyum puanı %{min_score}+ olan, başvurulmamış ilan yok. Önce analiz edin, eşiği düşürün ya da ölçek filtresini genişletin.")
    else:
        all_on = st.checkbox(f"✅ Tümünü seç ({len(cand)} ilan)", key=f"bulk_all_{hash(tuple(cand['id']))}")
        table = cand[["id", "Kaynak", "Ölçek", "Şirket", "Pozisyon", "Şehir", "puan", "recommendation"]].rename(
            columns={"puan": "Puan", "recommendation": "Öneri"})
        table.insert(0, "Onay", all_on)
        edited = st.data_editor(table, hide_index=True, width="stretch",
                                key=f"campaign_table_{hash(tuple(table['id']))}_{all_on}",
                                disabled=[c for c in table.columns if c != "Onay"],
                                column_config={"Onay": st.column_config.CheckboxColumn("Onay"),
                                               "Puan": st.column_config.ProgressColumn("Puan", min_value=0, max_value=100, format="%d")})
        approved = edited.loc[edited["Onay"], "id"].tolist()

        with st.expander("📃 Başvuru öncesi ilan detayını incele"):
            labels = {int(r.id): f"#{r.id} · %{int(r.puan)} · {r.Şirket} — {r.Pozisyon}" for r in cand.itertuples()}
            inspect_id = st.selectbox("İncelemek istediğiniz ilan", list(labels), format_func=labels.get, key="bulk_inspect")
            irow = jobs[jobs["id"] == inspect_id].iloc[0]
            ic1, ic2 = st.columns([2, 1])
            with ic1:
                st.markdown("**İlan metni**")
                st.text_area("İlan metni", value=(irow.get("details") or "(İlan metni henüz çekilmedi)"),
                             height=260, label_visibility="collapsed", key=f"bulk_det_{inspect_id}")
            with ic2:
                st.markdown("**Özet değerlendirme**")
                if isinstance(irow.get("matching_skills"), str) and irow["matching_skills"].strip():
                    st.markdown(f"✅ **CV'de olan:** {irow['matching_skills']}")
                if isinstance(irow.get("missing_skills"), str) and irow["missing_skills"].strip():
                    st.markdown(f"🧩 **Eksik:** {irow['missing_skills']}")
                if isinstance(irow.get("evaluation"), str) and irow["evaluation"].strip():
                    st.write(irow["evaluation"])

        step("3️⃣ Başvur")
        o1, o2 = st.columns(2)
        invite = o1.checkbox("Her şirketin İK yöneticisine de davet gönder", value=True,
                             help="Şirket adıyla eşleşen, ağınızda olmayan 1 İK kişisi otomatik seçilir.")
        mode = o2.radio("Mod", ["Tam otonom", "Yarı otonom"], horizontal=True,
                        help="Tam: boş zorunlu alanda durur. Yarı: formu siz gönderirsiniz.")
        used = {p: guard.status(p)["başvuru"]["bugün"] for p in ("LinkedIn", "Kariyer.net")}
        blocked = [p for p in used if guard.status(p)["engel"]]
        st.caption(f"Bugün: LinkedIn {used['LinkedIn']} · Kariyer.net {used['Kariyer.net']} başvuru "
                   f"(platform başına sınır {MAX_DAILY_APPLICATIONS}). Açılan Chrome penceresini kapatmayın.")
        if blocked:
            st.warning(f"Şu an durdurulmuş platform: {', '.join(blocked)} — bu platformun ilanları atlanır.")
        if st.button(f"🚀 Seçilen {len(approved)} ilana başvur", type="primary", disabled=not approved, width="stretch"):
            rows = [r.to_dict() for _, r in jobs[jobs["id"].isin(approved)].iterrows()]
            with st.status(f"{len(rows)} ilan için başvuru sürüyor...", expanded=True) as box:
                res = campaign.run_campaign(rows, mode="tam" if mode == "Tam otonom" else "yari",
                                            invite_hr=invite, on_progress=box.write)
                box.update(label="Bitti", state="complete")
            st.session_state["campaign_results"] = res
            st.rerun()

    if st.session_state.get("campaign_results"):
        st.subheader("Son sonuç")
        st.dataframe(pd.DataFrame(st.session_state["campaign_results"]), hide_index=True, width="stretch")
