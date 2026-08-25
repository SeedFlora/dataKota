TARGET_CLASSES = [
    "Dinas Bina Marga",
    "Satuan Polisi Pamong Praja",
    "Dinas Perhubungan",
    "Kelurahan",
    "Dinas Pertamanan dan Hutan",
    "Dinas Sumber Daya Air",
    "Dinas Cipta Karya, Tata Ruang, dan Pertanahan",
    "Badan Pembinaan Badan Usaha Milik Daerah",
    "Instansi lain",
]

LABEL2ID = {lbl: i for i, lbl in enumerate(TARGET_CLASSES)}
ID2LABEL = {i: lbl for lbl, i in LABEL2ID.items()}


def normalize_skpd(s: str) -> str:
    """Map raw label_skpd → one of TARGET_CLASSES. First match wins."""
    s = str(s).upper()
    if any(
        k in s
        for k in (
            "PERHUBUNGAN",
            "PERPARKIRAN",
            "PENGENDALIAN LALU LINTAS",
            "LALU LINTAS JALAN",
        )
    ):
        return "Dinas Perhubungan"
    if "BINA MARGA" in s:
        return "Dinas Bina Marga"
    if "POLISI PAMONG PRAJA" in s or "SATPOL" in s:
        return "Satuan Polisi Pamong Praja"
    if "KELURAHAN" in s:
        return "Kelurahan"
    if "PERTAMANAN" in s or "HUTAN" in s:
        return "Dinas Pertamanan dan Hutan"
    if "SUMBER DAYA AIR" in s:
        return "Dinas Sumber Daya Air"
    if "CIPTA KARYA" in s or "TATA RUANG" in s or "PERTANAHAN" in s:
        return "Dinas Cipta Karya, Tata Ruang, dan Pertanahan"
    if (
        "BUMD" in s
        or "BADAN USAHA MILIK DAERAH" in s
        or s.startswith(("PT ", "PERUMDA"))
    ):
        return "Badan Pembinaan Badan Usaha Milik Daerah"
    return "Instansi lain"
