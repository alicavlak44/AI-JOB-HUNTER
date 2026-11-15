"""Günlük / haftalık istatistikler.

Ayrı bir metrik tablosu yok: her şey jobs tablosundaki zaman damgalarından hesaplanır
(created_at = bulundu, analyzed_at = analiz edildi, cv_created_at = özel CV üretildi,
applied_at = başvuru onay ekranı görüldü). Hesaplar DataFrame üzerinde saf fonksiyonlardır.
"""
import re
from datetime import date, timedelta

import pandas as pd

from app.settings import (STATUS_APPLIED_VERIFIED, STATUS_APPLY_UNVERIFIED, STATUS_APPLY_FAILED,
                          STATUS_AT_APPLY_SCREEN)

EVENTS = {  # kolon → panelde görünen ad
    "created_at": "Bulunan ilan",
    "analyzed_at": "Analiz edilen",
    "cv_created_at": "Özel CV",
    "applied_at": "Başvuru (doğrulanmış)",
}
SCORE_BUCKETS = [(0, 39, "0-39 (Başvurma)"), (40, 64, "40-64 (Değerlendir)"), (65, 100, "65-100 (Başvur)")]


def parse_score(value):
    """'%62', '%87  (Altın ...' → 62 / 87; '-' veya boş → None."""
    m = re.search(r"%\s*(\d{1,3})", str(value or ""))
    return int(m.group(1)) if m else None


def _dates(df, col):
    """Gün başına yuvarlanmış zaman damgaları. Tamamen boş sütunlarda da güvenli (pandas 3)."""
    if col not in df:
        return pd.Series([], dtype="datetime64[ns]")
    return pd.to_datetime(df[col].astype("object"), errors="coerce").dt.normalize()


def period_counts(df, start, end):
    """[start, end] (dahil) aralığında her olayın sayısı."""
    out = {}
    for col, label in EVENTS.items():
        d = _dates(df, col)
        out[label] = int(((d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))).sum())
    return out


def summary(df, today=None):
    """Bugün, son 7 gün ve önceki 7 gün sayıları."""
    today = today or date.today()
    return {
        "today": period_counts(df, today, today),
        "week": period_counts(df, today - timedelta(days=6), today),
        "prev_week": period_counts(df, today - timedelta(days=13), today - timedelta(days=7)),
    }


def daily(df, today=None, days=14):
    """Son N günün günlük olay sayıları (satır = gün, sütun = olay)."""
    today = today or date.today()
    idx = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    data = {}
    for col, label in EVENTS.items():
        counts = _dates(df, col).value_counts()
        data[label] = [int(counts.get(pd.Timestamp(d), 0)) for d in idx]
    # Gerçek tarih indeksi: grafikte günler metin gibi alfabetik sıralanmasın
    out = pd.DataFrame(data, index=pd.DatetimeIndex([pd.Timestamp(d) for d in idx]))
    out.index.name = "Gün"
    return out


TR_MONTHS_SHORT = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def daily_chart(df, today=None, days=14):
    """Günlük olaylar için Türkçe etiketli, gün sırası korunan gruplu sütun grafiği (Altair)."""
    import altair as alt
    d = daily(df, today, days)
    labels = [f"{t.day} {TR_MONTHS_SHORT[t.month - 1]}" for t in d.index]
    long = (d.set_axis(labels).rename_axis("Gün").reset_index()
            .melt(id_vars="Gün", var_name="Olay", value_name="Adet"))
    return (alt.Chart(long).mark_bar()
            .encode(x=alt.X("Gün:N", sort=labels, title=None, axis=alt.Axis(labelAngle=-45)),
                    xOffset=alt.XOffset("Olay:N", sort=list(EVENTS.values())),
                    y=alt.Y("Adet:Q", title=None, axis=alt.Axis(tickMinStep=1)),
                    color=alt.Color("Olay:N", sort=list(EVENTS.values()), legend=alt.Legend(orient="bottom", title=None)),
                    tooltip=["Gün", "Olay", "Adet"])
            .properties(height=260))


def funnel(df):
    """Toplam huni: bulundu → analiz → 'Başvur' önerisi → özel CV → başvuru denendi → doğrulandı."""
    status = df.get("Durum", df.get("status", pd.Series(dtype="object")))
    rec = df.get("recommendation", pd.Series(dtype="object"))
    tried = {STATUS_AT_APPLY_SCREEN, STATUS_APPLIED_VERIFIED, STATUS_APPLY_UNVERIFIED, STATUS_APPLY_FAILED}
    return pd.DataFrame({"Adet": [
        len(df),
        int(_dates(df, "analyzed_at").notna().sum()),
        int((rec == "Başvur").sum()),
        int(_dates(df, "cv_created_at").notna().sum()),
        int(status.isin(tried).sum()),
        int(_dates(df, "applied_at").notna().sum()),
    ]}, index=["1 · Bulunan", "2 · Analiz edilen", "3 · 'Başvur' önerilen", "4 · Özel CV üretilen",
               "5 · Başvuru denenen", "6 · Başvuru doğrulanan"])  # numara: grafik sırayı korusun


def score_distribution(df):
    col = "ATS Uyum" if "ATS Uyum" in df else "ats_score"
    scores = df[col].map(parse_score).dropna() if col in df else pd.Series(dtype=float)
    return pd.DataFrame({"İlan": [int(((scores >= lo) & (scores <= hi)).sum()) for lo, hi, _ in SCORE_BUCKETS]},
                        index=[label for *_, label in SCORE_BUCKETS])


def sentence(counts, label):
    """'Bugün 15 ilan bulundu, 5'i analiz edildi, ...' özeti."""
    parts = [f"{counts['Bulunan ilan']} ilan bulundu",
             f"{counts['Analiz edilen']} analiz yapıldı",
             f"{counts['Özel CV']} özel CV üretildi",
             f"{counts['Başvuru (doğrulanmış)']} başvuru doğrulandı"]
    return f"{label} " + ", ".join(parts) + "."
