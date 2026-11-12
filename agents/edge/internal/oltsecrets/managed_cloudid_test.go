package oltsecrets

import (
	"path/filepath"
	"testing"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/managedolts"
)

func TestARemoveOrSetForAnotherCloudIDNeverTouchesTheOLTOfThatName(t *testing.T) {
	m := newManagedEnv(t, nil)
	m.wantSet(mDelivID, nil, CodeAwaitingLocalTrust)
	m.trust()
	if r := m.process(m.build(spec{id: mDeliv2, olt: mName})); r.Outcome != OutcomeApplied { // credentials into the automatic file
		t.Fatalf("%+v", r)
	}
	creds := m.st.CredsPath(mName)
	reg := m.readFile(filepath.Join(m.dir, managedolts.RegistryFile))
	other := "5a1f3c52-0b6e-4f0e-9a52-00000000beef"

	// a signed remove that names this OLT but ANOTHER Cloud id (an old delivery, a recreated name, an inconsistency in the Cloud): refused, no effect at all
	r := m.send(mDeliv3, mName, `{"kind":"olt_connection","action":"remove","cloud_id":"`+other+`"}`)
	if r.Outcome != OutcomeFailed || r.Code != CodeNameConflict {
		t.Fatalf("%+v", r.Result)
	}
	if !m.item().Trusted || !m.fileExists(creds) || m.readFile(filepath.Join(m.dir, managedolts.RegistryFile)) != reg {
		t.Fatal("a refused remove changed something")
	}
	if tomb, _ := m.st.Tombstones(); len(tomb) != 0 {
		t.Fatalf("a refused remove left a tombstone: %v", tomb)
	}

	// a set under the same name with another Cloud id is another OLT: refused too (the Cloud removes the old one first)
	m.wantRefused(did(700), map[string]any{"cloud_id": other, "address": "10.20.7.7"}, CodeNameConflict)
	if it := m.item(); it.Entry.CloudID != mCloudID || !it.Trusted || it.Entry.Address != "10.20.1.5" {
		t.Fatalf("%+v", it)
	}

	// the right id removes it; and only then is the name free for the new Cloud id (which starts untrusted and without credentials)
	if r := m.send(did(701), mName, `{"kind":"olt_connection","action":"remove","cloud_id":"`+mCloudID+`"}`); r.Outcome != OutcomeApplied || r.Code != "" {
		t.Fatalf("%+v", r.Result)
	}
	m.wantSet(did(702), map[string]any{"cloud_id": other}, CodeAwaitingLocalTrust)
	if it := m.item(); it.Entry.CloudID != other || it.Trusted || m.fileExists(creds) {
		t.Fatalf("%+v", it)
	}
	// and a late duplicate of the remove for the OLD Cloud id cannot remove the recreated one
	r = m.send(did(703), mName, `{"kind":"olt_connection","action":"remove","cloud_id":"`+mCloudID+`"}`)
	if r.Outcome != OutcomeFailed || r.Code != CodeNameConflict || m.item().Entry.CloudID != other {
		t.Fatalf("%+v", r.Result)
	}
}
