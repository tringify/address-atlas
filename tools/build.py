"""Build address-atlas data from sources/ and curated/.

Every published value is explicit: the build fails on any gap instead of
filling it at runtime.
"""
import glob, json, os, pathlib, re, sys

ROOT = pathlib.Path(os.environ.get("ATLAS_ROOT") or pathlib.Path(__file__).resolve().parents[1])
OUT = ROOT / "data"
DROPPED_LANGS = {"la", "vo", "cu"}
NO_POSTCODE = {"MZ", "PA", "ZM", "CD", "BI", "KM", "KP", "SY"}  # no published, validatable format
OVERRIDE_PATTERN = {"IN": r"[1-9]\d{2} ?\d{3}"}
# Formatting rules written for an older pattern (KR moved to 5 digits in 2015, MN added
# a 5+4 form, SV dropped the "CP " sorting form).
OVERRIDE_INSERT = {"KR": [], "SV": [], "MN": [{"after": 5, "char": "-", "only_when_length": [9]}]}

CITY_KINDS = {"city", "post_town", "suburb", "district", "village_township", "townland", "neighborhood"}
PROVINCE_KINDS = {"area", "county", "department", "district", "do_si", "emirate", "island", "oblast",
                  "parish", "prefecture", "province", "state"}
POSTAL_KINDS = {"postal", "zip", "pin", "eircode"}
TOKEN_FIELDS = {"N": ["first_name", "last_name"], "O": ["company"], "A": ["address1", "address2"],
                "D": ["district"], "C": ["city"], "S": ["province_code"], "Z": ["postal_code"], "X": []}
FIELDS = ["first_name", "last_name", "company", "address1", "address2", "district", "city",
          "province_code", "postal_code", "country_code", "phone"]
LABEL_FOR_FIELD = {"first_name": "fields.first_name", "last_name": "fields.last_name",
                   "company": "fields.company", "address1": "fields.address1", "address2": "fields.address2",
                   "phone": "fields.phone", "country_code": "fields.country"}

errors = []
def err(m): errors.append(m)


def load(p): return json.loads((ROOT / p).read_text())


def reviews():
    d = {}
    for f in sorted(glob.glob(str(ROOT / "sources/review/D-*.json"))):
        d.update(json.load(open(f)))
    for f in sorted(glob.glob(str(ROOT / "sources/verify/F-*.json"))):
        for k, v in json.load(open(f)).items():
            d[k] = v["final"]
    return d


def kind(candidates, allowed, default):
    for c in candidates:
        if c in allowed:
            return c
    return default


def parse_layout(cc, fmt, has_provinces):
    lines, envelope = [], []
    for raw in fmt.split("%n"):
        row, env, i = [], "", 0
        while i < len(raw):
            ch = raw[i]
            if ch != "%":
                env += ch; i += 1; continue
            tok = raw[i + 1]; i += 2
            if tok not in TOKEN_FIELDS:
                err(f"{cc}: unknown layout token %{tok}"); continue
            fields = TOKEN_FIELDS[tok]
            if tok == "S" and not has_provinces:
                fields = []
            if not fields:
                continue
            if tok == "A":
                lines += [["address1"], ["address2"]]; env += "{address1}\n{address2}"; continue
            row += fields
            env += " ".join("{%s}" % f for f in fields)
        if row:
            lines.append(row)
        env = env.strip(" ,-")

        if env:
            envelope += env.split("\n")
    # Forms start with who and company; the rest keeps the country's order.
    # Envelope lines keep the country's printed order unchanged.
    head = [r for r in lines if r in (["first_name", "last_name"], ["company"])]
    head.sort(key=lambda r: r != ["first_name", "last_name"])
    lines = head + [r for r in lines if r not in head]
    return lines, envelope


def postal_format(rule, typed, pattern):
    def apply(compact):
        s = compact.upper() if rule["uppercase"] else compact
        pos = []
        for op in rule["insert"]:
            if "only_when_length" in op and len(s) not in op["only_when_length"]: continue
            if "only_when_match" in op and not re.search(op["only_when_match"], s): continue
            if "unless_match" in op and re.search(op["unless_match"], s): continue
            p = op["after"] if "after" in op else len(s) - op["before_last"]
            if 0 < p < len(s): pos.append((p, op["char"]))
        for p, ch in sorted(pos, reverse=True): s = s[:p] + ch + s[p:]
        return s
    compact = "".join(c for c in typed.strip() if c not in rule["strip"])
    out = apply(compact)
    pre = rule.get("prefix")
    if pre and pre.get("strip_if_typed") and not re.fullmatch(pattern, out, re.I):
        t = "".join(c for c in pre["text"] if c not in rule["strip"]).lower()
        if compact.lower().startswith(t): out = apply(compact[len(t):])
    return out


def main():
    rev = reviews()
    live = load("sources/google-live/snapshot.json")["countries"]
    rules = load("sources/postal/rules.json")
    codes = [l.strip() for l in (ROOT / "sources/countries.txt").read_text().split() if l.strip()]
    langs = [l.strip() for l in (ROOT / "sources/languages.txt").read_text().split()
             if l.strip() and l.strip() not in DROPPED_LANGS]

    prov = {}
    for f in sorted(glob.glob(str(ROOT / "curated/provinces/[A-Z][A-Z].json"))):
        p = json.load(open(f)); prov[p["country"]] = p

    countries, provinces = {}, {}
    for cc in codes:
        r = rev.get(cc)
        if not r:
            err(f"{cc}: no reviewed entry"); continue
        lv = live.get(cc, {})
        named = bool((r.get("province") or {}).get("named"))
        units = prov.get(cc, {}).get("units", []) if named else []
        if named and cc not in prov:
            err(f"{cc}: addresses name a province but no province list")
        # An empty curated list means the slot holds one fixed value (e.g. VI, AS): no field.
        lines, envelope = parse_layout(cc, r["layout"], bool(units))
        req_tokens = r.get("required") or ""
        required = [f for t in req_tokens for f in (["address1"] if t == "A" else TOKEN_FIELDS.get(t, []))
                    if not (t == "S" and not units) and not (t == "Z" and cc in NO_POSTCODE)]
        required = ["first_name", "last_name"] + [f for f in required if f not in ("first_name", "last_name")] + ["country_code"]
        upper = sorted({f for t in (lv.get("upper") or "") for f in (["address1", "address2"] if t == "A" else TOKEN_FIELDS.get(t, []))})

        postal = None
        pr = r.get("postal") or {}
        if pr.get("uses") and cc not in NO_POSTCODE:
            pattern = OVERRIDE_PATTERN.get(cc, pr.get("pattern"))
            rule = dict(rules.get(cc) or {"uppercase": True, "strip": " -.", "insert": [], "prefix": None})
            if cc in OVERRIDE_INSERT:
                rule["insert"] = OVERRIDE_INSERT[cc]
            # Publish conditions without lookahead so RE2 (Go) and JS read them alike.
            ops = []
            for op in rule["insert"]:
                op = dict(op)
                m = re.fullmatch(r"\^\(\?!(.+)\)", op.get("only_when_match", ""))
                if m:
                    del op["only_when_match"]; op["unless_match"] = "^" + m.group(1)
                ops.append(op)
            rule["insert"] = ops
            if not pattern:
                err(f"{cc}: postcode used but no pattern")
            else:
                examples = []
                for e in pr.get("examples") or []:
                    got = postal_format(rule, e, pattern)
                    if not re.fullmatch(pattern, got, re.I):
                        err(f"{cc}: example {e!r} -> {got!r} fails pattern")
                    examples.append(got)
                if not examples:
                    err(f"{cc}: postcode without examples")
                lv_zip = (r.get("labels") or {}).get("postal")
                postal = {
                    "kind": kind([lv_zip, lv.get("zip_name_type")], POSTAL_KINDS, "postal"),
                    "pattern": pattern, "examples": examples,
                    "required": "postal_code" in required,
                    "uppercase": True,  # no country writes postal codes in lower case
                    "strip": rule["strip"], "insert": rule["insert"],
                    "prefix": ({"text": rule["prefix"]["text"], "required": rule["prefix"]["status"] == "required"}
                               if rule.get("prefix") else None),
                    "max_length": max(len(e) for e in examples) if examples else 0,
                    "input_mode": "numeric" if re.fullmatch(r"[\\d{},? \-\[\]()|]+", pattern.replace("\\d", "")) or set(re.sub(r"\\d|[{}0-9,?() \-\[\]|]", "", pattern)) == set() else "text",
                }
        if not postal:
            lines = [[f for f in row if f != "postal_code"] for row in lines]
            lines = [row for row in lines if row]
            envelope = [l for l in (re.sub(r"\s*\{postal_code\}\s*", " ", x).strip(" ,-") for x in envelope) if l]

        countries[cc] = {
            "layout": lines, "envelope": envelope, "required": required, "uppercase": upper,
            "city_kind": kind([(r.get("labels") or {}).get("city"), lv.get("locality_name_type")], CITY_KINDS, "city"),
            "district_kind": kind([lv.get("sublocality_name_type")], CITY_KINDS, "suburb") if any("district" in row for row in lines) else None,
            "province": ({"kind": kind([(r.get("province") or {}).get("kind"), lv.get("state_name_type")], PROVINCE_KINDS, "province"),
                          "codes": [u["code"] for u in units]} if units else None),
            "postal": postal,
        }
        for u in units:
            provinces[u["code"]] = {"country": cc, "local": u["local"], "latin": u["latin"],
                                    "aliases": u.get("aliases", [])}

    # i18n
    cldr_c = load("sources/cldr/countries.json")
    cldr_s = load("sources/cldr/subdivisions.json")
    i18n = {}
    en_labels = load("curated/labels/en.json")
    keys = list(en_labels)
    ph = lambda t: sorted(re.findall(r"\$\d|\{[A-Z_]+\}|<[^>]+>", t))
    for lang in langs:
        lf = ROOT / f"curated/labels/{lang}.json"
        lab = json.loads(lf.read_text()) if lf.exists() else {}
        if not lab:
            err(f"{lang}: no label file")
        labels, prov_ = {}, {}
        for k in keys:
            vv = lab.get(k)
            if not vv or not vv.get("value"):
                err(f"{lang}: label {k} missing"); continue
            if ph(vv["value"]) != ph(en_labels[k]["value"]):
                err(f"{lang}: label {k} placeholders differ from English")
            labels[k] = vv["value"]; prov_["labels." + k] = vv["provenance"]
        cn = dict(cldr_c.get(lang) or {})
        cf = ROOT / f"curated/country-names/{lang}.json"
        cur = json.loads(cf.read_text()) if cf.exists() else {}
        names = {}
        for cc in codes:
            if cc in cn:
                names[cc] = cn[cc]
            elif cc in cur:
                names[cc] = cur[cc]["value"]; prov_["countries." + cc] = "curated"
            else:
                err(f"{lang}: country {cc} missing")
        pn = {}
        sub = cldr_s.get(lang) or {}
        for code, p in provinces.items():
            if code in sub:
                pn[code] = sub[code].rstrip("⁰¹²³⁴⁵⁶⁷⁸⁹").strip()  # CLDR's disambiguation marks
            else:
                pn[code] = p["latin"]; prov_["provinces." + code] = "official"
        i18n[lang] = {"labels": labels, "countries": names, "provinces": pn, "provenance": prov_}

    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"{len(errors)} errors", file=sys.stderr)
        sys.exit(1)

    # codes ledger: never drop a published identifier
    ledger_p = ROOT / "codes.json"
    ledger = json.loads(ledger_p.read_text()) if ledger_p.exists() else {"countries": [], "provinces": [], "fields": [], "kinds": []}
    now = {"countries": sorted(countries), "provinces": sorted(set(provinces) | {a for p in provinces.values() for a in p["aliases"]}),
           "fields": FIELDS, "kinds": sorted(["city." + k for k in CITY_KINDS] + ["province." + k for k in PROVINCE_KINDS] + ["postal." + k for k in POSTAL_KINDS])}
    for k, old in ledger.items():
        gone = set(old) - set(now[k])
        if gone:
            sys.exit(f"codes.json: release drops {k}: {sorted(gone)}")
    ledger_p.write_text(json.dumps(now, indent=1) + "\n")

    OUT.mkdir(exist_ok=True); (OUT / "i18n").mkdir(exist_ok=True)
    (OUT / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    (OUT / "provinces.json").write_text(json.dumps(provinces, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    for lang, d in i18n.items():
        (OUT / f"i18n/{lang}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    (OUT / "languages.json").write_text(json.dumps(sorted(i18n)) + "\n")
    print(f"ok: {len(countries)} countries, {len(provinces)} provinces, {len(i18n)} languages")


if __name__ == "__main__":
    main()
