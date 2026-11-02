package olt

import "testing"

func TestProfileInventoryOnlyRunsOnTheReleaseItWasCapturedOn(t *testing.T) {
	for _, q := range []string{"olt.profile.line", "olt.profile.srv", "olt.profile.dba", "olt.profile.traffic"} {
		if !releaseValidatedFor(q, "MA5600V800R015C00") {
			t.Errorf("%s must run on the captured release", q)
		}
		for _, fw := range []string{"MA5600V800R015C99", "MA5600V800R015", "MA5600V800R015C00B1", "MA5600V800R018C10", ""} {
			if releaseValidatedFor(q, fw) {
				t.Errorf("%s must be refused on %q", q, fw)
			}
		}
	}
	if !releaseValidatedFor("olt.version", "MA5600V800R015C99") {
		t.Error("the other queries keep the R015 rule")
	}
}
