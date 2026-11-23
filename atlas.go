// Package atlas provides address formats, postal code rules, provinces and
// translated labels for every country.
//
// All data is generated from published sources and checked at build time:
// every country, province and language has explicit values, so nothing here
// falls back to another value at runtime.
package atlas

import (
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strings"
	"sync"
)

//go:embed data/countries.json data/provinces.json data/languages.json data/i18n/*.json
var files embed.FS

// Country is one country's address rules.
type Country struct {
	Code string `json:"-"`
	// Layout lists form rows in writing order; fields on a row share a line.
	Layout [][]string `json:"layout"`
	// Envelope is the printed form, one template per line with {field} placeholders.
	Envelope []string `json:"envelope"`
	// EnvelopeLatin is the Latin-order printed form of a country written in its
	// own script, used when the reader's language is not in EnvelopeLanguages.
	EnvelopeLatin     []string `json:"envelope_latin"`
	EnvelopeLanguages []string `json:"envelope_languages"`
	// ProvincePrint is "code" where postal convention prints the code's suffix
	// (CA, NSW, SP) and "name" elsewhere.
	ProvincePrint string `json:"province_print"`
	// Required lists the fields a deliverable address needs.
	Required []string `json:"required"`
	// Uppercase lists fields written in capitals on an envelope.
	Uppercase    []string  `json:"uppercase"`
	CityKind     string    `json:"city_kind"`
	DistrictKind *string   `json:"district_kind"`
	Province     *Province `json:"province"`
	Postal       *Postal   `json:"postal"`
}

// Province describes a country's province field.
type Province struct {
	Kind  string   `json:"kind"`
	Codes []string `json:"codes"`
}

// ProvinceInfo is one province.
type ProvinceInfo struct {
	Country string   `json:"country"`
	Local   string   `json:"local"`
	Latin   string   `json:"latin"`
	Aliases []string `json:"aliases"`
}

// Postal holds a country's postal code rules.
type Postal struct {
	Kind      string        `json:"kind"`
	Pattern   string        `json:"pattern"`
	Examples  []string      `json:"examples"`
	Required  bool          `json:"required"`
	Uppercase bool          `json:"uppercase"`
	Strip     string        `json:"strip"`
	Insert    []PostalOp    `json:"insert"`
	Prefix    *PostalPrefix `json:"prefix"`
	MaxLength int           `json:"max_length"`
	InputMode string        `json:"input_mode"`

	re *regexp.Regexp
}

// PostalOp inserts Char after the first After characters, or before the last
// BeforeLast characters, of the compact code.
type PostalOp struct {
	Char           string `json:"char"`
	After          int    `json:"after,omitempty"`
	BeforeLast     int    `json:"before_last,omitempty"`
	OnlyWhenLength []int  `json:"only_when_length,omitempty"`
	OnlyWhenMatch  string `json:"only_when_match,omitempty"`
	UnlessMatch    string `json:"unless_match,omitempty"`
}

// PostalPrefix is written on mail before the code but is not part of it.
type PostalPrefix struct {
	Text     string `json:"text"`
	Required bool   `json:"required"`
}

// Locale holds one language's labels and names.
type Locale struct {
	Labels    map[string]string `json:"labels"`
	Countries map[string]string `json:"countries"`
	Provinces map[string]string `json:"provinces"`
}

var (
	ErrUnknownCountry  = errors.New("atlas: unknown country")
	ErrUnknownLanguage = errors.New("atlas: unknown language")
	ErrNoPostalCode    = errors.New("atlas: country has no postal codes")
	ErrPostalInvalid   = errors.New("atlas: invalid postal code")
)

var (
	loadOnce  sync.Once
	countries map[string]*Country
	provinces map[string]*ProvinceInfo
	aliases   map[string]string
	languages []string
	locales   sync.Map // lang -> *Locale
)

func mustRead(name string, v any) {
	b, err := files.ReadFile(name)
	if err != nil {
		panic(err)
	}
	if err := json.Unmarshal(b, v); err != nil {
		panic(fmt.Errorf("atlas: %s: %w", name, err))
	}
}

func load() {
	loadOnce.Do(func() {
		mustRead("data/countries.json", &countries)
		mustRead("data/provinces.json", &provinces)
		mustRead("data/languages.json", &languages)
		aliases = map[string]string{}
		for code, c := range countries {
			c.Code = code
			if c.Postal != nil {
				c.Postal.re = regexp.MustCompile("(?i)^(?:" + c.Postal.Pattern + ")$")
			}
		}
		for code, p := range provinces {
			for _, a := range p.Aliases {
				aliases[a] = code
			}
		}
	})
}

// Countries returns every country code, sorted.
func Countries() []string {
	load()
	out := make([]string, 0, len(countries))
	for c := range countries {
		out = append(out, c)
	}
	sort.Strings(out)
	return out
}

// Get returns a country's rules.
func Get(code string) (*Country, error) {
	load()
	if c, ok := countries[strings.ToUpper(code)]; ok {
		return c, nil
	}
	return nil, ErrUnknownCountry
}

// Languages returns every supported language code.
func Languages() []string { load(); return append([]string(nil), languages...) }

// LocaleFor returns one language's labels and names.
func LocaleFor(lang string) (*Locale, error) {
	load()
	if v, ok := locales.Load(lang); ok {
		return v.(*Locale), nil
	}
	b, err := files.ReadFile("data/i18n/" + lang + ".json")
	if err != nil {
		return nil, ErrUnknownLanguage
	}
	var l Locale
	if err := json.Unmarshal(b, &l); err != nil {
		return nil, err
	}
	locales.Store(lang, &l)
	return &l, nil
}

// ProvinceByCode returns a province, resolving a retired code to its successor.
func ProvinceByCode(code string) (string, *ProvinceInfo, bool) {
	load()
	code = strings.ToUpper(code)
	if to, ok := aliases[code]; ok {
		code = to
	}
	p, ok := provinces[code]
	return code, p, ok
}

// NormalizePostal returns the standard written form of a postal code.
func (c *Country) NormalizePostal(input string) (string, error) {
	p := c.Postal
	if p == nil {
		return "", ErrNoPostalCode
	}
	compact := strings.Map(func(r rune) rune {
		if strings.ContainsRune(p.Strip, r) {
			return -1
		}
		return r
	}, strings.TrimSpace(input))
	out := p.apply(compact)
	if !p.re.MatchString(out) && p.Prefix != nil {
		pre := strings.Map(func(r rune) rune {
			if strings.ContainsRune(p.Strip, r) {
				return -1
			}
			return r
		}, p.Prefix.Text)
		if len(compact) > len(pre) && strings.EqualFold(compact[:len(pre)], pre) {
			out = p.apply(compact[len(pre):])
		}
	}
	if out == "" || !p.re.MatchString(out) {
		return "", ErrPostalInvalid
	}
	return out, nil
}

func (p *Postal) apply(compact string) string {
	s := compact
	if p.Uppercase {
		s = strings.ToUpper(s)
	}
	r := []rune(s)
	n := len(r)
	type cut struct {
		at  int
		sep string
	}
	var cuts []cut
	for _, op := range p.Insert {
		if len(op.OnlyWhenLength) > 0 && !contains(op.OnlyWhenLength, n) {
			continue
		}
		if op.OnlyWhenMatch != "" && !regexp.MustCompile(op.OnlyWhenMatch).MatchString(strings.ToUpper(s)) {
			continue
		}
		if op.UnlessMatch != "" && regexp.MustCompile(op.UnlessMatch).MatchString(strings.ToUpper(s)) {
			continue
		}
		at := op.After
		if op.BeforeLast > 0 {
			at = n - op.BeforeLast
		}
		if at > 0 && at < n {
			cuts = append(cuts, cut{at, op.Char})
		}
	}
	var b strings.Builder
	for i, ch := range r {
		for _, c := range cuts {
			if c.at == i {
				b.WriteString(c.sep)
			}
		}
		b.WriteRune(ch)
	}
	return b.String()
}

func contains(list []int, v int) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// Address is an address in atlas fields. ProvinceCode and CountryCode are codes.
type Address struct {
	FirstName, LastName, Company, Address1, Address2, District, City string
	ProvinceCode, PostalCode, CountryCode, Phone                     string
}

// Format returns the address as printed lines in the given language: the
// country's envelope order, province and country names from that language.
func Format(a Address, lang string) ([]string, error) {
	c, err := Get(a.CountryCode)
	if err != nil {
		return nil, err
	}
	l, err := LocaleFor(lang)
	if err != nil {
		return nil, err
	}
	upper := map[string]bool{}
	for _, f := range c.Uppercase {
		upper[f] = true
	}
	vals := map[string]string{
		"first_name": a.FirstName, "last_name": a.LastName, "company": a.Company,
		"address1": a.Address1, "address2": a.Address2, "district": a.District, "city": a.City,
		"province_code": provincePrinted(c, l, a.ProvinceCode), "postal_code": a.PostalCode,
	}
	envelope := c.Envelope
	if c.EnvelopeLatin != nil && !slices.Contains(c.EnvelopeLanguages, strings.Split(lang, "-")[0]) {
		envelope = c.EnvelopeLatin
	}
	ph := regexp.MustCompile(`\{([a-z_0-9]+)\}`)
	var out []string
	for _, tpl := range envelope {
		line := ph.ReplaceAllStringFunc(tpl, func(m string) string {
			f := m[1 : len(m)-1]
			v := vals[f]
			if upper[f] {
				v = strings.ToUpper(v)
			}
			return v
		})
		line = strings.Join(strings.Fields(line), " ")
		line = strings.Trim(line, " ,-")
		if line != "" {
			out = append(out, line)
		}
	}
	out = append(out, l.Countries[c.Code])
	return out, nil
}

// provincePrinted is a province as an address prints it: the code's suffix
// where postal convention uses it (US-CA prints CA), otherwise its name.
func provincePrinted(c *Country, l *Locale, code string) string {
	code = strings.ToUpper(code)
	if c.ProvincePrint == "code" {
		if i := strings.IndexByte(code, '-'); i > 0 {
			suffix := code[i+1:]
			if strings.Trim(suffix, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") == "" {
				return suffix
			}
		}
	}
	return l.Provinces[code]
}
