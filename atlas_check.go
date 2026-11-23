//go:build ignore

// Checks every country's examples normalise to themselves and every language
// has every name. Run: go run atlas_check.go
package main

import (
	"fmt"
	"os"

	atlas "github.com/tringify/address-atlas"
)

func main() {
	bad := 0
	for _, cc := range atlas.Countries() {
		c, _ := atlas.Get(cc)
		if c.Postal != nil {
			for _, e := range c.Postal.Examples {
				if got, err := c.NormalizePostal(e); err != nil || got != e {
					fmt.Println(cc, e, got, err)
					bad++
				}
			}
		}
		for _, lang := range atlas.Languages() {
			l, err := atlas.LocaleFor(lang)
			if err != nil || l.Countries[cc] == "" {
				fmt.Println(lang, cc, "missing country name")
				bad++
			}
			if c.Province != nil {
				for _, p := range c.Province.Codes {
					if l.Provinces[p] == "" {
						fmt.Println(lang, p, "missing province name")
						bad++
					}
				}
			}
		}
	}
	if bad > 0 {
		os.Exit(1)
	}
	fmt.Println("ok")
}
