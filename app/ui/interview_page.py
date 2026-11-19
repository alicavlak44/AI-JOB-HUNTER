"""Mülakat Provası: yapay zekâ mülakatçı soruları sesli sorar, aday sesli (ya da yazılı) cevaplar, sonunda karne.

Ses tamamen yerel: soru macOS Türkçe sesiyle okunur, cevap yerel Whisper ile yazıya çevrilir.
"""
import pandas as pd
import streamlit as st

from ai_engine import interview as iv
from ai_engine import voice
from app import context
from app.ui.common import header, show_flash, set_flash
from database.db_manager import get_all_jobs

INTERVIEWER, CANDIDATE = ":material/record_voice_over:", ":material/person:"
FIELD_LABEL = {"it": "Bilgi Teknolojileri", "ik": "İnsan Kaynakları", "genel": "Genel"}


def _k(name):
    return f"iv_{name}_{context.current()}"


def _reset():
    for name in ("plan", "idx", "results", "setup", "transcript", "pending_eval", "saved", "followups"):
        st.session_state.pop(_k(name), None)


def _say(text, avatar=INTERVIEWER, role="assistant"):
    with st.chat_message(role, avatar=avatar):
        st.markdown(text)


def _play(text):
    if st.session_state.get(_k("setup"), {}).get("voice") and voice.tts_available():
        try:
            st.audio(voice.speak(text), format="audio/wav", autoplay=True)
        except voice.VoiceError as e:
            st.caption(f"Ses çalınamadı: {e}")


def _cv():
    """(profil, CV düz metni) — CV Stüdyosu profili varsa ondan."""
    from ai_engine import cv_studio as cs
    from ai_engine.cv_builder import profile_text
    try:
        p, original = cs.load_profile(context.current())
        return p, profile_text(p) + "\n" + (original or "")
    except FileNotFoundError:
        from ai_engine.brain import read_cv_text
        text = read_cv_text() or ""
        return cs.profile_from_text(text) if text else cs.empty_profile(), text


# ---------------------------------------------------------------- kurulum
def _setup():
    field = context.field()
    st.markdown("#### Yeni mülakat")
    jobs = get_all_jobs()
    options = {f"Genel — {FIELD_LABEL.get(field, field)} pozisyonları": ("", "")}
    if not jobs.empty:
        for _, r in jobs[jobs["details"].fillna("").str.len() > 50].head(40).iterrows():
            options[f"{r['Pozisyon']} — {r['Şirket']}"] = (r["Pozisyon"], r["details"])
    c1, c2 = st.columns([2, 1])
    target = c1.selectbox("Hangi pozisyon için prova?", list(options),
                          help="Analiz edilmiş ilanlarınızdan birini seçerseniz sorular o ilanın gereksinimlerine göre olur.")
    custom = c2.text_input("ya da unvan yazın", placeholder="Örn: Sistem Uzmanı")
    c1, c2, c3, c4 = st.columns(4)
    n_tech = c1.number_input("Teknik soru", 2, 6, 4)
    n_beh = c2.number_input("Davranışsal soru", 1, 3, 2)
    mode = c3.segmented_control("Cevap", ["Sesli", "Yazılı"], default="Sesli" if voice.stt_available() else "Yazılı")
    fb = c4.segmented_control("Geri bildirim", ["Her cevaptan sonra", "Sonunda"], default="Her cevaptan sonra")
    if mode == "Sesli" and not voice.stt_available():
        st.warning("Konuşma tanıma kurulu değil (venv/bin/pip install mlx-whisper). Şimdilik yazılı cevap verebilirsiniz.")
    if not voice.tts_available():
        st.caption(f"Mülakatçı sesi ({voice.TTS_VOICE}) bulunamadı; sorular yalnızca yazılı gösterilecek. "
                   "Sistem Ayarları → Erişilebilirlik → Sesli İçerik'ten Türkçe ses ekleyebilirsiniz.")
    if st.button("Mülakatı başlat", type="primary", icon=":material/play_arrow:"):
        title, job_text = options[target]
        title = custom.strip() or title
        profile, cv_text = _cv()
        with st.status("Mülakatçı hazırlanıyor: CV'niz ve pozisyon okunuyor, sorular seçiliyor...", expanded=False) as box:
            plan, err = iv.plan_interview(profile, field, title, job_text, int(n_tech), int(n_beh))
            box.update(label=f"{len(plan)} soruluk mülakat hazır", state="complete")
        if err:
            set_flash("iv", "warning", "Yerel model zamanında cevap vermedi; sorular alanınızın soru bankasından seçildi.")
        st.session_state[_k("setup")] = {"title": title or (profile.get("headline") or "Genel"), "field": field,
                                          "voice": mode == "Sesli", "feedback_each": fb != "Sonunda",
                                          "cv_text": cv_text, "name": (profile.get("name") or "").split(" ")[0]}
        st.session_state[_k("plan")] = plan
        st.session_state[_k("idx")] = 0
        st.session_state[_k("results")] = []
        st.session_state[_k("followups")] = 0
        st.rerun()

    past = iv.list_sessions(context.current())
    if past:
        st.markdown("#### Önceki provalarınız")
        st.dataframe(pd.DataFrame(past), hide_index=True, width="stretch",
                     column_config={"Puan": st.column_config.ProgressColumn("Puan", min_value=0, max_value=100, format="%d")})


# ---------------------------------------------------------------- mülakat
def _feedback_card(ev):
    with st.container(border=True):
        st.markdown(f"**Puan: {ev['score']}/5**" + ("" if ev.get("source") == "yapay zekâ" else " · (kural tabanlı)"))
        if ev.get("strengths"):
            st.markdown("**İyi olan:** " + " · ".join(ev["strengths"]))
        if ev.get("improve"):
            st.markdown("**Geliştirin:** " + " · ".join(ev["improve"]))
        if ev.get("better"):
            with st.expander("Daha iyi bir cevap örneği (köşeli parantezleri kendi bilgilerinizle doldurun)"):
                st.markdown(ev["better"])


def _interview():
    setup, plan = st.session_state[_k("setup")], st.session_state[_k("plan")]
    idx, results = st.session_state[_k("idx")], st.session_state[_k("results")]
    st.progress(min(1.0, idx / len(plan)), text=f"Soru {min(idx + 1, len(plan))} / {len(plan)} · {setup['title']}")
    if idx == 0 and not results:
        greet = (f"Merhaba {setup['name']}, hoş geldiniz. Bugün {setup['title']} pozisyonu için yaklaşık "
                 f"{len(plan)} soruluk bir görüşme yapacağız. Hazırsanız başlayalım.")
        _say(greet)
    for r in results:  # geçmiş
        _say(f"*{iv.STAGE_LABEL.get(r['question']['stage'], '')}* — {r['question']['question']}")
        _say(r["answer"] or "_(geçildi)_", avatar=CANDIDATE, role="user")
        if r.get("eval") and setup["feedback_each"]:
            _feedback_card(r["eval"])

    if idx >= len(plan):
        return _finish()
    q = plan[idx]
    _say(f"*{iv.STAGE_LABEL.get(q['stage'], '')}* — **{q['question']}**")
    _play((f"Merhaba {setup['name']}. " if idx == 0 and not results else "") + q["question"])

    tkey = _k(f"tr_{idx}")
    if setup["voice"] and voice.stt_available():
        rec = st.audio_input("Cevabınızı kaydedin (bitince durdurun)", key=_k(f"rec_{idx}"))
        if rec is not None and st.session_state.get(_k(f"rec_done_{idx}")) != rec.file_id:
            with st.spinner("Cevabınız yazıya çevriliyor (bilgisayarınızda)..."):
                try:
                    st.session_state[tkey] = voice.transcribe(rec.getvalue(), prompt=q["question"])
                except voice.VoiceError as e:
                    st.error(str(e))
            st.session_state[_k(f"rec_done_{idx}")] = rec.file_id
    answer = st.text_area("Cevabınız" + (" (yazıya döküldü — gerekirse düzeltin)" if setup["voice"] else ""),
                          key=tkey, height=150, placeholder="Cevabınızı buraya yazın" if not setup["voice"] else
                          "Kayıt yaptığınızda konuşmanız buraya yazılacak")
    c1, c2, c3 = st.columns([2, 1, 1])
    send = c1.button("Cevabı gönder", type="primary", width="stretch", disabled=not answer.strip(), key=_k(f"send_{idx}"))
    skip = c2.button("Bu soruyu geç", width="stretch", key=_k(f"skip_{idx}"))
    end = c3.button("Mülakatı bitir", width="stretch", key=_k(f"end_{idx}"))
    if end:
        st.session_state[_k("idx")] = len(plan)
        st.rerun()
    if send or skip:
        text = "" if skip else answer.strip()
        item = {"question": q, "answer": text, "eval": None}
        if setup["feedback_each"]:
            with st.spinner("Mülakatçı cevabınızı değerlendiriyor..."):
                item["eval"] = iv.evaluate(q, text, {}, setup["field"], setup["title"], setup["cv_text"])
            fu = item["eval"].get("followup")
            if fu and q["stage"] in ("technical", "behavioral") and st.session_state[_k("followups")] < 2 and text:
                plan.insert(idx + 1, {**iv._q("followup", fu, q.get("expects", ""), "yapay zekâ"), "id": f"{q['id']}+"})
                st.session_state[_k("followups")] += 1
        results.append(item)
        st.session_state[_k("idx")] = idx + 1
        st.rerun()


def _finish():
    setup, results = st.session_state[_k("setup")], st.session_state[_k("results")]
    pending = [r for r in results if r.get("eval") is None]
    if pending:
        bar = st.progress(0.0, text="Cevaplarınız değerlendiriliyor...")
        for i, r in enumerate(pending, 1):
            r["eval"] = iv.evaluate(r["question"], r["answer"], {}, setup["field"], setup["title"], setup["cv_text"])
            bar.progress(i / len(pending), text=f"Değerlendiriliyor: {i}/{len(pending)}")
    rep = iv.report(results)
    _say(f"Teşekkürler {setup['name']}, görüşmemiz burada bitti. Değerlendirmeniz aşağıda.")
    _play(f"Teşekkürler {setup['name']}, görüşmemiz burada bitti.")
    if not st.session_state.get(_k("saved")) and results:
        iv.save_session(context.current(), {"title": setup["title"], "field": setup["field"], "report": rep,
                                            "results": results})
        st.session_state[_k("saved")] = True

    st.markdown("#### Mülakat karnesi")
    c = st.columns(4)
    c[0].metric("Genel puan", f"{rep['overall']}/100")
    for i, (stage, score) in enumerate(list(rep["by_stage"].items())[:3], 1):
        c[i].metric(stage, f"{score}/5")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Güçlü yanlarınız**")
        for s in rep["strengths"] or ["—"]:
            st.markdown(f"- {s}")
    with c2:
        st.markdown("**Bir sonraki mülakat için**")
        for s in rep["improve"] or ["—"]:
            st.markdown(f"- {s}")
    st.caption(f"Toplam {rep['words']} kelime konuştunuz; dolgu kelimesi ('yani', 'şey', 'eee'): {rep['fillers']}.")
    st.markdown("#### Soru soru")
    for r in results:
        ev = r["eval"]
        with st.expander(f"{ev['score']}/5 · {iv.STAGE_LABEL.get(r['question']['stage'], '')} — {r['question']['question'][:90]}"):
            st.markdown(f"**Cevabınız:** {r['answer'] or '_(geçildi)_'}")
            if r["question"].get("expects"):
                st.caption(f"Mülakatçının duymak istediği: {r['question']['expects']}")
            _feedback_card(ev)
    if st.button("Yeni mülakat", type="primary", icon=":material/refresh:"):
        _reset()
        st.rerun()


def page_interview():
    header("Mülakat Provası", "Yapay zekâ mülakatçı alanınıza, CV'nize ve seçtiğiniz ilana göre sorular sorar. Sesli "
                              "cevap verin; sonunda puanlı bir karne alın. Ses bilgisayarınızdan dışarı çıkmaz.")
    show_flash("iv")
    if st.session_state.get(_k("plan")) is None:
        _setup()
    else:
        if st.button("Mülakatı iptal et", key=_k("cancel"), icon=":material/close:"):
            _reset()
            st.rerun()
        _interview()
