"""İlan ↔ CV eşleştirmesinin ölçülebilir kısmı (LLM'siz).

- Beceri eşleşmesi: sözlükteki teknik terimler ilanda ve CV'de kelime sınırıyla aranır.
- Deneyim şartı: "en az 5 yıl", "3–5 yıl deneyimli", "minimum 4 years" gibi kalıplar.
- Bölüm şartı: ilanda sayılan bölüm aileleri ile CV'deki eğitim aileleri karşılaştırılır.
- Ek şartlar: ehliyet, askerlik, seyahat — documents/profile.json'dan kontrol edilir.
"""
import re
from dataclasses import dataclass, field, asdict

from ai_engine.cv_profile import CVProfile, field_families, tr_lower

# Kanonik ad -> eş anlamlılar (küçük harf). Eş anlamlılar kelime sınırıyla aranır.
SKILLS = {
    # Ağ
    "Cisco": ["cisco"], "Ruijie": ["ruijie"], "Huawei": ["huawei"], "HP/Aruba": ["procurve", "aruba", "hpe aruba"],
    "Juniper": ["juniper"], "MikroTik": ["mikrotik"],
    "VLAN": ["vlan"], "LACP": ["lacp"], "STP": ["stp", "spanning tree"], "Trunking": ["trunk", "trunking"],
    "BGP": ["bgp"], "OSPF": ["ospf"], "EIGRP": ["eigrp"], "VRF": ["vrf"], "HSRP/VRRP": ["hsrp", "vrrp"],
    "MPLS": ["mpls"], "SD-WAN": ["sd-wan", "sdwan"], "NAT": ["nat"], "TCP/IP": ["tcp/ip", "tcp-ip"],
    "DNS": ["dns"], "DHCP": ["dhcp"], "VPN": ["vpn", "ipsec", "ssl vpn"], "Kablosuz Ağ": ["wi-fi", "wifi", "kablosuz", "wireless", "wlan"],
    "Load Balancer": ["load balancer", "yük dengeleyici", "f5"], "Proxy": ["proxy"],
    "Fiber/Kablolama": ["fiber", "cat6", "cat6a", "patch panel", "kablolama", "cabling"],
    "SIP": ["sip", "voip", "sip trunking"],
    # Güvenlik
    "Firewall": ["firewall", "güvenlik duvarı"], "Fortinet": ["fortinet", "fortigate"], "Palo Alto": ["palo alto"],
    "Check Point": ["check point", "checkpoint"], "Sophos": ["sophos"], "Labris": ["labris"],
    "IDS/IPS": ["ids/ips", "ips/ids", "ids", "ips"], "WAF": ["waf"], "SIEM": ["siem", "qradar", "splunk"],
    "Log Analizi": ["log analizi", "log analysis", "log yönetimi"], "Web Filtering": ["web filtering", "web filtreleme"],
    # Sistem
    "Windows Server": ["windows server"], "Active Directory": ["active directory"], "GPO": ["gpo", "group policy"],
    "Entra ID/Azure AD": ["entra id", "azure ad", "azure active directory"], "Microsoft 365": ["microsoft 365", "office 365", "m365", "o365"],
    "Exchange": ["exchange"], "SharePoint": ["sharepoint"],
    "Linux": ["linux", "debian", "ubuntu", "centos", "rhel", "red hat"], "Nginx": ["nginx"], "Apache": ["apache"], "IIS": ["iis"],
    # Sanallaştırma / depolama
    "VMware": ["vmware", "esxi", "vsphere", "vcenter", "mware"], "Proxmox": ["proxmox"], "Hyper-V": ["hyper-v"],
    "NAS": ["nas", "qnap", "synology"], "SAN": ["san"], "iSCSI": ["iscsi"], "Yedekleme": ["backup", "yedekleme", "veeam"],
    # DevOps / bulut
    "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s", "openshift"], "Ansible": ["ansible"], "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "jenkins", "gitlab ci", "github actions", "argocd", "pipeline"], "Git": ["git"],
    "JFrog Artifactory": ["artifactory", "jfrog"], "AWS": ["aws", "amazon web services"], "Azure": ["azure"], "GCP": ["gcp", "google cloud"],
    # İzleme
    "Zabbix": ["zabbix"], "PRTG": ["prtg"], "Nagios": ["nagios"], "Grafana": ["grafana"], "Prometheus": ["prometheus"], "ELK": ["elk", "elasticsearch", "kibana"],
    # Yazılım / veritabanı
    "Python": ["python"], "C#": ["c#"], "Java": ["java"], "PowerShell": ["powershell"], "Bash": ["bash", "shell script"],
    "SQL": ["sql"], "MySQL": ["mysql"], "PostgreSQL": ["postgresql", "postgres"], "MSSQL": ["mssql", "sql server"], "Oracle": ["oracle"],
    # Süreç / araç
    "ITIL": ["itil"], "Jira": ["jira"], "Confluence": ["confluence"], "DOORS": ["doors"], "SysML": ["sysml"],
    "ERP": ["erp", "sap", "odoo", "netsis"],
    # Sertifika
    "CCNA": ["ccna"], "CCNP": ["ccnp"], "MCSA": ["mcsa"], "RHCE/RHCSA": ["rhce", "rhcsa"], "CompTIA": ["comptia", "security+", "network+"],
    # Veri merkezi donanım
    "UPS/PDU": ["ups", "pdu", "redresör"], "Sunucu Donanımı": ["hpe", "dell", "cisco ucs", "rack"],
    # Dil
    "İngilizce": ["ingilizce", "İngilizce", "english"],
}
# Genel şartlar: listelenir ama beceri kapsamına sayılmaz (neredeyse her ilanda geçer,
# alakasız ilanlarda bile kapsamı yapay olarak yükseltiyordu).
NON_TECHNICAL = {"İngilizce"}

# İlandaki şu kelimeler o becerinin "tercihen" (zorunlu değil) olduğunu gösterir
PREFERRED_MARKERS = ("tercihen", "tercih sebebi", "artı", "plus", "nice to have", "preferred", "is a plus")

# Türkçe metinlerde sıradan kelimeyle karışabilen kısaltmalar sadece BÜYÜK harfle aranır
# (ör. "Tic. ve San. A.Ş." içindeki "San").
CASE_SENSITIVE = {"SAN"}

_PATTERNS = {
    canon: re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(a.upper() if canon in CASE_SENSITIVE else a) for a in aliases) + r")(?![\w-])",
        0 if canon in CASE_SENSITIVE else re.IGNORECASE,
    )
    for canon, aliases in SKILLS.items()
}


def normalize(text):
    text = (text or "").replace(" ", " ")
    text = re.sub(r"\s*-\s*", "-", text)       # "Hyper - V" -> "Hyper-V", "Site - to - Site"
    text = re.sub(r"\s*/\s*", "/", text)       # "IDS / IPS" -> "IDS/IPS"
    return re.sub(r"\s+", " ", text)


# Sadece BÜYÜK harfle yazıldığında anlamlı olan ek kısaltmalar (ör. "AD" = Active Directory)
CASE_SENSITIVE_ALIASES = {"Active Directory": ["AD"], "Entra ID/Azure AD": ["AAD"]}
_CS_PATTERNS = {
    canon: re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, al)) + r")(?![\w-])")
    for canon, al in CASE_SENSITIVE_ALIASES.items()
}


def find_skills(text):
    t = normalize(text)
    found = {canon for canon, pat in _PATTERNS.items() if pat.search(t)}
    found |= {canon for canon, pat in _CS_PATTERNS.items() if pat.search(t)}
    return found


def _preferred_skills(job_text):
    """'Tercihen ...' cümlelerinde geçen beceriler (cümle = virgül/nokta ile ayrılan parça)."""
    t = normalize(job_text)
    pref = set()
    for chunk in re.split(r"[.;\n•]|,\s(?=[A-ZÇĞİÖŞÜ])", t):
        if any(m in tr_lower(chunk) for m in PREFERRED_MARKERS):
            pref |= find_skills(chunk)
    return pref


_YEARS_PATTERNS = [
    r"(?:en az|minimum|min\.?|at least)\s*(\d{1,2})\s*(?:\+)?\s*(?:yıl|sene|years?)",
    r"(\d{1,2})\s*\+\s*(?:yıl|sene|years?)",
    r"(\d{1,2})\s*(?:yıl|sene|years?)(?:lık|lik)?\s*(?:deneyim|tecrübe|experience)",
]


def required_years(job_text):
    t = tr_lower(normalize(job_text))
    # "3–5 yıl" / "3-5 years" aralıklarında alt sınır esas alınır
    t = re.sub(r"(\d{1,2})\s*[–—-]\s*\d{1,2}(?=\s*(?:yıl|sene|years?))", r"\1", t)
    found = []
    for pat in _YEARS_PATTERNS:
        found += [int(x) for x in re.findall(pat, t)]
    found = [y for y in found if 0 < y <= 15]
    return max(found) if found else None


def _degree_requirement(job_text):
    """(aileler, esnek_mi): ilanda sayılan bölüm aileleri; 'ilgili/benzeri bölüm' ifadesi varsa esnek."""
    t = tr_lower(normalize(job_text))
    if not re.search(r"mezun|bölüm|degree|bachelor|lisans|graduate", t):
        return set(), True
    # Sadece bölüm/mezuniyet geçen cümlelere bak (şirket tanıtımındaki "elektronik" vb. sayılmasın)
    sentences = [s for s in re.split(r"[.;\n•]", t) if re.search(r"mezun|bölüm|degree|bachelor|lisans|graduate|fakülte", s)]
    fams = field_families(" ".join(sentences))
    flexible = bool(re.search(r"ilgili|benzeri|related|equivalent|veya dengi|vb\.", " ".join(sentences)))
    return fams, flexible


_EXTRA_REQS = {
    "driving_license": (r"ehliyet|sürücü belgesi|driving licen[cs]e", "B sınıfı ehliyet"),
    "military_done": (r"askerlik|military service", "Askerlik durumu"),
    "can_travel": (r"seyahat engeli|şehir dışı|travel", "Seyahat / şehir dışı çalışma"),
    "night_shift_ok": (r"gece çalış|vardiya|shift", "Gece / vardiyalı çalışma"),
}


@dataclass
class MatchFacts:
    job_skills: list = field(default_factory=list)
    required_skills: list = field(default_factory=list)
    preferred_skills: list = field(default_factory=list)
    matched_required: list = field(default_factory=list)
    missing_required: list = field(default_factory=list)
    matched_preferred: list = field(default_factory=list)
    missing_preferred: list = field(default_factory=list)
    skill_coverage: float | None = None       # 0-1, zorunlu becerilerde; None = ilanda yeterli teknik terim yok
    cv_years: float = 0.0
    required_years: int | None = None
    experience_ok: bool | None = None
    degree_families_required: list = field(default_factory=list)
    degree_match: bool | None = None          # None = ilanda bölüm şartı yok
    degree_flexible: bool = True
    extra_checks: dict = field(default_factory=dict)  # {"B sınıfı ehliyet": True/False/None(bilinmiyor)}

    def to_dict(self):
        return asdict(self)

    def as_prompt_text(self):
        """LLM'e verilecek, çelişmemesi gereken doğrulanmış bilgiler."""
        lines = [f"- Adayın toplam profesyonel deneyimi (stajlar hariç): {self.cv_years} yıl"]
        if self.required_years:
            lines.append(f"- İlanın istediği deneyim: en az {self.required_years} yıl → "
                         f"{'KARŞILANIYOR' if self.experience_ok else 'KARŞILANMIYOR'}")
        if self.matched_required or self.matched_preferred:
            lines.append(f"- CV'de AÇIKÇA bulunan ve ilanda geçen beceriler: {', '.join(self.matched_required + self.matched_preferred)}")
        if self.missing_required:
            lines.append(f"- İlanda geçen ama CV'de bulunmayan beceriler: {', '.join(self.missing_required)}")
        if self.missing_preferred:
            lines.append(f"- 'Tercihen' istenen ama CV'de olmayanlar (zorunlu değil): {', '.join(self.missing_preferred)}")
        if self.degree_match is not None:
            lines.append(f"- Bölüm şartı: {'uyumlu' if self.degree_match else 'UYUMSUZ'}"
                         f"{' (ilan ilgili bölümleri de kabul ediyor)' if self.degree_flexible else ''}")
        for name, val in self.extra_checks.items():
            lines.append(f"- {name}: {'var' if val else 'yok' if val is False else 'BİLİNMİYOR (CV/profilde yazmıyor, iddia etme)'}")
        return "\n".join(lines)


def match(job_text, cv_text, profile: CVProfile):
    job_sk = find_skills(job_text)
    cv_sk = find_skills(cv_text)
    pref = _preferred_skills(job_text) & job_sk
    req = job_sk - pref
    f = MatchFacts(
        job_skills=sorted(job_sk),
        required_skills=sorted(req),
        preferred_skills=sorted(pref),
        matched_required=sorted(req & cv_sk),
        missing_required=sorted(req - cv_sk),
        matched_preferred=sorted(pref & cv_sk),
        missing_preferred=sorted(pref - cv_sk),
        cv_years=profile.professional_years,
    )
    tech_req = req - NON_TECHNICAL
    if len(tech_req) >= 3:
        f.skill_coverage = round(len(tech_req & cv_sk) / len(tech_req), 2)

    f.required_years = required_years(job_text)
    if f.required_years:
        f.experience_ok = profile.professional_years >= f.required_years

    fams, flexible = _degree_requirement(job_text)
    if fams:
        f.degree_families_required = sorted(fams)
        f.degree_match = bool(fams & profile.education_families)
        f.degree_flexible = flexible

    low = normalize(job_text).lower()
    for key, (pat, label) in _EXTRA_REQS.items():
        if re.search(pat, low):
            f.extra_checks[label] = profile.extra.get(key)  # None = bilinmiyor
    return f


# ------------------------------------------------ Yapay zeka değerlendirmesinden puan
# Model tek bir 0-100 sayı verince hep aynı birkaç değeri (ör. 42, 15) seçiyordu.
# Bunun yerine ana şartları tek tek işaretliyor ve alan uyumunu bir sınıfla seçiyor;
# puanı bu somut kararlardan kod hesaplıyor.
FIELD_FIT_LABELS = {
    0: "tamamen farklı meslek (ör. İK, satış, muhasebe)",
    1: "uzak ilgili (ör. donanım/savunma sistem mühendisliği, yazılım geliştirme)",
    2: "aynı sektör, farklı rol (ör. DevOps, veri merkezi saha)",
    3: "yakın rol (ör. sistem yöneticisi ↔ ağ mühendisi)",
    4: "aynı rol",
}
_STATUS_POINTS = {"var": 1.0, "kısmen": 0.5, "yok": 0.0}


def _norm_evidence(text):
    return re.sub(r"\s+", " ", normalize(text or "").lower()).strip(" .,;:\"'")


_PROFILE_REQ_RE = re.compile(
    "|".join(pat for pat, _ in _EXTRA_REQS.values()) + r"|yurt ?(?:içi|dışı)|seyahat|askerlik|ehliyet",
    re.IGNORECASE)


def drop_profile_requirements(requirements):
    """Ehliyet, askerlik, seyahat gibi CV'de genelde yazmayan şartları puan dışı bırakır.
    Bunlar ayrıca 'bilinmeyen şartlar' olarak gösteriliyor; model 'yok' deyince haksız puan düşüyordu."""
    kept = [r for r in requirements if not _PROFILE_REQ_RE.search(r.get("item", ""))]
    return kept, [r.get("item", "") for r in requirements if r not in kept]


def verify_requirements(requirements, cv_text):
    """Modelin 'var' dediği ama kanıtı CV'de geçmeyen şartları 'kısmen'e düşürür.
    Dönüş: (düzeltilmiş liste, düşürülen şart adları)."""
    cv_low = _norm_evidence(cv_text)
    cv_sk = find_skills(cv_text)
    fixed, downgraded = [], []
    for r in requirements:
        r = dict(r)
        status = (r.get("status") or "yok").strip().lower()
        status = status if status in _STATUS_POINTS else "yok"
        if status == "var":
            ev = _norm_evidence(r.get("evidence"))
            ev_sk = find_skills(r.get("evidence") or "")
            ok = bool(ev) and (ev in cv_low or (ev_sk and ev_sk <= cv_sk))
            if not ok:
                status = "kısmen"
                downgraded.append(r.get("item", "?"))
        r["status"] = status
        fixed.append(r)
    return fixed, downgraded


def rubric_score(requirements, field_fit):
    """Şart listesi + alan uyumu → 0-100. Şartların yarısı + alan uyumunun yarısı.
    Alan tamamen farklıysa (0) şartlardan gelen puan da yarıya iner."""
    field_fit = max(0, min(4, int(field_fit)))
    if requirements:
        req_part = sum(_STATUS_POINTS[r["status"]] for r in requirements) / len(requirements)
    else:
        req_part = field_fit / 4
    if field_fit == 0:
        req_part *= 0.5
    return int(round(50 * req_part + 50 * field_fit / 4))


def blended_score(llm_score, facts: MatchFacts):
    """LLM puanını ölçülebilir gerçeklerle birleştirir ve sert şartlarda tavan uygular.
    Dönüş: (puan, açıklama listesi)."""
    notes = []
    if facts.skill_coverage is None:
        score = llm_score
        notes.append("İlanda yeterli teknik terim yok; puan büyük ölçüde yapay zeka değerlendirmesi.")
    else:
        if facts.required_years:
            exp = min(1.0, facts.cv_years / facts.required_years)
        else:
            exp = 1.0
        score = 0.5 * llm_score + 0.35 * facts.skill_coverage * 100 + 0.15 * exp * 100
        notes.append(f"Beceri kapsamı %{round(facts.skill_coverage * 100)}, yapay zeka puanı %{llm_score}.")

    if facts.required_years and facts.cv_years < facts.required_years - 1:
        score = min(score, 60)
        notes.append(f"Deneyim şartı ({facts.required_years} yıl) belirgin şekilde karşılanmıyor → en fazla %60.")
    if facts.degree_match is False and not facts.degree_flexible:
        score = min(score, 35)
        notes.append("Zorunlu bölüm şartı karşılanmıyor → en fazla %35 (Başvurma).")
    elif facts.degree_match is False:
        score = min(score, 70)
        notes.append("Bölüm doğrudan uyumlu değil (ilan ilgili bölümleri kabul ediyor) → en fazla %70.")
    return int(round(score)), notes


def recommendation_for(score):
    return "Başvur" if score >= 65 else "Değerlendir" if score >= 40 else "Başvurma"
