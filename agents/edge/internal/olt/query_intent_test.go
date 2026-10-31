package olt

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

const testOLT = "8f14e45f-ceea-467a-9a36-4a1b5c3d2e10"

// pinned against the Cloud's own computation (apps/api/app/core/olt_query.py catalog_version(); tests/test_olt_query.py checks the other side)
const pinnedCatalogVersion = "959fdad3e4dc820399aec98bc2a232e35a714136043353424c12a5f67c36e62c"

func intent(t *testing.T, js string) (Intent, error) {
	t.Helper()
	dec := json.NewDecoder(strings.NewReader(js))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		t.Fatal(err)
	}
	return ParseIntent(m)
}

func TestCatalogVersionMatchesTheCloud(t *testing.T) {
	if got := CatalogVersion(); got != pinnedCatalogVersion {
		t.Fatalf("catalog version %s; the Cloud computes %s: the two catalogs drifted", got, pinnedCatalogVersion)
	}
}

func TestParseIntentIsClosedPerScope(t *testing.T) {
	cv := CatalogVersion()
	base := `"olt_ref":"` + testOLT + `","catalog_version":"` + cv + `"`
	ok := map[string]string{
		"olt.version":     `{"query_id":"olt.version",` + base + `}`,
		"slot.cpu":        `{"query_id":"slot.cpu","slot":3,` + base + `}`,
		"pon.ont.info":    `{"query_id":"pon.ont.info","slot":1,"port":0,` + base + `}`,
		"onu.info":        `{"query_id":"onu.info","slot":1,"port":0,"ont":127,` + base + `}`,
		"onu.info/bounds": `{"query_id":"onu.info","slot":17,"port":15,"ont":0,` + base + `}`,
	}
	for name, js := range ok {
		if _, err := intent(t, js); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	bad := map[string]struct {
		js  string
		err error
	}{
		"extra field":       {`{"query_id":"olt.version","slot":1,` + base + `}`, ErrIntentFields},
		"missing field":     {`{"query_id":"slot.cpu",` + base + `}`, ErrIntentFields},
		"unknown field":     {`{"query_id":"olt.version","x":1,` + base + `}`, ErrIntentFields},
		"unknown query":     {`{"query_id":"olt.reboot",` + base + `}`, ErrUnknownQuery},
		"query not string":  {`{"query_id":5,` + base + `}`, ErrUnknownQuery},
		"slot too big":      {`{"query_id":"slot.cpu","slot":18,` + base + `}`, ErrBadQueryParams},
		"negative":          {`{"query_id":"slot.cpu","slot":-1,` + base + `}`, ErrBadQueryParams},
		"string number":     {`{"query_id":"slot.cpu","slot":"1",` + base + `}`, ErrBadQueryParams},
		"float":             {`{"query_id":"slot.cpu","slot":1.0,` + base + `}`, ErrBadQueryParams},
		"exponent":          {`{"query_id":"slot.cpu","slot":1e0,` + base + `}`, ErrBadQueryParams},
		"bool":              {`{"query_id":"slot.cpu","slot":true,` + base + `}`, ErrBadQueryParams},
		"leading zero":      {`{"query_id":"slot.cpu","slot":01,` + base + `}`, nil}, // not even valid JSON: the decoder refuses before the parser
		"another catalog":   {`{"query_id":"olt.version","olt_ref":"` + testOLT + `","catalog_version":"` + pinnedCatalogVersion[:63] + `0"}`, ErrIntentCatalog},
		"olt_ref not uuid":  {`{"query_id":"olt.version","olt_ref":"OLT-1","catalog_version":"` + cv + `"}`, ErrIntentOLT},
		"olt_ref uppercase": {`{"query_id":"olt.version","olt_ref":"8F14E45F-CEEA-467A-9A36-4A1B5C3D2E10","catalog_version":"` + cv + `"}`, ErrIntentOLT},
	}
	for name, c := range bad {
		if c.err == nil {
			continue
		}
		if _, err := intent(t, c.js); !errors.Is(err, c.err) {
			t.Errorf("%s: got %v, want %v", name, err, c.err)
		}
	}
}
