"""Check sources/postal/rules.json against libaddressinput countryinfo.txt.

For every country with a `zip` pattern, each zipex example is lowercased, its
separators removed, and the rule applied; the result must equal the matching
canonical example, which must fully match the pattern. Also checks coverage,
prefix stripping, extra examples and idempotence.

Run: python3 -I sources/postal/check.py > logs/postal-check.txt
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
INFO = ROOT / "sources/libaddressinput/countryinfo.txt"
RULES = ROOT / "sources/postal/rules.json"
SEPARATORS = " -.–"  # how a zipex is reduced to "what a person types"


def _apply(rule, compact):
    s = compact.upper() if rule["uppercase"] else compact
    positions = []
    for op in rule["insert"]:
        if "only_when_length" in op and len(s) not in op["only_when_length"]:
            continue
        if "only_when_match" in op and not re.search(op["only_when_match"], s):
            continue
        pos = op["after"] if "after" in op else len(s) - op["before_last"]
        if 0 < pos < len(s):
            positions.append((pos, op["char"]))
    for pos, ch in sorted(positions, reverse=True):
        s = s[:pos] + ch + s[pos:]
    return s


def format_code(rule, typed, pattern=None):
    """Turn typed input into the standard written form."""
    compact = "".join(c for c in typed.strip() if c not in rule["strip"])
    out = _apply(rule, compact)
    p = rule.get("prefix")
    if p and p.get("strip_if_typed") and pattern and not re.fullmatch(pattern, out):
        ptxt = "".join(c for c in p["text"] if c not in rule["strip"]).lower()
        if compact.lower().startswith(ptxt):
            out = _apply(rule, compact[len(ptxt):])
    return out


def load_info():
    zips, none = {}, set()
    for line in INFO.read_text().splitlines():
        k, _, v = line.partition("=")
        if not re.fullmatch(r"data/[A-Z]{2}", k) or k == "data/ZZ":
            continue
        d = json.loads(v)
        if "zip" in d:
            zips[d["key"]] = d
        else:
            none.add(d["key"])
    return zips, none


def main():
    zips, none = load_info()
    rules = json.loads(RULES.read_text())
    fails = []
    stats = dict(examples=0, exact=0, deviations=0, invalid=0, extra=0, prefix=0)

    def fail(cc, msg):
        fails.append(f"{cc}: {msg}")

    # coverage
    entries = {k for k in rules if not k.startswith("_")}
    for cc in sorted(set(zips) - entries):
        fail(cc, "has zip pattern but no rule")
    for cc in sorted(entries - set(zips)):
        fail(cc, "rule present but no zip pattern in countryinfo")
    if set(rules.get("_no_postal_code", [])) != none:
        fail("_no_postal_code", f"mismatch: {sorted(none ^ set(rules.get('_no_postal_code', [])))}")

    for cc in sorted(set(zips) & entries):
        d, r = zips[cc], rules[cc]
        pat = d["zip"]
        for key in ("uppercase", "strip", "insert", "prefix", "canonical_examples", "source", "confidence", "notes"):
            if key not in r:
                fail(cc, f"missing field {key}")
        if not str(r.get("source", "")).startswith("https://"):
            fail(cc, "source is not an https URL")
        if r.get("confidence") not in ("high", "low"):
            fail(cc, "confidence must be high or low")
        if r.get("confidence") == "low" and not r.get("notes"):
            fail(cc, "low confidence without notes")
        if r.get("pattern") != pat:
            fail(cc, "pattern copy in rules.json differs from countryinfo")

        invalid = r.get("invalid_zipex", {})
        devs = r.get("zipex_deviations", {})
        zipex = [e for e in d.get("zipex", "").split(",") if e]
        valid = [e for e in zipex if e not in invalid]
        canon = r["canonical_examples"]
        if len(valid) != len(canon):
            fail(cc, f"{len(valid)} usable zipex but {len(canon)} canonical examples")
            continue
        for e in invalid:
            stats["invalid"] += 1
            if e not in zipex:
                fail(cc, f"invalid_zipex {e!r} is not a zipex value")
            elif re.fullmatch(pat, e) or re.fullmatch(pat, format_code(r, e.lower(), pat)):
                fail(cc, f"zipex {e!r} marked invalid but it is valid")
        for e, c in zip(valid, canon):
            stats["examples"] += 1
            typed = "".join(ch for ch in e.lower() if ch not in SEPARATORS)
            got = format_code(r, typed, pat)
            if got != c:
                fail(cc, f"zipex {e!r}: typed {typed!r} -> {got!r}, expected {c!r}")
            if not re.fullmatch(pat, c):
                fail(cc, f"canonical {c!r} does not match pattern")
            if format_code(r, c, pat) != c:
                fail(cc, f"canonical {c!r} is not stable under the rule")
            if c == e:
                stats["exact"] += 1
            elif devs.get(e, {}).get("canonical") == c:
                stats["deviations"] += 1
            else:
                fail(cc, f"canonical {c!r} differs from zipex {e!r} without a zipex_deviations entry")
        for typed, want in r.get("extra_examples", {}).items():
            stats["extra"] += 1
            got = format_code(r, typed.lower(), pat)
            if got != want or not re.fullmatch(pat, got):
                fail(cc, f"extra example {typed!r} -> {got!r}, expected {want!r} matching pattern")
        p = r.get("prefix")
        if p:
            if p.get("status") not in ("required", "optional"):
                fail(cc, "prefix status must be required or optional")
            for c in canon:
                stats["prefix"] += 1
                typed = (p["text"] + c).lower()
                got = format_code(r, typed, pat)
                if got != c:
                    fail(cc, f"prefixed input {typed!r} -> {got!r}, expected {c!r}")

    n = len(zips)
    seps = sorted(cc for cc in zips if rules.get(cc, {}).get("insert"))
    low = sorted(cc for cc in zips if rules.get(cc, {}).get("confidence") == "low")
    print(f"countries with zip pattern: {n}")
    print(f"countries without postal code: {len(none)}")
    print(f"countries with separator insert rules: {len(seps)}: {' '.join(seps)}")
    print(f"low confidence: {len(low)}: {' '.join(low)}")
    print(f"zipex checked: {stats['examples']} (reproduced exactly: {stats['exact']}, "
          f"documented deviations: {stats['deviations']}); invalid zipex confirmed rejected: {stats['invalid']}")
    print(f"extra examples checked: {stats['extra']}; prefixed inputs checked: {stats['prefix']}")
    for cc in sorted(zips):
        for e, v in rules.get(cc, {}).get("zipex_deviations", {}).items():
            print(f"  deviation {cc} {e!r} -> {v['canonical']!r}: {v['reason']}")
        for e, why in rules.get(cc, {}).get("invalid_zipex", {}).items():
            print(f"  invalid   {cc} {e!r}: {why}")
    if fails:
        print(f"FAILURES ({len(fails)}):")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
