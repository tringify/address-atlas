"""Build sources/postal/rules.json from libaddressinput countryinfo.txt plus the
per-country decisions below (checked against UPU addressing PDFs, fetched 2026-11-01).

Run: python3 -I sources/postal/build_rules.py
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
INFO = ROOT / "sources/libaddressinput/countryinfo.txt"
OUT = ROOT / "sources/postal/rules.json"

UPU = "https://www.upu.int/UPU/media/upu/PostalEntitiesFiles/addressingUnit/{}En.pdf"
STRIP = " -."

# Source document (UPU ISO3 file name) per country; territories point at the
# parent operator's document when their own UPU page says "see <parent>".
ISO3 = dict(AC="shn", AD="and", AF="afg", AI="aia", AL="alb", AM="arm", AR="arg", AS="usa", AT="aut", AU="aus",
            AX="ala", AZ="aze", BA="bih", BB="brb", BD="bgd", BE="bel", BG="bgr", BH="bhr", BL="blm", BM="bmu",
            BN="brn", BR="bra", BT="btn", BY="blr", CA="can", CC="aus", CH="che", CK="cok", CL="chl", CN="chn",
            CO="col", CR="cri", CV="cpv", CX="aus", CY="cyp", CZ="cze", DE="deu", DK="dnk", DO="dom", DZ="dza",
            EC="ecu", EE="est", EG="egy", EH="mar", ES="esp", ET="eth", FI="fin", FK="flk", FM="usa", FO="fro",
            FR="fra", GB="gbr", GE="geo", GF="guf", GG="ggy", GI="gib", GL="dnk", GN="gin", GP="glp", GR="grc",
            GS="sgs", GT="gtm", GU="usa", GW="gnb", HM="hmd", HN="hnd", HR="hrv", HT="hti", HU="hun", ID="idn",
            IL="isr", IM="gbr", IN="ind", IO="iot", IQ="irq", IR="irn", IS="isl", IT="ita", JE="gbr", JO="jor",
            JP="jpn", KE="ken", KG="kgz", KH="khm", KR="kor", KW="kwt", KY="cym", KZ="kaz", LA="lao", LB="lbn",
            LI="che", LK="lka", LR="lbr", LS="lso", LT="ltu", LU="lux", LV="lva", MA="mar", MC="mco", MD="mda",
            ME="mne", MF="maf", MG="mdg", MH="usa", MK="mkd", MM="mmr", MN="mng", MP="usa", MQ="mtq", MT="mlt",
            MU="mus", MV="mdv", MX="mex", MY="mys", MZ="moz", NC="ncl", NE="ner", NF="nfk", NG="nga", NI="nic",
            NL="nld", NO="nor", NP="npl", NZ="nzl", OM="omn", PE="per", PF="pyf", PG="png", PH="phl", PK="pak",
            PL="pol", PM="spm", PN="pcn", PR="usa", PT="prt", PW="usa", PY="pry", RE="reu", RO="rou", RS="srb",
            RU="rus", SA="sau", SE="swe", SG="sgp", SH="shn", SI="svn", SJ="nor", SK="svk", SM="smr", SN="sen",
            SO="som", SV="slv", SZ="swz", TA="shn", TC="tca", TH="tha", TJ="tjk", TM="tkm", TN="tun", TR="tur",
            TW=None, TZ="tza", UA="ukr", US="usa", UY="ury", UZ="uzb", VA="vat", VC="vct", VE="ven", VG="vgb",
            VI="usa", VN="vnm", WF="wlf", XK=None, YT="myt", ZA="zaf", ZM="zmb")
OTHER_SOURCE = {
    "TW": "https://www.post.gov.tw/post/internet/Postal/index.jsp?ID=207",
    "XK": "https://www.postakosoves.com/",
}

SPACE_AFTER_3 = [{"after": 3, "char": " "}]
UK_STYLE = [
    {"before_last": 3, "char": " ", "only_when_match": "^(?!BFPO)"},
    {"after": 4, "char": " ", "only_when_match": "^BFPO"},
]
ZIP4 = [{"after": 5, "char": "-", "only_when_length": [9]}]

# CC: insert ops, prefix, confidence, notes, extra examples (typed -> expected), invalid zipex reasons
R = {}


def rule(cc, insert=(), prefix=None, low=False, notes="", extra=None, invalid=None, deviation=None):
    R[cc] = dict(insert=list(insert), prefix=prefix, low=low, notes=notes, extra=extra or {},
                 invalid=invalid or {}, deviation=deviation or {})


def pfx(text, status, scope):
    return {"text": text, "status": status, "scope": scope, "strip_if_typed": True}


# --- separators ---------------------------------------------------------------
for cc in ("GB", "GG", "JE", "IM", "GI", "AC", "SH", "TA", "FK", "GS", "IO", "PN", "TC"):
    rule(cc, UK_STYLE, notes="UK-style postcode: one space before the inward code (last 3 characters).")
R["GB"]["notes"] += " BFPO codes are written 'BFPO <n>' (space after BFPO)."
R["GB"]["invalid"] = {"RH6 OHP": "letter O where the inward code needs digit 0; the correct 'RH6 0HP' is also listed"}
R["GB"]["notes"] += " zipex BS18 8HF is a retired district but still matches the pattern."
R["JE"]["notes"] += " UPU Jersey page: 'See United Kingdom'; source is the GB document."
R["IM"]["notes"] += " UPU Isle of Man page: 'See United Kingdom' (example IM99 1PS); source is the GB document."
R["GI"]["notes"] += " UPU: single generic code GX11 1AA."
for cc in ("SE", "GR", "CZ", "SK"):
    rule(cc, SPACE_AFTER_3, notes="UPU: 5 digits with a space between 3rd and 4th digits.")
R["SE"]["deviation"] = {z: {"canonical": z[:3] + " " + z[3:],
                            "reason": "zipex written without the space; UPU/PostNord form has a space after the 3rd digit"}
                        for z in ("11455", "12345", "10500")}
R["CZ"]["notes"] += " Two spaces between code and locality on mail (not part of the code)."
rule("CA", SPACE_AFTER_3, notes="UPU/Canada Post: ANA NAN with a space between 3rd and 4th characters.")
rule("NL", [{"after": 4, "char": " "}], notes="UPU/PostNL: space between the digits and the 2 capital letters (1234 AB).")
rule("MT", SPACE_AFTER_3, notes="UPU: 'One space between letters and digits' (ZTN 1073). Old 2-digit codes (NXR 01) in zipex predate the 2007 4-digit scheme but follow the same spacing.")
rule("BM", [{"after": 2, "char": " "}], notes="UPU: 4 alphanumeric characters with a space between the 2nd and 3rd.")
rule("JP", [{"after": 3, "char": "-"}], notes="UPU: hyphen between 3rd and 4th digits.")
rule("BR", [{"after": 5, "char": "-"}], notes="UPU: hyphen between 5th and 6th digits (CEP).")
rule("PL", [{"after": 2, "char": "-"}], notes="UPU: dash between 2nd and 3rd digits.")
rule("PT", [{"after": 4, "char": "-"}], notes="UPU: dash between 4th and 5th digits.")
rule("KY", [{"after": 3, "char": "-"}], notes="UPU: 'KY' + island digit, hyphen, 4 digits (KY1-1100). Letters are part of the code.")
rule("LV", [{"after": 2, "char": "-"}], notes="UPU: 'LV-' + 4 digits; the LV- is part of the libaddressinput pattern, so it is in the canonical form.")
rule("US", ZIP4, notes="UPU/USPS: ZIP+4 written with a hyphen between 5th and 6th digits; 5-digit ZIP has no separator.")
for cc in ("PR", "VI", "GU", "FM", "MH", "MP"):
    rule(cc, ZIP4, notes="US territory using USPS ZIP codes; format from the USA UPU document (territory UPU page only gives the ZIP range).")
for cc in ("AS", "PW"):
    rule(cc, notes="US territory using USPS ZIP codes; pattern allows only the 5-digit ZIP, so no ZIP+4 hyphen.")

# --- low confidence: separator rule not confirmed by the official source -------
rule("KR", [{"after": 3, "char": "-"}], low=True,
     notes="Pattern/zipex are the pre-2015 6-digit 'NNN-NNN' format. UPU Korea document: since 1 Aug 2015 the code is 5 digits with no separator (e.g. 42007). The hyphen rule reproduces the old format but is not confirmed by the current official source; codes matching this pattern are obsolete.")
rule("LB", [{"after": 4, "char": " ", "only_when_length": [8]}], low=True,
     notes="UPU Lebanon document has no postcode section. 8-digit codes are written NNNN NNNN in zipex and in secondary sources; 4-digit codes have no separator. Not confirmed from LibanPost.")
rule("CR", [{"after": 3, "char": "-", "only_when_length": [7]}], low=True,
     notes="UPU: 5 digits, no separator. The pattern also allows 4 digits and a 7-digit 'NNN-NNNN' form, whose hyphen rule is not confirmed by the official source.")
rule("PE", [{"after": 4, "char": " ", "only_when_match": "^LIMA"},
            {"after": 6, "char": " ", "only_when_match": "^CALLAO"}], low=True,
     notes="Pattern/zipex use the old 'LIMA nn' / 'CALLAO n' zones; the space follows the zipex. UPU Peru document: current code is 5 digits with no separator (e.g. 15074), which this rule leaves unchanged.")
rule("SV", [{"after": 2, "char": " "}], low=True,
     notes="Pattern requires 'CP ' + 4 digits; UPU El Salvador document shows 4 digits only (1120), without CP. The 'CP ' form is kept because the pattern requires it, but it is not confirmed officially.")
rule("IR", low=True,
     deviation={"11936-12345": {"canonical": "1193612345",
                                "reason": "UPU Iran document writes the 10-digit code with no separator (1619614153); zipex has a hyphen after the 5th digit"}},
     notes="Canonical form follows UPU (10 digits, no separator). Pattern allows an optional hyphen; no official source for the hyphen was found.")
rule("TW", low=True,
     notes="UPU Taiwan document not available. Pattern allows 3 or 5 digits with no separator, as in zipex. Chunghwa Post now uses 3+3 (6-digit) codes, which this pattern does not accept; the separator for 3+3 is not given on the Chunghwa Post page checked.")
rule("XK", low=True,
     notes="No UPU document for Kosovo. 5 digits, no separator as in zipex and Kosovo institutional addresses (e.g. 10000 Prishtinë); not confirmed from Posta e Kosovës.")

# --- digits / fixed codes without separator: pattern conflicts with source ------
for cc, n in {
    "AF": "UPU: 6 digits (100208); pattern/zipex are 4 digits.",
    "AM": "UPU: 4 digits (0002); zipex 375010 is the old Soviet-era 6-digit form, allowed by the pattern '(37)?'.",
    "EG": "UPU: 7 digits; pattern/zipex are 5 digits.",
    "KH": "UPU: 6 digits (120209); pattern/zipex are 5 digits.",
    "KZ": "UPU: new 7-character alphanumeric code (Z00Y5M3); pattern/zipex are the old 6 digits.",
    "MM": "UPU: 7 digits; pattern/zipex are 5 digits.",
    "PY": "UPU: 6 digits (001218); pattern/zipex are 4 digits.",
    "SO": "UPU: region abbreviation + space + 5 digits (JH 09010); pattern/zipex have only the 5 digits, so no region prefix is added.",
    "TZ": "UPU: 5 digits (11101); pattern/zipex are 4 digits.",
    "VN": "UPU: 5 digits; pattern/zipex are 6 digits.",
    "HN": "UPU: 2 letters + 4 digits (CM1102); pattern is 5 digits with no zipex.",
    "EC": "UPU: 6 digits (090306), no separator; pattern also allows old alphanumeric forms (H0103C, EC090112).",
    "MU": "UPU: 5 digits (42602), or R + 4 digits for Rodrigues; the pattern only accepts 3 digits + 2 letters + 3 digits (742CU001), which is not in the official source.",
    "CK": "UPU Cook Islands document shows no postcode at all; pattern \\d{4} has no zipex and no official basis.",
    "HM": "Uninhabited (UPU); Australia Post postcode 7151 used for Australian Antarctic/HM mail is not confirmed by the UPU document.",
}.items():
    rule(cc, low=True, notes="No separator. Pattern conflicts with or is not backed by the official source: " + n)
R["HM"]["extra"] = {"7151": "7151"}

# --- prefixes (written in front of the code, not part of the pattern) ----------
rule("AX", prefix=pfx("AX-", "required", "UPU: 5 digits 'preceded by AX' (AX-22100 MARIEHAMN)"))
rule("FO", prefix=pfx("FO-", "required", "UPU: 'ISO code alpha-2 (FO) plus 3 digits' (FO-100 Tórshavn)"))
rule("CY", prefix=pfx("CY-", "optional", "UPU: 'preceded by CY- for inbound mail'; domestic example has none (6036 Larnaka)"))
rule("HR", prefix=pfx("HR-", "required", "UPU: 5 digits 'preceded by HR' (HR-10000 ZAGREB)"))
rule("HT", prefix=pfx("HT", "required", "UPU: 4 digits 'preceded by HT', no separator (HT6120 DELMAS)"))
rule("LT", prefix=pfx("LT-", "required", "UPU: Lithuania Post requires the ISO country code (LT-04340 Vilnius)"))
rule("LU", prefix=pfx("L-", "required", "UPU: 4 digits 'preceded by L' (L-1234 DUDELANGE); the prefix is L, not LU"))
rule("MD", prefix=pfx("MD-", "required", "UPU: 4 digits 'preceded by MD-' (MD-2012, CHISINAU)"))
rule("AZ", prefix=pfx("AZ", "required", "UPU: 'ISO country code and 4 digits', no separator (AZ1010 Baku)"))
rule("AI", prefix=pfx("AI-", "required", "UPU: 'with a dash before the numeric part' (AI-2640)"))
rule("OM", prefix=pfx("PC ", "optional", "Pattern allows an optional 'PC ' (postal code) label; UPU shows 3 digits only (133)"))
R["OM"]["extra"] = {"PC 133": "133"}
for cc in ("AX", "FO", "CY", "HR", "HT", "LT", "LU", "MD", "AZ", "AI"):
    R[cc]["notes"] = "Prefix is written on mail but is not part of the libaddressinput pattern, so canonical form excludes it."

# --- notes for plain-digit countries that need them ---------------------------
NOTES = {
    "BD": "UPU writes 'DHAKA – 1340': the dash separates locality and code, not part of the code.",
    "PK": "UPU writes 'ISLAMABAD–44000': the dash separates locality and code, not part of the code.",
    "FR": "Pattern allows a space after 2 digits, but La Poste/UPU write 5 digits without a space (33380).",
    "BN": "Pattern allows a space after the 2 letters; UPU writes BT2328 without one.",
    "BY": "",
    "EE": "",
    "RS": "UPU mentions a 6-digit PAK address code; pattern accepts 5 or 6 digits, no separator either way.",
    "CL": "UPU coding diagram splits '872 0019' but addresses write 8720019 with no space.",
    "CO": "UPU coding diagram splits '11 02 21' but addresses write the 6 digits together.",
    "RU": "UPU coding diagram splits '125 075' but addresses write 125075.",
    "LI": "UPU: Liechtenstein uses Swiss Post's system; source is the Switzerland document.",
    "SJ": "UPU: 'See Norway'; source is the Norway document.",
    "GL": "UPU: 'See Denmark'; source is the Denmark document.",
    "CC": "UPU: 'See Australia'. No zipex; Australia Post code 6799 used as the test example.",
    "CX": "UPU: 'See Australia'. No zipex; Australia Post code 6798 used as the test example.",
    "NF": "UPU: 'Postcode of NORFOLK ISLAND is 2899'. No zipex; 2899 used as the test example.",
    "PF": "No zipex; UPU example 98709 used as the test example.",
    "IQ": "No zipex; UPU example 61002 used as the test example.",
    "EH": "No UPU document for Western Sahara; addresses use Barid Al-Maghrib 5-digit codes (Morocco document).",
    "IL": "UPU: 7 digits (9414219); pattern also accepts the old 5 digits. No separator.",
    "GN": "UPU: 3 digits, often followed by a BP (P.O. box) number, which is not part of the code.",
    "BB": "Letters BB are part of the code (UPU: 'preceded by BB', BB26028), no separator.",
    "AD": "Letters AD are part of the code (UPU: 'AD is a part of the postcode').",
    "VC": "Letters VC are part of the code (UPU: VC0120).",
    "VG": "Letters VG are part of the code (UPU: VG1110).",
    "AR": "CPA: 1 letter + 4 digits + 3 letters, no separator (UPU: Y5900FNF). Pattern also accepts the old 4-digit code.",
    "SZ": "UPU: 1 letter + 3 digits (H100).",
}
EXTRA = {"CC": {"6799": "6799"}, "CX": {"6798": "6798"}, "NF": {"2899": "2899"},
         "PF": {"98709": "98709"}, "IQ": {"61002": "61002"}}
INVALID = {"BY": {"20050": "5 digits; Belarus codes are 6 digits (220050 is also listed)"},
           "EE": {"1001": "4 digits; Estonian codes are 5 digits"}}


def load():
    zip_, none = {}, []
    for line in INFO.read_text().splitlines():
        k, _, v = line.partition("=")
        if not re.fullmatch(r"data/[A-Z]{2}", k) or k == "data/ZZ":
            continue
        d = json.loads(v)
        if "zip" in d:
            zip_[d["key"]] = d
        else:
            none.append(d["key"])
    return zip_, none


def main():
    data, none = load()
    out = {"_schema": {
        "description": "Rule that turns typed input into the country's standard written postal code. Countries come from libaddressinput countryinfo.txt (commit in sources/libaddressinput/COMMIT).",
        "procedure": [
            "1. Remove every character in `strip` from the input (compact form).",
            "2. If `uppercase`, convert to upper case.",
            "3. If the compact form does not fit the pattern after formatting and `prefix.strip_if_typed`, remove a leading prefix (prefix text with `strip` characters removed, case-insensitive) and retry.",
            "4. Apply every op in `insert`. Positions and conditions are evaluated on the compact string, then all characters are inserted at once.",
            "5. The result must fully match the libaddressinput `zip` pattern.",
        ],
        "insert_op": {
            "after": "int n: insert `char` after the n-th character (counted from the start)",
            "before_last": "int n: insert `char` before the last n characters",
            "char": "separator to insert (' ' or '-')",
            "only_when_length": "optional list of compact lengths; op applies only for these lengths",
            "only_when_match": "optional regex tested (re.search) on the upper-cased compact string; op applies only when it matches",
        },
        "prefix": "null, or {text, status: required|optional, scope, strip_if_typed}. A prefix written on mail in front of the code but NOT part of the libaddressinput pattern; the canonical form excludes it. Letters that the pattern itself contains (AD, BB, LV-, KY, VC, VG...) are part of the code, not a prefix.",
        "canonical_examples": "zipex values in standard form, same order; zipex values that cannot be valid are moved to `invalid_zipex` with a reason.",
        "zipex_deviations": "{zipex: {canonical, reason}} for zipex values whose official written form differs from how libaddressinput writes them.",
        "extra_examples": "typed input -> expected output, from the official source; used for countries without zipex or to test prefixes.",
        "confidence": "high = rule confirmed by `source`; low = not confirmed or pattern conflicts with source (see notes).",
        "source": "UPU addressing document for the country (or the parent operator's document when the UPU page refers to it).",
        "checked_by": "sources/postal/check.py -> logs/postal-check.txt",
    }}
    for cc in sorted(data):
        d = data[cc]
        r = R.get(cc) or dict(insert=[], prefix=None, low=False, notes="", extra={}, invalid={}, deviation={})
        notes = " ".join(x for x in (NOTES.get(cc, ""), r["notes"]) if x)
        if not r["insert"] and not notes:
            notes = "Plain digits, no separator (UPU)."
        has_letters = bool(re.search(r"[A-Za-z]", d["zip"].replace("\\d", "")))
        invalid = {**INVALID.get(cc, {}), **r["invalid"]}
        rec = {
            "uppercase": has_letters,
            "strip": STRIP,
            "insert": r["insert"],
            "prefix": r["prefix"],
            "pattern": d["zip"],
            "zipex": d.get("zipex", ""),
        }
        # Written independently of the formatter: zipex as published, unless the
        # official form differs (zipex_deviations gives the official form).
        rec["canonical_examples"] = [
            r["deviation"][e]["canonical"] if e in r["deviation"] else e
            for e in d.get("zipex", "").split(",") if e and e not in invalid]
        if invalid:
            rec["invalid_zipex"] = invalid
        if r["deviation"]:
            rec["zipex_deviations"] = r["deviation"]
        extra = {**EXTRA.get(cc, {}), **r["extra"]}
        if extra:
            rec["extra_examples"] = extra
        rec["source"] = OTHER_SOURCE.get(cc) or UPU.format(ISO3[cc])
        rec["confidence"] = "low" if r["low"] else "high"
        rec["notes"] = notes
        out[cc] = rec
    out["_no_postal_code"] = sorted(none)
    out["_no_postal_code_notes"] = {
        "IE": "No `zip` in this countryinfo.txt snapshot, although Ireland has used Eircode (e.g. A65 F4E2, space after 3rd character) since 2015. Left out because there is no pattern to check against.",
        "UM": "Has zipex 96898 but no `zip` pattern in countryinfo.txt.",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {OUT} ({len(data)} countries, {len(none)} without postal code)")


if __name__ == "__main__":
    main()
