"""Compare the pinned sources with what their publishers serve today.

Prints a Markdown report of every difference and exits 1 when there is one.
"""
import json, pathlib, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOOGLE = "https://chromium-i18n.appspot.com/ssl-address/data/{}"
FIELDS = ("fmt", "require", "upper", "zip", "zipex", "sub_isoids", "sub_keys",
          "state_name_type", "locality_name_type", "zip_name_type", "sublocality_name_type")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "address-atlas-watch"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def main():
    snap = json.loads((ROOT / "sources/google-live/snapshot.json").read_text())["countries"]
    codes = (ROOT / "sources/countries.txt").read_text().split()
    out = []
    for cc in codes:
        try:
            now = json.loads(get(GOOGLE.format(cc)))
        except Exception as e:  # 404 for countries Google has no data for
            now = {} if "404" in str(e) else None
            if now is None:
                out.append(f"- {cc}: fetch failed ({e})"); continue
        old = snap.get(cc, {})
        for f in FIELDS:
            if old.get(f) != now.get(f):
                out.append(f"- {cc} `{f}`: `{old.get(f)}` → `{now.get(f)}`")

    pins = json.loads((ROOT / "sources/pins.json").read_text())
    iso = json.loads(get("https://salsa.debian.org/api/v4/projects/iso-codes-team%2Fiso-codes/repository/commits?per_page=1"))[0]["id"]
    if iso != pins["iso_codes"]:
        out.append(f"- iso-codes: new commit {iso} (pinned {pins['iso_codes']})")
    cldr = json.loads(get("https://api.github.com/repos/unicode-org/cldr-json/releases/latest"))["tag_name"]
    if cldr != pins["cldr"]:
        out.append(f"- CLDR: new release {cldr} (pinned {pins['cldr']})")

    if out:
        print("Sources changed since the last release:\n\n" + "\n".join(out))
        sys.exit(1)
    print("No source changes.")


if __name__ == "__main__":
    main()
