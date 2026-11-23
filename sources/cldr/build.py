import json, os, re, sys, collections
import xml.etree.ElementTree as ET
DL, REPO = sys.argv[1], sys.argv[2]
C = f'{DL}/common/common'
JS = f'{DL}/cldr-localenames-full/package/main'
OUT = f'{REPO}/sources/cldr'
langs = open(f'{REPO}/sources/languages.txt').read().split()
ccs = open(f'{REPO}/sources/countries.txt').read().split()
subs = [l.rstrip('\n').split('\t') for l in open(f'{REPO}/sources/subdivisions.tsv', encoding='utf-8') if l.strip()]
assert len(langs) == 142 and len(ccs) == 250 and len(subs) == 1359

LOCMAP = {  # our code -> (cldr locale or None, note)
 'pt-BR': ('pt', 'CLDR "pt" is Brazilian Portuguese (pt_BR is default content of pt)'),
 'pt': ('pt', 'CLDR "pt" (= pt_BR default content)'),
 'pt-PT': ('pt_PT', 'European Portuguese; parent pt'),
 'no': ('no', 'CLDR 49 "no" is the base Norwegian locale (nb and nn have parent no)'),
 'nb': ('nb', 'parentLocale = no'),
 'nn': ('nn', 'parentLocale = no'),
 'mo': ('ro_MD', 'CLDR languageAlias mo->ro (deprecated); using ro_MD (Romanian, Moldova), parent ro'),
 'sh': ('sr_Latn', 'CLDR languageAlias sh->sr_Latn (legacy); parentLocale of sr_Latn = root'),
 'zh': ('zh', 'CLDR "zh" (= zh_Hans default content)'),
 'zh-TW': ('zh_Hant', 'likely subtags zh-TW -> zh_Hant_TW, which is default content of zh_Hant; parentLocale = root'),
 'la': (None, 'no Latin locale in CLDR 49'),
 'vo': (None, 'no Volapuk locale in CLDR 49'),
 'cu': (None, 'no Church Slavic locale in CLDR 49'),
}
# parent locales (non-component-specific)
sd = ET.parse(f'{C}/supplemental/supplementalData.xml').getroot()
PARENT = {}
for pls in sd.iter('parentLocales'):
    if pls.get('component'): continue
    for pl in pls.findall('parentLocale'):
        for l in pl.get('locales').split(): PARENT[l] = pl.get('parent')
def parent(l):
    if l in PARENT: return PARENT[l]
    return l.rsplit('_', 1)[0] if '_' in l else 'root'
def chain(l):
    out = []
    while l != 'root':
        out.append(l); l = parent(l)
    return out

def load(path, tag):
    if not os.path.exists(path): return {}
    r = ET.parse(path).getroot()
    d = {}
    ldn = r.find('localeDisplayNames')
    if ldn is None: return {}
    for e in ldn.iter(tag):
        if e.get('alt') or not e.text or e.text == '\u2191\u2191\u2191': continue
        d[e.get('type')] = (e.text, e.get('draft') or 'approved')
    return d
OK_DRAFT = {'approved', 'contributed'}  # cldr-json threshold

# ---- locale map ----
lm = []
for l in langs:
    if l in LOCMAP: loc, note = LOCMAP[l]
    else:
        loc = l.replace('-', '_')
        assert os.path.exists(f'{C}/main/{loc}.xml'), l
        note = 'same code'
    if loc:
        ch = chain(loc)
        note += f'; inheritance chain: {" > ".join(ch + ["root"])}'
        if not os.path.exists(f'{C}/subdivisions/{loc}.xml'):
            hs = [c for c in ch if os.path.exists(f'{C}/subdivisions/{c}.xml')]
            note += f'; subdivisions: {"no file for "+loc+", inherited from "+hs[0] if hs else "no CLDR subdivision file in chain"}'
    lm.append((l, loc, note))

# ---- non-ISO subdivision code mapping ----
SUBMAP = {
 'TW-KINMEN_COUNTY': ('twkin', 'ISO TW-KIN Kinmen County'),
 'TW-LIENCHIANG_COUNTY': ('twlie', 'ISO TW-LIE Lienchiang County'),
 'BS-CROOKED_ISLAND': ('bsck', 'ISO BS-CK Crooked Island and Long Cay district'),
 'RU-RESPUBLIKA_KRYM': ('ua43', 'same territory as ISO UA-43 (Crimea); CLDR has it only under UA'),
 'RU-SEVASTOPOL': ('ua40', 'same territory as ISO UA-40 (Sevastopol); CLDR has it only under UA'),
}
NOEQ = {
 'BS-ABACO': 'island group split across ISO districts bsco/bsno/bsso; no single CLDR id',
 'BS-ANDROS': 'island split across ISO districts bscs/bsns/bssa (+bsmc); no single CLDR id',
 'BS-ELEUTHERA': 'island split across ISO districts bsce/bsne/bsse (+bshi); no single CLDR id',
 'BS-GRAND_BAHAMA': 'island split across ISO districts bseg/bswg/bsfp; no single CLDR id',
 'CV-FOGO': 'island, not an ISO 3166-2 unit (municipalities cvcf/cvmo/cvsf); no CLDR id',
 'CV-SANTIAGO': 'island, not an ISO 3166-2 unit (9 municipalities); no CLDR id',
 'CV-SANTO_ANTAO': 'island, not an ISO 3166-2 unit (cvpa/cvpn/cvrg); no CLDR id',
 'CV-SAO_NICOLAU': 'island, not an ISO 3166-2 unit (cvrb/cvts); no CLDR id',
 'HK-KOWLOON': 'ISO 3166-2 defines no HK subdivisions; no CLDR id',
 'HK-HONG_KONG_ISLAND': 'ISO 3166-2 defines no HK subdivisions; no CLDR id',
 'HK-NEW_TERRITORIES': 'ISO 3166-2 defines no HK subdivisions; no CLDR id',
 'KY-CAYMAN_BRAC': 'ISO 3166-2 defines no KY subdivisions; no CLDR id',
 'KY-GRAND_CAYMAN': 'ISO 3166-2 defines no KY subdivisions; no CLDR id',
 'KY-LITTLE_CAYMAN': 'ISO 3166-2 defines no KY subdivisions; no CLDR id',
 'TV-NIULAKITA': 'not an ISO 3166-2 unit (administered with Niutao, tvnit); no CLDR id',
}
sm = ET.parse(f'{C}/supplemental/supplementalMetadata.xml').getroot()
SALIAS = {e.get('type'): e.get('replacement') for e in sm.iter('subdivisionAlias')}
en_sub = load(f'{C}/subdivisions/en.xml', 'subdivision')
idmap = {}  # our code -> (cldr id or None, note)
for row in subs:
    code = row[0]
    if code in SUBMAP: idmap[code] = SUBMAP[code]; continue
    if code in NOEQ: idmap[code] = (None, NOEQ[code]); continue
    cid = code.replace('-', '').lower()
    note = ''
    if cid not in en_sub and cid in SALIAS and ' ' not in SALIAS[cid]:
        note = f'CLDR subdivisionAlias {cid}->{SALIAS[cid]}'; cid = SALIAS[cid]
    if cid not in en_sub:
        extra = {'usmh': 'CLDR treats MH as a territory', 'usfm': 'CLDR treats FM as a territory', 'uspw': 'CLDR treats PW as a territory',
                 'usaa': 'US military postal code, not an ISO 3166-2 subdivision', 'usae': 'US military postal code, not an ISO 3166-2 subdivision',
                 'usap': 'US military postal code, not an ISO 3166-2 subdivision'}.get(cid)
        idmap[code] = (None, f'id {cid} not in any CLDR 49 subdivisions file' + (f' ({extra})' if extra else '')); continue
    idmap[code] = (cid, note)

# ---- extract ----
mainc, subc = {}, {}
def main_terr(loc):
    if loc not in mainc: mainc[loc] = load(f'{C}/main/{loc}.xml', 'territory')
    return mainc[loc]
def sub_names(loc):
    if loc not in subc: subc[loc] = load(f'{C}/subdivisions/{loc}.xml', 'subdivision')
    return subc[loc]

countries, subdivs, missing, csrc, ssrc = {}, {}, [], [], []
jsonmismatch = []
for l, loc, _ in lm:
    countries[l], subdivs[l] = {}, {}
    if not loc:
        for cc in ccs: missing.append((l, 'country', cc, 'no CLDR 49 locale for this language'))
        for row in subs: missing.append((l, 'subdivision', row[0], 'no CLDR 49 locale for this language'))
        continue
    ch = chain(loc)
    jl = loc.replace('_', '-')
    jt = json.load(open(f'{JS}/{jl}/territories.json', encoding='utf-8'))['main'][jl]['localeDisplayNames']['territories']
    for cc in ccs:
        got = None; low = None
        for c in ch:
            v = main_terr(c).get(cc)
            if not v: continue
            if v[1] in OK_DRAFT: got = (v[0], c); break
            if low is None: low = (c, v)
        jv = jt.get(cc)
        if (got[0] if got else None) != (jv if jv != cc else None):
            jsonmismatch.append((l, cc, got, jv))
        if got:
            countries[l][cc] = got[0]
            csrc.append((l, cc, got[1], 'inherited' if got[1] != loc else 'own'))
        else:
            r = f'not in CLDR {" > ".join(ch)} territories'
            if low: r += f'; only a draft="{low[1][1]}" value exists in CLDR XML {low[0]} ({low[1][0]}), below cldr-json publication threshold'
            missing.append((l, 'country', cc, r))
    for row in subs:
        code = row[0]; cid, note = idmap[code]
        if not cid:
            missing.append((l, 'subdivision', code, note)); continue
        got = None
        for c in ch:
            v = sub_names(c).get(cid)
            if v: got = (v[0], c, v[1]); break
        if got:
            subdivs[l][code] = got[0]
            ssrc.append((l, code, cid, got[1], 'inherited' if got[1] != loc else 'own', got[2]))
        else:
            hs = [c for c in ch if os.path.exists(f'{C}/subdivisions/{c}.xml')]
            missing.append((l, 'subdivision', code, f'CLDR {"/".join(hs)} has no name for {cid}' if hs else f'no CLDR subdivision data for {" > ".join(ch)}'))

# ---- checks ----
mc = collections.Counter((m[0], m[1]) for m in missing)
for l in langs:
    assert len(countries[l]) + mc[(l, 'country')] == 250, l
    assert len(subdivs[l]) + mc[(l, 'subdivision')] == 1359, l
print('json mismatches:', len(jsonmismatch)); [print(' ', x) for x in jsonmismatch[:20]]
# TSV en/de/es/fr/it columns vs extraction
for i, l in enumerate(['en', 'de', 'es', 'fr', 'it'], start=2):
    diff = [(r[0], r[i], subdivs[l].get(r[0])) for r in subs if r[i] != subdivs[l].get(r[0])]
    print(f'TSV {l} diffs: {len(diff)}', diff[:6])

# ---- write ----
def tsv(name, header, rows):
    with open(f'{OUT}/{name}', 'w', encoding='utf-8') as f:
        f.write('\t'.join(header) + '\n')
        for r in rows: f.write('\t'.join(x or '' for x in r) + '\n')
tsv('locale-map.tsv', ['our_code', 'cldr_locale', 'notes'], lm)
tsv('missing.tsv', ['lang', 'kind', 'code', 'reason'], missing)
tsv('subdivision-id-map.tsv', ['our_code', 'cldr_id', 'notes'], [(k, v[0] or '', v[1]) for k, v in idmap.items() if v[1] or v[0] is None])
tsv('countries-source.tsv', ['lang', 'code', 'cldr_source_locale', 'own_or_inherited'], csrc)
tsv('subdivisions-source.tsv', ['lang', 'code', 'cldr_id', 'cldr_source_locale', 'own_or_inherited', 'draft'], ssrc)
for name, d in [('countries.json', countries), ('subdivisions.json', subdivs)]:
    with open(f'{OUT}/{name}', 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=False)
# summary
print('lang\tcldr\tcountries\tsubdivisions\tc_inh\ts_inh')
ci = collections.Counter(r[0] for r in csrc if r[3] == 'inherited'); si = collections.Counter(r[0] for r in ssrc if r[4] == 'inherited')
for l, loc, _ in lm: print(f'{l}\t{loc}\t{len(countries[l])}\t{len(subdivs[l])}\t{ci[l]}\t{si[l]}')
print('missing country', sum(1 for m in missing if m[1] == 'country'), 'subdivision', sum(1 for m in missing if m[1] == 'subdivision'))
print('drafts', collections.Counter(r[5] for r in ssrc))
