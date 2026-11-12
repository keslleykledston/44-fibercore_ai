package oltsecrets

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/config"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/credfile"
	"github.com/keslleykledston/44-fibercore_ai/agents/edge/internal/gateway"
)

// fakeCloud implements the Cloud side of the ADR-0045 contract: seal-key, next (200 / 204 / 429 / 503, the SAME delivery with the SAME lease while it is dispatched) and
// result (lease_token must be the current attempt's, otherwise 409 stale_lease).
type fakeCloud struct {
	t  *testing.T
	mu sync.Mutex

	pending    []*gateway.SecretDelivery
	dispatched *gateway.SecretDelivery
	lease      int

	sealKeys  []string
	nextCalls int
	results   []map[string]string
	rawBodies []string

	sealStatus     int // 0 = 204
	next503        int
	next429        int
	staleOnce      bool // the first result is answered 409 and the lease rotates (the Cloud re-leased meanwhile)
	loseResultOnce bool // the result is NOT recorded and the answer is a 503 (response/processing lost)
}

func (f *fakeCloud) token() string { return "lease-" + string(rune('A'+f.lease)) }

func (f *fakeCloud) handler(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch {
	case r.URL.Path == "/v1/auth/service-token":
		json.NewEncoder(w).Encode(map[string]string{"access_token": "tok"})
	case r.Header.Get("Authorization") != "Bearer tok":
		w.WriteHeader(401)
	case r.URL.Path == "/v1/edge/seal-key" && r.Method == http.MethodPost:
		var b map[string]string
		json.NewDecoder(r.Body).Decode(&b)
		f.sealKeys = append(f.sealKeys, b["public_key"])
		if f.sealStatus != 0 {
			w.WriteHeader(f.sealStatus)
			return
		}
		w.WriteHeader(204)
	case r.URL.Path == "/v1/edge/secret-deliveries/next" && r.Method == http.MethodGet:
		f.nextCalls++
		if f.next429 > 0 {
			f.next429--
			w.Header().Set("Retry-After", "2")
			w.WriteHeader(429)
			return
		}
		if f.next503 > 0 {
			f.next503--
			w.Header().Set("Retry-After", "5")
			w.WriteHeader(503)
			return
		}
		if f.dispatched == nil && len(f.pending) > 0 {
			f.dispatched, f.pending = f.pending[0], f.pending[1:]
			f.lease++
		}
		if f.dispatched == nil {
			w.WriteHeader(204)
			return
		}
		d := *f.dispatched
		d.LeaseToken = f.token()
		json.NewEncoder(w).Encode(d)
	case strings.HasPrefix(r.URL.Path, "/v1/edge/secret-deliveries/") && strings.HasSuffix(r.URL.Path, "/result") && r.Method == http.MethodPost:
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/edge/secret-deliveries/"), "/result")
		var b map[string]string
		json.NewDecoder(r.Body).Decode(&b)
		if f.staleOnce {
			f.staleOnce = false
			f.lease++ // the lease expired and the Cloud handed the same delivery out again
			w.WriteHeader(409)
			w.Write([]byte(`{"detail":"stale_lease"}`))
			return
		}
		if f.dispatched == nil || f.dispatched.ID != id || b["lease_token"] != f.token() {
			w.WriteHeader(409)
			w.Write([]byte(`{"detail":"stale_lease"}`))
			return
		}
		if f.loseResultOnce {
			f.loseResultOnce = false
			w.WriteHeader(503)
			return
		}
		f.results = append(f.results, b)
		f.dispatched = nil
		w.WriteHeader(204)
	default:
		w.WriteHeader(404)
	}
}

type loop struct {
	e      *env
	cloud  *fakeCloud
	gw     *gateway.Client
	worker *Worker
	clock  time.Time
}

func newLoop(t *testing.T) *loop {
	e := newEnv(t)
	f := &fakeCloud{t: t}
	srv := httptest.NewServer(http.HandlerFunc(f.handler))
	t.Cleanup(srv.Close)
	gw := gateway.New(srv.URL, "cid", "sec", srv.Client())
	l := &loop{e: e, cloud: f, gw: gw, clock: time.Unix(1_800_000_000, 0)}
	l.worker = &Worker{Cloud: gw, Proc: e.proc, Log: e.proc.Log, Now: func() time.Time { return l.clock }}
	return l
}

// tick advances the worker's clock past MinGap and runs one round.
func (l *loop) tick() {
	l.clock = l.clock.Add(MinGap + time.Second)
	l.worker.Tick(context.Background())
}

func (l *loop) enqueue(s spec) { l.cloud.pending = append(l.cloud.pending, l.e.build(s)) }

func TestLoopPublishesTheKeyOnceAndAppliesADelivery(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.tick()
	if len(l.cloud.sealKeys) != 1 || l.cloud.sealKeys[0] != l.e.key.PublicB64() {
		t.Fatalf("seal keys: %v", l.cloud.sealKeys)
	}
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" || l.cloud.results[0]["lease_token"] != "lease-B" {
		t.Fatalf("results: %v", l.cloud.results)
	}
	if _, ok := l.cloud.results[0]["code"]; ok {
		t.Fatal("an applied result carries no code")
	}
	c, found, err := credfile.Read(l.e.credPath)
	if err != nil || !found || c.Username != tUser || c.Password != tPass {
		t.Fatalf("%+v %v %v", c, found, err)
	}
	l.tick() // 204 now; the key is not published again
	l.tick()
	if len(l.cloud.sealKeys) != 1 {
		t.Fatalf("the key must not be re-sent every round: %d", len(l.cloud.sealKeys))
	}
}

func TestLoopRepublishesTheKeyEventually(t *testing.T) {
	l := newLoop(t)
	l.tick()
	l.clock = l.clock.Add(RepublishEvery)
	l.worker.Tick(context.Background())
	if len(l.cloud.sealKeys) != 2 {
		t.Fatalf("%d", len(l.cloud.sealKeys))
	}
}

func TestLoopMinGapAbsorbsTheDoubleTrigger(t *testing.T) {
	l := newLoop(t)
	l.tick()
	calls := l.cloud.nextCalls
	l.worker.Tick(context.Background()) // right after: the clock did not move
	if l.cloud.nextCalls != calls {
		t.Fatal("a second trigger within MinGap must do nothing")
	}
}

func TestLoopTransient503OnNextIsNotAFailureOfTheDelivery(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.cloud.next503 = 2
	l.tick()
	l.tick()
	if len(l.cloud.results) != 0 || l.e.fileExists(l.e.credPath) {
		t.Fatal("nothing may be reported or written while the Cloud answers 503")
	}
	l.tick()
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" {
		t.Fatalf("%v", l.cloud.results)
	}
}

func TestLoopRespectsA429AndTheIntakeBudgetWait(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.cloud.next429 = 1
	l.tick()
	if l.gw.SecretsWaitUntil().Before(time.Now()) {
		t.Fatal("the 429 must open the wait window")
	}
	calls := l.cloud.nextCalls
	l.tick() // the real wait (>= 1 s) has not passed: no call at all
	if l.cloud.nextCalls != calls {
		t.Fatal("no call while the Cloud asked us to wait")
	}
	// the secrets wait never holds back the delivery of snapshots (its own window)
	if !l.gw.ThrottledUntil().IsZero() {
		t.Fatal("the intake-budget window must not be touched by a 429 of the secrets routes")
	}
	// and the existing intake-budget wait is respected too
	l.gw.ResetThrottleForTest()
	l.gw.ThrottleForTest(time.Hour)
	l.tick()
	if l.cloud.nextCalls != calls {
		t.Fatal("no call while the intake budget wait is open")
	}
	if len(l.cloud.results) != 0 {
		t.Fatal("a 429 is not a failure of the delivery")
	}
}

func TestLoopStaleLeaseAsksAgainAndTheRedeliveryIsAnsweredApplied(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.cloud.staleOnce = true
	l.tick()
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" || l.cloud.results[0]["lease_token"] != "lease-C" {
		t.Fatalf("the result must arrive with the NEW lease: %v", l.cloud.results)
	}
	// the file was written once; the redelivery landed in step 3
	if applied, _, _ := l.e.store.Check(tDelivery, tOLT, config.KindSSHLogin, l.e.exp); !applied {
		t.Fatal("recorded")
	}
}

func TestLoopLostResultIsReportedAgainWithoutWritingTwice(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.cloud.loseResultOnce = true
	l.tick() // applied, but the report got a 503
	if len(l.cloud.results) != 0 {
		t.Fatal("the Cloud has not recorded it yet")
	}
	before := l.e.readFile(l.e.credPath)
	// anything that wrote again would now fail
	l.e.proc.AfterWrite = func() error { t.Error("the delivery was written a second time"); return nil }
	l.tick() // next returns the SAME dispatched delivery (same lease): step 3, applied
	if len(l.cloud.results) != 1 || l.cloud.results[0]["outcome"] != "applied" {
		t.Fatalf("%v", l.cloud.results)
	}
	if l.e.readFile(l.e.credPath) != before {
		t.Fatal("rewritten")
	}
}

func TestLoopReportsEveryFailureCodeWithTheLease(t *testing.T) {
	l := newLoop(t)
	forged := l.e.build(spec{id: "33333333-3333-4333-8333-333333333391"})
	forged.Signature = ""
	l.cloud.pending = append(l.cloud.pending, forged)
	l.enqueue(spec{id: "33333333-3333-4333-8333-333333333392", olt: "OUTRA"})
	l.enqueue(spec{id: "33333333-3333-4333-8333-333333333393", keyID: "0123456789abcdef"})
	l.tick()
	if len(l.cloud.results) != 3 {
		t.Fatalf("%v", l.cloud.results)
	}
	for i, want := range []string{CodeBadSignature, CodeTargetNotConfigured, CodeBadKeyID} {
		r := l.cloud.results[i]
		if r["outcome"] != "failed" || r["code"] != want || r["lease_token"] == "" {
			t.Errorf("%d: %v", i, r)
		}
	}
	if l.e.fileExists(l.e.credPath) {
		t.Fatal("nothing may be written")
	}
}

func TestLoopCloudRefusingTheKeyStopsPollingAndBacksOff(t *testing.T) {
	l := newLoop(t)
	l.cloud.sealStatus = 403 // feature off for this provider
	l.enqueue(spec{})
	l.tick()
	if l.cloud.nextCalls != 0 || len(l.cloud.sealKeys) != 1 {
		t.Fatalf("no polling without a published key: next=%d keys=%d", l.cloud.nextCalls, len(l.cloud.sealKeys))
	}
	l.tick() // inside RefusedBackoff: not even the key again
	if len(l.cloud.sealKeys) != 1 {
		t.Fatal("must wait before asking again")
	}
	l.cloud.sealStatus = 0
	l.clock = l.clock.Add(RefusedBackoff)
	l.worker.Tick(context.Background())
	if len(l.cloud.sealKeys) != 2 || len(l.cloud.results) != 1 {
		t.Fatalf("keys=%d results=%v", len(l.cloud.sealKeys), l.cloud.results)
	}
}

func TestLoopSeal503RetriesNextRound(t *testing.T) {
	l := newLoop(t)
	l.cloud.sealStatus = 503
	l.tick()
	l.cloud.sealStatus = 0
	l.tick()
	if len(l.cloud.sealKeys) != 2 {
		t.Fatalf("%d", len(l.cloud.sealKeys))
	}
}

func TestLoopWhatTheCloudSeesCarriesNoSecret(t *testing.T) {
	l := newLoop(t)
	l.enqueue(spec{})
	l.enqueue(spec{id: "33333333-3333-4333-8333-333333333394", kind: config.KindSNMPCommunity})
	l.tick()
	all := strings.Join(l.cloud.sealKeys, "|")
	for _, r := range l.cloud.results {
		b, _ := json.Marshal(r)
		all += string(b)
	}
	for _, s := range []string{tUser, tPass, tCommunity} {
		if strings.Contains(all, s) || strings.Contains(l.e.logs.String(), s) {
			t.Fatalf("a secret reached the Cloud or the log: %q", s)
		}
	}
	if strings.Contains(all, "BEGIN") || strings.Contains(all, "private") {
		t.Fatal("key material")
	}
}

// The delivery loop runs while the collection reads the credentials file at the start of its own sessions: it never sees a partial file.
func TestLoopRunsConcurrentlyWithSessionsReadingTheFile(t *testing.T) {
	l := newLoop(t)
	oltCfg := config.OLTConfig{Name: tOLT, CredentialsFile: l.e.credPath, Username: "static", SecretFile: "/nonexistent"}
	for i := 0; i < 8; i++ {
		l.enqueue(spec{id: "33333333-3333-4333-8333-33333333340" + string(rune('0'+i)), exp: l.e.exp + int64(i),
			plaintext: `{"kind":"ssh_login","username":"u` + string(rune('0'+i)) + `","password":"p` + string(rune('0'+i)) + `"}`})
	}
	stop := make(chan struct{})
	var wg sync.WaitGroup
	var bad string
	var mu sync.Mutex
	for r := 0; r < 4; r++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				if !l.e.fileExists(l.e.credPath) {
					continue // not applied yet: the static source would be used (and here it is absent on purpose)
				}
				u, p, err := oltCfg.SSHLogin()
				if err != nil || u[1:] != p[1:] {
					mu.Lock()
					bad = "session saw: " + u + "/" + p
					mu.Unlock()
					return
				}
			}
		}()
	}
	for i := 0; i < 3; i++ {
		l.tick()
	}
	close(stop)
	wg.Wait()
	if bad != "" {
		t.Fatal(bad)
	}
	if len(l.cloud.results) != 8 {
		t.Fatalf("%d results", len(l.cloud.results))
	}
}
