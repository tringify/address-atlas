import { countriesData, provincesData, languagesData } from "./data.js";

export interface PostalOp { char: string; after?: number; before_last?: number; only_when_length?: number[]; only_when_match?: string; unless_match?: string }
export interface Postal {
  kind: string; pattern: string; examples: string[]; required: boolean; uppercase: boolean; strip: string;
  insert: PostalOp[]; prefix: { text: string; required: boolean } | null; max_length: number; input_mode: "numeric" | "text";
}
export interface Country {
  layout: string[][]; envelope: string[]; required: string[]; uppercase: string[];
  city_kind: string; district_kind: string | null;
  province: { kind: string; codes: string[] } | null; postal: Postal | null;
}
export interface ProvinceInfo { country: string; local: string; latin: string; aliases: string[] }
export interface Locale { labels: Record<string, string>; countries: Record<string, string>; provinces: Record<string, string> }
export interface Address {
  first_name?: string; last_name?: string; company?: string; address1?: string; address2?: string; district?: string;
  city?: string; province_code?: string; postal_code?: string; country_code: string; phone?: string;
}

const countries = countriesData as unknown as Record<string, Country>;
const provinces = provincesData as unknown as Record<string, ProvinceInfo>;
export const languages: readonly string[] = languagesData as string[];
const aliases: Record<string, string> = {};
for (const [code, p] of Object.entries(provinces)) for (const a of p.aliases) aliases[a] = code;

export class AtlasError extends Error {
  constructor(public code: "unknown_country" | "unknown_language" | "no_postal_code" | "postal_invalid") { super(code); }
}

export function countryCodes(): string[] { return Object.keys(countries).sort(); }

export function getCountry(code: string): Country {
  const c = countries[code.toUpperCase()];
  if (!c) throw new AtlasError("unknown_country");
  return c;
}

/** Resolves a retired province code to its successor. */
export function getProvince(code: string): { code: string; province: ProvinceInfo } | null {
  let c = code.toUpperCase();
  c = aliases[c] ?? c;
  const p = provinces[c];
  return p ? { code: c, province: p } : null;
}

const localeCache = new Map<string, Locale>();
/** Loads one language. Pass a loader that returns data/i18n/<lang>.json (e.g. dynamic import or fetch). */
export async function loadLocale(lang: string, loader: (lang: string) => Promise<Locale>): Promise<Locale> {
  if (!languages.includes(lang)) throw new AtlasError("unknown_language");
  let l = localeCache.get(lang);
  if (!l) { l = await loader(lang); localeCache.set(lang, l); }
  return l;
}

function stripChars(s: string, chars: string): string { return [...s].filter((ch) => !chars.includes(ch)).join(""); }

function apply(p: Postal, compact: string): string {
  let s = p.uppercase ? compact.toUpperCase() : compact;
  const chars = [...s], n = chars.length, up = s.toUpperCase();
  const cuts: [number, string][] = [];
  for (const op of p.insert) {
    if (op.only_when_length && !op.only_when_length.includes(n)) continue;
    if (op.only_when_match && !new RegExp(op.only_when_match).test(up)) continue;
    if (op.unless_match && new RegExp(op.unless_match).test(up)) continue;
    const at = op.before_last ? n - op.before_last : op.after ?? 0;
    if (at > 0 && at < n) cuts.push([at, op.char]);
  }
  return chars.map((ch, i) => cuts.filter(([at]) => at === i).map(([, sep]) => sep).join("") + ch).join("");
}

/** Returns the standard written form of a postal code, or throws AtlasError. */
export function normalizePostal(countryCode: string, input: string): string {
  const p = getCountry(countryCode).postal;
  if (!p) throw new AtlasError("no_postal_code");
  const re = new RegExp(`^(?:${p.pattern})$`, "i");
  const compact = stripChars(input.trim(), p.strip);
  let out = apply(p, compact);
  if (!re.test(out) && p.prefix) {
    const pre = stripChars(p.prefix.text, p.strip);
    if (compact.length > pre.length && compact.slice(0, pre.length).toLowerCase() === pre.toLowerCase()) out = apply(p, compact.slice(pre.length));
  }
  if (!out || !re.test(out)) throw new AtlasError("postal_invalid");
  return out;
}

/** Placeholder for a postal code input: the country's first example. */
export function postalPlaceholder(countryCode: string): string | null {
  return getCountry(countryCode).postal?.examples[0] ?? null;
}

/** Printed address lines in the locale's language, in the country's order. */
export function formatAddress(a: Address, locale: Locale): string[] {
  const c = getCountry(a.country_code);
  const vals: Record<string, string> = {
    first_name: a.first_name ?? "", last_name: a.last_name ?? "", company: a.company ?? "",
    address1: a.address1 ?? "", address2: a.address2 ?? "", district: a.district ?? "", city: a.city ?? "",
    province_code: a.province_code ? locale.provinces[a.province_code.toUpperCase()] ?? "" : "",
    postal_code: a.postal_code ?? "",
  };
  const lines: string[] = [];
  for (const tpl of c.envelope) {
    const line = tpl.replace(/\{([a-z_0-9]+)\}/g, (_, f: string) => (c.uppercase.includes(f) ? vals[f].toUpperCase() : vals[f]))
      .split(/\s+/).filter(Boolean).join(" ").replace(/^[ ,-]+|[ ,-]+$/g, "");
    if (line) lines.push(line);
  }
  lines.push(locale.countries[a.country_code.toUpperCase()]);
  return lines;
}
