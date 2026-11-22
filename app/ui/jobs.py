"""🔎 İlanlar: ara → listele → bir ilanı seç → analiz / başvuru / özel CV."""
import json
import os

import streamlit as st

from ai_engine.brain import extract_positions_from_cv, AIError, check_ai, read_cv_text
from ai_engine.company_tier import TIER_LARGE, TIER_SMALL, classify_company
from ai_engine.cv_builder import build_tailored_cv
from ai_engine.role_class import (ALL_ROLE_CLASSES, ROLE_BADGE, classify_role,
                                  detect_candidate_role_profile, matches_role_prefs)
from app import campaign, context, followup, settings
from app.logger import get_logger
from app.settings import STATUS_APPLIED_VERIFIED
from app.ui.common import header, show_flash, set_flash, msg_kind, txt
from browser.automator import (scrape_kariyernet_browser, run_application_bot, open_linkedin_hr_hunter,
                               choose_cv, fetch_job_description_browser)
from browser.scraper import scrape_linkedin_jobs, build_hr_search_url, stats_message, fetch_job_description
from database.db_manager import (get_all_jobs, delete_single_job, delete_unprocessed_jobs,
                                 set_tailored_cv, update_job_details, update_job_tracking)

log = get_logger("ui.jobs")


def _search():
    key = f"positions_{context.current()}"
    if key not in st.session_state:
        st.session_state[key] = context.user().get("targets") or ["Uzman"]
    c1, c2, c3 = st.columns([2.2, 1, 1.2])
    pos = c1.selectbox("Pozisyon", st.session_state[key], accept_new_options=True,
                       help="Listeden seçin veya yeni bir unvan yazın")
    city = c2.text_input("Şehir", value=context.user().get("city", "Ankara"))
    src = c3.radio("Kaynak", ["LinkedIn (hızlı)", "Kariyer.net"], horizontal=True)
    auto_ats = st.checkbox("⚡ İlanları çekerken CV'ye göre ATS uyumluluğunu hemen kontrol et",
                           value=settings.ai_config()["is_cloud"],
                           help="Bulut API (Gemini vb.) ile yeni gelen her ilanın detayını ve CV uyum puanını anında hesaplar.")
    b1, b2 = st.columns([1, 1])
    if b1.button("🔎 İlanları getir", type="primary", width="stretch"):
        before_ids = set(get_all_jobs()["id"].tolist()) if not get_all_jobs().empty else set()
        with st.spinner("İlanlar çekiliyor..."):
            st_res = (scrape_linkedin_jobs(pos, city) if src.startswith("LinkedIn")
                      else scrape_kariyernet_browser(pos, city))
            m = stats_message("LinkedIn" if src.startswith("LinkedIn") else "Kariyer.net", st_res)
        if auto_ats and st_res.get("added", 0) > 0:
            ai_ok, ai_msg = check_ai()
            if ai_ok:
                all_now = get_all_jobs()
                newly = all_now[~all_now["id"].isin(before_ids)]
                only_big = bool(context.user().get("only_large_companies"))
                u_roles = context.user().get("allowed_role_classes") or None
                u_fresh = bool(context.user().get("fresh_grad_only"))
                rows_to_score = []
                for _, r in newly.iterrows():
                    ct = classify_company(r.get("Şirket"), r.get("details"), r.get("Pozisyon"))
                    if only_big and ct["tier"] == TIER_SMALL:
                        continue
                    if (u_roles or u_fresh) and not matches_role_prefs(r.get("Pozisyon"), r.get("details"), u_roles, u_fresh):
                        continue
                    rows_to_score.append(r)
                if rows_to_score:
                    bar = st.progress(0.0, text=f"CV'ye göre ATS kontrolü başlıyor ({len(rows_to_score)} yeni ilan)...")
                    scored = 0
                    for idx, r in enumerate(rows_to_score[:20], 1):
                        bar.progress((idx - 1) / min(len(rows_to_score), 20),
                                     text=f"[{idx}/{min(len(rows_to_score), 20)}] ATS: {r['Şirket']} — {r['Pozisyon']}")
                        ok_a, _ = campaign.analyze_job(r, brief=True)
                        if ok_a:
                            scored += 1
                    bar.progress(1.0, text="ATS kontrolü bitti")
                    m += f" · **{scored} yeni ilanın CV/ATS uyumu hesaplandı.**"
            else:
                m += f" (ATS atlandı: {ai_msg})"
        set_flash("jobs", msg_kind(m), m)
        st.rerun()
    if b2.button("🧠 CV'ime göre pozisyon öner", width="stretch"):
        with st.spinner("Yapay zeka CV'nizden uygun unvanları çıkarıyor..."):
            try:
                found = extract_positions_from_cv()
            except AIError as e:
                found = []
                set_flash("jobs", "error", f"❌ {e}")
        if found:
            st.session_state[key] = found
            context.update_user(context.current(), targets=found)
            set_flash("jobs", "success", "✅ Pozisyon listesi CV'nize göre güncellendi.")
        st.rerun()


def _job_detail(jobs):
    labels = {int(r.id): f"#{r.id} · {r.Pozisyon} — {r.Şirket} · {r.Durum}" for r in jobs.itertuples()}
    sel = st.selectbox("İlan seçin", list(labels), format_func=labels.get)
    row = jobs[jobs["id"] == sel].iloc[0]
    apply_cv = choose_cv(row["tailored_cv_path"])

    a1, a2, a3, a4, a5, a6 = st.columns([1.2, 1.1, 1.1, 1.1, 1.1, 0.5])
    if a1.button("🧠 Analiz et (tam)", type="primary", width="stretch"):
        with st.spinner("İlan okunuyor; puan, ön yazı ve İK notu üretiliyor..."):
            ok, m = campaign.analyze_job(row, brief=False)
        set_flash("detail", "success" if ok else "error", ("✅ " if ok else "❌ ") + m)
        st.rerun()
    if a2.button("🛡️ Yarı otonom başvur", width="stretch", help="Form açılır, siz gönderirsiniz"):
        with st.spinner("İlan sayfası açılıyor. Formu tamamlayıp gönderin, sonra pencereyi kapatın..."):
            status, msg = run_application_bot(int(sel), row["url"], mode="yari", cv_path=apply_cv)
        set_flash("detail", "success" if status == STATUS_APPLIED_VERIFIED else "warning", f"{status}: {msg}" if status else msg)
        st.rerun()
    if a3.button("🚀 Tam otonom başvur", width="stretch", help="Boş zorunlu alan çıkarsa durur ve size bırakır"):
        with st.spinner("Başvuru adımları yürütülüyor..."):
            status, msg = run_application_bot(int(sel), row["url"], mode="tam", cv_path=apply_cv)
        set_flash("detail", "success" if status == STATUS_APPLIED_VERIFIED else "warning", f"{status}: {msg}" if status else msg)
        st.rerun()
    if a4.button("🤝 Şirketin İK'sını aç", width="stretch"):
        with st.spinner(f"{row['Şirket']} İK uzmanları LinkedIn'de açılıyor..."):
            open_linkedin_hr_hunter(build_hr_search_url(row["Şirket"], row["Şehir"]))
    if a5.button("🎤 Mülakat provası", width="stretch", help="Bu ilanın gereksinimleriyle sesli mülakat provası başlat"):
        st.session_state["iv_preselect_job_id"] = int(sel)
        if "interview" in st.session_state.get("_pages", {}):
            st.switch_page(st.session_state["_pages"]["interview"])
    if a6.button("🗑️", width="stretch", help="İlanı sil"):
        delete_single_job(int(sel))
        st.rerun()
    show_flash("detail")
    if txt(row["last_error"]):
        st.caption(f"ℹ️ {row['last_error']}")

    if not (txt(row["evaluation"]) or txt(row["cover_letter"])):
        st.info("Bu ilan henüz analiz edilmedi. '🧠 Analiz et' ile uyum puanını görün; aşağıdan ilan metnini şimdiden inceleyebilirsiniz.")
        t_det, t_trk = st.tabs(["📃 İlan detayı", "📋 Süreç takibi"])
        with t_det:
            _details_panel(int(sel), row)
        with t_trk:
            _tracking_panel(int(sel), row)
        return

    m1, m2 = st.columns([1, 3])
    m1.metric("Uyum puanı", row["ATS Uyum"], help="65 ve üzeri: başvurun")
    if txt(row["recommendation"]):
        m1.caption(f"Öneri: **{row['recommendation']}**")
    with m2:
        st.markdown(f"🔑 **Anahtar kelimeler:** {row['golden_keywords']}")
        if txt(row["matching_skills"]):
            st.markdown(f"✅ **CV'de olan:** {row['matching_skills']}")
        if txt(row["missing_skills"]):
            st.markdown(f"🧩 **Eksik:** {row['missing_skills']}")

    t0, t1, t2, t3, t4, t5 = st.tabs(["📃 İlan detayı", "📊 Değerlendirme", "✍️ Ön yazı", "🤝 İK notu", "📄 İlana özel CV", "📋 Süreç takibi"])
    with t0:
        _details_panel(int(sel), row)
    with t1:
        st.write(row["evaluation"])
        if txt(row["match_facts"]):
            fx = json.loads(row["match_facts"])
            f = st.columns(3)
            f[0].metric("Deneyim (staj hariç)", f"{fx['cv_years']} yıl",
                        delta=None if not fx["required_years"] else f"ilan: {fx['required_years']} yıl",
                        delta_color="normal" if fx["experience_ok"] in (True, None) else "inverse")
            f[1].metric("Beceri kapsamı", "—" if fx["skill_coverage"] is None else f"%{round(fx['skill_coverage'] * 100)}")
            f[2].metric("Bölüm şartı", {True: "Uyumlu", False: "Uyumsuz", None: "Yok"}[fx["degree_match"]])
    with t2:
        if txt(row["cover_letter"]):
            st.text_area("Ön yazı", value=row["cover_letter"], height=260, label_visibility="collapsed")
        else:
            st.caption("Hızlı analizde ön yazı üretilmez → '🧠 Analiz et (tam)'.")
    with t3:
        if txt(row["hr_message"]):
            st.code(row["hr_message"], language="text")
        else:
            st.caption("Hızlı analizde İK notu üretilmez → '🧠 Analiz et (tam)'.")
    with t4:
        st.caption("CV'deki bilgiler ilana göre yeniden sıralanır; CV'de olmayan hiçbir şey eklenmez.")
        if st.button("📄 İlana özel CV üret"):
            with st.spinner("CV ilana göre düzenleniyor ve denetleniyor (1-3 dk)..."):
                try:
                    res = build_tailored_cv(int(sel), row["Pozisyon"], row["Şirket"], row["details"] or "")
                    set_tailored_cv(int(sel), res["path"])
                    rep = res["report"]
                    set_flash("detail", "success", f"✅ Özel CV hazır: {len(rep['accepted'])} düzenleme kabul, "
                                                   f"{len(rep['rejected'])} uydurma şüphesi reddedildi.")
                except AIError as e:
                    set_flash("detail", "error", f"❌ CV üretilemedi: {e}")
                except Exception as e:
                    log.exception("İlan #%s için CV üretiminde hata", sel)
                    set_flash("detail", "error", f"❌ Beklenmeyen hata: {e}")
            st.rerun()
        cv_path = row["tailored_cv_path"] if isinstance(row["tailored_cv_path"], str) else None
        if cv_path and os.path.exists(cv_path):
            with open(cv_path, "rb") as fh:
                st.download_button("⬇️ CV'yi indir (.docx)", fh.read(), file_name=os.path.basename(cv_path))
        if apply_cv:
            st.caption(f"📎 Başvuruda yüklenecek: **{os.path.basename(apply_cv)}**")
    with t5:
        _tracking_panel(int(sel), row)


def _details_panel(job_id, row):
    det = txt(row.get("details"))
    ct = classify_company(row.get("Şirket"), det, row.get("Pozisyon"))
    rc = classify_role(row.get("Pozisyon"), det)
    c1, c2 = st.columns([3, 1])
    c1.caption(f"Sınıf: **{rc['display']}** · Ölçek: **{ct['badge']}** ({ct['reason']}) · Kaynak: **{row['Kaynak']}** · "
               f"Şehir: **{row['Şehir']}** · " + (f"{len(det)} karakter detay" if det else "İlan detayı henüz çekilmedi"))
    if c2.button("🔄 Detayı çek", key=f"det_fetch_{job_id}", width="stretch"):
        with st.spinner("İlan metni çekiliyor..."):
            url = row.get("url") or ""
            fetched = fetch_job_description(url) if row["Kaynak"] != "Kariyer.net" else ""
            if len(fetched) < 200 and row["Kaynak"] == "Kariyer.net":
                fetched = fetch_job_description_browser(url)
            if fetched and len(fetched) >= 80:
                update_job_details(job_id, fetched)
                set_flash("detail", "success", f"✅ İlan detayı çekildi ({len(fetched)} karakter).")
            else:
                set_flash("detail", "warning", "⚠️ İlan detayı alınamadı; ilan kapanmış veya koruma sınırında olabilir.")
        st.rerun()
    if det:
        st.text_area("İlan metni", value=det, height=340, label_visibility="collapsed", key=f"det_txt_{job_id}")
    else:
        st.info("Bu ilanın tam metni henüz çekilmedi. Yukarıdaki '🔄 Detayı çek' düğmesiyle ya da arka plandaki İlan Avcısı ile otomatik çekilir.")


def _tracking_panel(job_id, row):
    cur_stage = txt(row.get("pipeline_stage"))
    stage_opts = ["(belirtilmedi)"] + followup.STAGES
    s_idx = stage_opts.index(cur_stage) if cur_stage in stage_opts else 0
    c1, c2 = st.columns([1.2, 1])
    stage = c1.selectbox("Başvuru sonrası aşama", stage_opts, index=s_idx, key=f"tr_st_{job_id}")
    iv_date = c2.text_input("Mülakat tarihi (isteğe bağlı)", value=txt(row.get("interview_date")),
                            placeholder="2026-11-28 14:00", key=f"tr_dt_{job_id}")
    notes = st.text_area("Notlar (görüşülen kişi, maaş beklentisi, izlenim...)", value=txt(row.get("notes")),
                         height=90, key=f"tr_nt_{job_id}")
    b1, b2 = st.columns(2)
    if b1.button("💾 Süreç bilgisini kaydet", key=f"tr_sv_{job_id}", width="stretch"):
        update_job_tracking(job_id, "" if stage == "(belirtilmedi)" else stage, iv_date, notes)
        set_flash("detail", "success", "✅ Süreç takibi kaydedildi.")
        st.rerun()
    if b2.button("✉️ Takip mesajı gönderildi işaretle", key=f"tr_fu_{job_id}", width="stretch"):
        update_job_tracking(job_id, "" if stage == "(belirtilmedi)" else stage, iv_date, notes, mark_followed_up=True)
        set_flash("detail", "success", "✅ Takip zamanı kaydedildi.")
        st.rerun()
    if txt(row.get("followed_up_at")):
        st.caption(f"Son takip: {row['followed_up_at']}")
    with st.expander("Hazır takip mesajı taslağı (kopyalayıp LinkedIn / e-posta ile gönderin)"):
        st.code(followup.followup_message(row["Pozisyon"], row["Şirket"], context.name()), language="text")


def page_jobs():
    header("İlanlar", "Ara, listeyi incele, bir ilanı seçip analiz et veya başvur.")
    with st.container(border=True):
        _search()
    show_flash("jobs")

    jobs = get_all_jobs()
    if jobs.empty:
        st.info("Henüz ilan yok. Yukarıdan '🔎 İlanları getir'.")
        return

    st.subheader(f"İlanlar ({len(jobs)})")
    u = context.user()
    default_roles = u.get("allowed_role_classes") or detect_candidate_role_profile(read_cv_text())["suggested_classes"]
    f1, f2, f3 = st.columns([1.6, 1.5, 1.8])
    search_q = f1.text_input("Ara (şirket / pozisyon)", placeholder="Örn: Aselsan, Sistem, Tekniker")
    status_filter = f2.multiselect("Duruma göre süz", sorted(jobs["Durum"].dropna().unique()), placeholder="Tümü")
    role_filter = f3.multiselect("Kadro sınıfı (Tekniker / Uzman / Mühendis)", ALL_ROLE_CLASSES,
                                 default=[r for r in default_roles if r in ALL_ROLE_CLASSES],
                                 format_func=lambda r: f"{ROLE_BADGE[r]} ({r})",
                                 placeholder="Tümü (Mühendis dahil)")
    t1, t2, t3 = st.columns([1.4, 1.5, 1])
    only_large = t1.checkbox("🏢 Sadece büyük/kurumsal şirketler", value=bool(u.get("only_large_companies")),
                             help="Bilinen büyük/kurumsal şirketler ve büyük ölçek sinyalli ilanlar")
    fresh_only = t2.checkbox("🎓 Yeni mezun / junior / yetiştirilmek üzere", value=bool(u.get("fresh_grad_only")),
                             help="Yeni mezun, junior, yetiştirilmek üzere veya 0-2 yıl ilanları süzer")
    if t3.button("🧹 İşlenmemişleri temizle", width="stretch"):
        delete_unprocessed_jobs()
        st.rerun()
    view = jobs[jobs["Durum"].isin(status_filter)] if status_filter else jobs
    if search_q.strip():
        q_low = search_q.strip().lower()
        mask = (view["Şirket"].fillna("").str.lower().str.contains(q_low, regex=False) |
                view["Pozisyon"].fillna("").str.lower().str.contains(q_low, regex=False))
        view = view[mask]
    view = view.copy()
    tiers = [classify_company(r.get("Şirket"), r.get("details"), r.get("Pozisyon")) for _, r in view.iterrows()]
    roles = [classify_role(r.get("Pozisyon"), r.get("details")) for _, r in view.iterrows()]
    view["_tier"] = [t["tier"] for t in tiers]
    view["Ölçek"] = [t["badge"] for t in tiers]
    view["Sınıf"] = [rc["display"] for rc in roles]
    if only_large:
        view = view[view["_tier"] == TIER_LARGE]
    if role_filter or fresh_only:
        keep = [matches_role_prefs(r.get("Pozisyon"), r.get("details"), role_filter or None, fresh_only)
                for _, r in view.iterrows()]
        view = view[keep]
    view["Detay"] = view["details"].fillna("").str.len().map(lambda n: "✓" if n >= 200 else "—")
    st.caption(f"Gösterilen: **{len(view)}** / {len(jobs)} ilan")
    st.dataframe(view[["id", "Kaynak", "Ölçek", "Sınıf", "Pozisyon", "Şirket", "Şehir", "Detay", "ATS Uyum", "Durum", "url"]],
                 width="stretch", hide_index=True, height=320,
                 column_config={"url": st.column_config.LinkColumn("İlan", display_text="Aç")})

    st.subheader("Seçili ilan")
    with st.container(border=True):
        _job_detail(view if not view.empty else jobs)
