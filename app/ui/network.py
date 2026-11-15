"""🤝 İK Ağı: İK yöneticilerini bul → seç (veya tek tık) → davet. Bağlantılarınız ve davetlileriniz hiç listelenmez."""
import pandas as pd
import streamlit as st

from app import account, guard
from app.settings import MAX_DAILY_INVITES
from app.ui.common import header, msg_kind
from browser.automator import find_hr_people, invite_people


def page_network():
    header("🤝 İK Ağı", "Şehirdeki İK yöneticilerine notsuz bağlantı daveti. Ağınızdaki ve davet ettiğiniz kişiler hiç gelmez.")
    inv = guard.status("LinkedIn")["bağlantı daveti"]
    left = max(0, MAX_DAILY_INVITES - int(inv["bugün"].split("/")[0]))
    kc = account.known_counts()
    c = st.columns(3)
    c[0].metric("Bugün kalan davet hakkı", left, help=f"Günlük {MAX_DAILY_INVITES}, haftalık sınır: {inv['hafta']}")
    c[1].metric("Atlanacak bağlantınız", kc.get("connection", 0), help="Hesabınızdan senkronlandı")
    c[2].metric("Bekleyen davetiniz", kc.get("pending_invite", 0))

    with st.container(border=True):
        n1, n2, n3 = st.columns([2, 1, 1])
        q = n1.text_input("Unvan", value="İnsan Kaynakları Müdürü")
        city = n2.text_input("Şehir", value="Ankara", key="hr_city")
        limit = n3.number_input("En fazla kişi", 1, 30, max(1, min(10, left or 10)))
        b1, b2 = st.columns(2)
        if b1.button("🔎 Bul ve listele", width="stretch"):
            with st.spinner("LinkedIn'de aranıyor (bot tarayıcısı açılır)..."):
                found = find_hr_people(q, city, limit=int(limit))
            st.session_state["hr_people"] = found["people"]
            st.session_state["hr_msg"] = found["error"] or f"✅ {len(found['people'])} yeni İK yöneticisi bulundu."
            st.rerun()
        if b2.button(f"⚡ Tek tıkla: bul + {min(int(limit), left)} kişiye davet", type="primary", width="stretch",
                     disabled=left == 0):
            with st.status("Otomatik davet...", expanded=True) as box:
                found = find_hr_people(q, city, limit=min(int(limit), left))
                if found["error"]:
                    box.write(found["error"])
                box.write(f"{len(found['people'])} uygun kişi; davetler gönderiliyor...")
                res = invite_people(found["people"], on_progress=box.write) if found["people"] else []
                box.update(label="Bitti", state="complete")
            st.session_state.update(hr_invite_results=res, hr_people=[], hr_msg=found["error"])
            st.rerun()
    msg = st.session_state.get("hr_msg")
    if msg:
        getattr(st, msg_kind(msg))(msg)

    people = st.session_state.get("hr_people") or []
    if people:
        sig = hash(tuple(p["url"] for p in people))
        all_on = st.checkbox(f"✅ Tümünü seç ({len(people)} kişi)", key=f"hr_all_{sig}")
        table = pd.DataFrame([{"Onay": all_on, "Ad": p["name"], "Unvan": p["headline"], "Konum": p["location"],
                               "Profil": p["url"]} for p in people])
        edited = st.data_editor(table, hide_index=True, width="stretch", key=f"hr_table_{sig}_{all_on}",
                                disabled=["Ad", "Unvan", "Konum", "Profil"],
                                column_config={"Profil": st.column_config.LinkColumn("Profil", display_text="Aç")})
        chosen = [p for p, ok in zip(people, edited["Onay"].tolist()) if ok]
        if len(chosen) > left:
            st.warning(f"Bugün {left} hak kaldı; ilk {left} kişiye gönderilir, kalanlar ertelenir.")
        if st.button(f"🤝 Seçilen {len(chosen)} kişiye davet gönder", type="primary", disabled=not chosen, width="stretch"):
            with st.status(f"{len(chosen)} kişiye davet...", expanded=True) as box:
                res = invite_people(chosen, on_progress=box.write)
                box.update(label="Bitti", state="complete")
            sent = {r.get("Profil") for r in res if "gönderildi" in r["Sonuç"]}
            st.session_state.update(hr_people=[p for p in people if p["url"] not in sent], hr_invite_results=res, hr_msg=None)
            st.rerun()

    if st.session_state.get("hr_invite_results"):
        st.subheader("📋 Son davet sonucu")
        st.dataframe(pd.DataFrame(st.session_state["hr_invite_results"]), hide_index=True, width="stretch",
                     column_config={"Profil": st.column_config.LinkColumn("Profil", display_text="Aç")})
