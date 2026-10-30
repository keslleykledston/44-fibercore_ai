package olt

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// Read-only query catalog for the Huawei MA56xx R015 CLI (docs/operations/OLT_QUERY_CATALOG.md, ADR-0026).
//
// A query is a typed template: the caller picks an ID and gives INTEGER parameters; the command line is rendered here, never accepted from
// outside. Every template starts with "display ", every parameter is a bounded integer, and the whole line must also match the query's own
// strict pattern before it can reach the session. Queries the runbook lists but nobody has run on this release are Validated=false: the Edge
// refuses them unless an operator enabled that exact ID locally (supervised capture -> sanitised fixture -> parser -> Validated=true).

// Scope says which CLI context a query lives in and which parameters it takes.
type Scope int

const (
	ScopeGlobal Scope = iota // config mode, no parameters
	ScopeSlot                // config mode, <slot>
	ScopePON                 // inside "interface gpon 0/<slot>", <port>
	ScopeONU                 // inside "interface gpon 0/<slot>", <port> <ont-id>
)

// Params are the only inputs a caller controls. Frame is always 0 on a MA5608T.
type Params struct {
	Slot, Port, ONT int
}

const (
	maxSlot = 17
	maxPort = 15
	maxONT  = 127
	// MaxQueryOutput caps what one query may return; larger output is cut and flagged, never silently dropped.
	MaxQueryOutput = 256 << 10
)

// Query is one entry of the catalog.
type Query struct {
	ID        string
	Title     string
	Scope     Scope
	Template  string // "display ..." with %[1]d = slot, %[2]d = port, %[3]d = ont-id where the scope takes them
	Validated bool   // proven on MA5600V800R015C00 against the real OLT (a sanitised fixture exists)
	Runbook   string // runbook section it comes from
}

var queryCatalog = []Query{
	// global
	{"olt.version", "Software, patch e uptime", ScopeGlobal, "display version", true, "3"},
	{"olt.time", "Hora e fuso da OLT", ScopeGlobal, "display time", false, "2"},
	{"olt.board", "Placas e estado", ScopeGlobal, "display board 0", true, "3"},
	{"olt.alarm.active", "Alarmes ativos", ScopeGlobal, "display alarm active all", false, "2"},
	{"olt.alarm.history", "Histórico de alarmes (lista)", ScopeGlobal, "display alarm history all list", false, "2"},
	{"olt.event.history", "Histórico de eventos (lista)", ScopeGlobal, "display event history all list", false, "3"},
	{"olt.autofind", "ONTs detectadas e não confirmadas", ScopeGlobal, "display ont autofind all", false, "2"},
	{"olt.temperature", "Temperatura", ScopeGlobal, "display temperature 0", false, "3"},
	{"olt.sync", "Sincronismo de controladoras", ScopeGlobal, "display data sync state", false, "3"},
	// per slot
	{"slot.board", "Detalhe da placa", ScopeSlot, "display board 0/%[1]d", false, "3"},
	{"slot.cpu", "CPU da placa", ScopeSlot, "display cpu 0/%[1]d", false, "3"},
	{"slot.mem", "Memória da placa", ScopeSlot, "display mem 0/%[1]d", false, "3"},
	// per PON
	{"pon.ont.summary", "Contagem de ONTs da PON", ScopePON, "display ont info summary %[2]d", false, "5"},
	{"pon.ont.info", "ONTs da PON", ScopePON, "display ont info %[2]d all", true, "5"},
	{"pon.ont.optical", "Óptica das ONTs da PON", ScopePON, "display ont optical-info %[2]d all", true, "6"},
	{"pon.port.info", "Informação da porta PON", ScopePON, "display port info %[2]d", false, "6"},
	{"pon.port.state", "Estado da porta PON", ScopePON, "display port state %[2]d", false, "6"},
	{"pon.ont.autofind", "ONTs não confirmadas na PON", ScopePON, "display ont autofind %[2]d", false, "5"},
	// per ONU
	{"onu.info", "ONT", ScopeONU, "display ont info %[2]d %[3]d", false, "7"},
	{"onu.optical", "Óptica da ONT", ScopeONU, "display ont optical-info %[2]d %[3]d", false, "8"},
	{"onu.register", "Registro e causa da última queda", ScopeONU, "display ont register-info %[2]d %[3]d", false, "9"},
	{"onu.alarm", "Alarmes da ONT", ScopeONU, "display ont alarm-state %[2]d %[3]d", false, "7"},
	{"onu.version", "Versão da ONT", ScopeONU, "display ont version %[2]d %[3]d", false, "7"},
	{"onu.capability", "Capacidades da ONT", ScopeONU, "display ont capability %[2]d %[3]d", false, "7"},
	{"onu.eth", "Portas Ethernet da ONT", ScopeONU, "display ont port state %[2]d %[3]d eth-port all", false, "10"},
}

var (
	// queryLine is the shape every rendered command must have: "display" plus words and bounded integers. It cannot contain separators,
	// quotes, redirections or a second command.
	queryLine = regexp.MustCompile(`^display [a-z][a-z-]*( ([a-z][a-z-]*|\d{1,3}(/\d{1,3})?))*$`)
	// writeVerbs must never appear in a catalog template (also checked by the tests on the whole catalog).
	writeVerbs = regexp.MustCompile(`(?i)\b(undo|reset|reboot|reload|save|clear|delete|add|modify|set|shutdown|activate|deactivate|upgrade|load|format|ont-?add|commit|quit|return)\b`)
)

var (
	ErrUnknownQuery    = errors.New("olt query: unknown id")
	ErrQueryNotEnabled = errors.New("olt query: not validated on this release and not enabled by the operator")
	ErrBadQueryParams  = errors.New("olt query: parameter out of range")
	ErrQueryFirmware   = errors.New("olt query: only MA5600V800R015 is covered")
	ErrDeviceRejected  = errors.New("olt query: device rejected the command")
	errQueryCatalogBug = errors.New("olt query: catalog entry renders an unsafe command")
	errQueryNoPrompt   = errors.New("olt query: session ended before the command ran")
	_                  = errQueryNoPrompt
)

// QueryByID looks an entry up; the catalog is immutable.
func QueryByID(id string) (Query, bool) {
	for _, q := range queryCatalog {
		if q.ID == id {
			return q, true
		}
	}
	return Query{}, false
}

// Queries returns a copy of the catalog (for listing in UIs and docs).
func Queries() []Query { return append([]Query(nil), queryCatalog...) }

// Plan is a fully validated, rendered query.
type Plan struct {
	Query   Query
	Enter   string // "interface gpon 0/<slot>" or ""
	Command string
}

func inRange(v, hi int) bool { return v >= 0 && v <= hi }

// Render validates the parameters for the query's scope and produces the exact command. Parameters that the scope does not use MUST be zero,
// so a caller cannot smuggle intent through an ignored field.
func (q Query) Render(p Params) (Plan, error) {
	use := map[Scope][3]bool{ScopeGlobal: {}, ScopeSlot: {true, false, false}, ScopePON: {true, true, false}, ScopeONU: {true, true, true}}[q.Scope]
	for i, v := range [3]int{p.Slot, p.Port, p.ONT} {
		hi := [3]int{maxSlot, maxPort, maxONT}[i]
		if (use[i] && !inRange(v, hi)) || (!use[i] && v != 0) {
			return Plan{}, ErrBadQueryParams
		}
	}
	cmd := strings.NewReplacer("%[1]d", strconv.Itoa(p.Slot), "%[2]d", strconv.Itoa(p.Port), "%[3]d", strconv.Itoa(p.ONT)).Replace(q.Template)
	if !queryLine.MatchString(cmd) || writeVerbs.MatchString(cmd) {
		return Plan{}, errQueryCatalogBug
	}
	pl := Plan{Query: q, Command: cmd}
	if q.Scope == ScopePON || q.Scope == ScopeONU {
		pl.Enter = fmt.Sprintf("interface gpon 0/%d", p.Slot)
	}
	return pl, nil
}

// QueryPolicy lists the unvalidated queries an operator enabled locally for a supervised capture. The zero value enables nothing.
type QueryPolicy struct{ Enabled map[string]bool }

func (qp QueryPolicy) permits(q Query) bool { return q.Validated || qp.Enabled[q.ID] }

// allows reports whether cmd is exactly the rendering of some permitted catalog query (used by the driver allowlist).
func (qp QueryPolicy) allows(cmd string) bool {
	if !queryLine.MatchString(cmd) {
		return false
	}
	for _, q := range queryCatalog {
		if !qp.permits(q) {
			continue
		}
		if matchesTemplate(q, cmd) {
			return true
		}
	}
	return false
}

var placeholder = regexp.MustCompile(`%\[(\d)\]d`)

// matchesTemplate accepts cmd only if it is exactly the template with canonical decimal numbers (no leading zeros) inside the SAME
// bounds Render enforces, so the allowlist can never admit a line that Render would have refused.
func matchesTemplate(q Query, cmd string) bool {
	quoted := strings.ReplaceAll(strings.ReplaceAll(regexp.QuoteMeta(q.Template), `\[`, "["), `\]`, "]") // keep %[n]d placeholders intact
	var slots []int                                                                                      // which parameter each capture group is
	pat := placeholder.ReplaceAllStringFunc(quoted, func(m string) string {
		slots = append(slots, int(m[2]-'1'))
		return `(0|[1-9][0-9]{0,2})`
	})
	m := regexp.MustCompile("^" + pat + "$").FindStringSubmatch(cmd)
	if m == nil {
		return false
	}
	bounds := [3]int{maxSlot, maxPort, maxONT}
	for i, idx := range slots {
		n, err := strconv.Atoi(m[i+1])
		if err != nil || n > bounds[idx] {
			return false
		}
	}
	return true
}

// QueryResult is what a query returns. Output is device text, UNPARSED: it may contain customer-chosen strings (ONT descriptions) and must
// not leave the Edge until a parser for that query exists (Validated=true implies one).
type QueryResult struct {
	ID        string
	Output    string
	Truncated bool
}

// RunQuery executes one catalog query on a MA5600 R015 session: display version (identity, checked here), enable, config, [interface gpon 0/<slot>], the command, [quit]. It always
// leaves an opened interface context (best effort) and never sends anything but the rendered command and those mode words.
func (h HuaweiR015) RunQuery(ctx context.Context, s Session, queryID string, p Params) (QueryResult, error) {
	return h.runQuery(ctx, s, queryID, p, []string{"enable", "config"})
}

// RunQueryInConfig is RunQuery for a session the collection of the same round already left in config mode (the R015 snapshot ends there, see
// HuaweiR015.Snapshot): it does not send `enable`/`config` again, which a device already in config mode may refuse. Everything else is identical.
func (h HuaweiR015) RunQueryInConfig(ctx context.Context, s Session, queryID string, p Params) (QueryResult, error) {
	return h.runQuery(ctx, s, queryID, p, nil)
}

func (h HuaweiR015) runQuery(ctx context.Context, s Session, queryID string, p Params, modes []string) (QueryResult, error) {
	q, ok := QueryByID(queryID)
	if !ok {
		return QueryResult{}, ErrUnknownQuery
	}
	if !h.Queries.permits(q) {
		return QueryResult{}, ErrQueryNotEnabled
	}
	plan, err := q.Render(p)
	if err != nil {
		return QueryResult{}, err
	}
	// The device identifies itself through THIS session; a caller-supplied identity would be a claim, not a proof.
	id, err := h.Identify(ctx, s)
	if err != nil {
		return QueryResult{}, err
	}
	if !isR015(id) {
		return QueryResult{}, ErrQueryFirmware
	}
	run := func(cmd string) (string, error) {
		out, err := s.Run(ctx, cmd)
		if err != nil {
			return "", err
		}
		if r015CLIError.MatchString(out) {
			return "", fmt.Errorf("%w: %q", ErrDeviceRejected, cmd)
		}
		return out, nil
	}
	for _, c := range modes {
		if _, err := run(c); err != nil {
			return QueryResult{}, err
		}
	}
	if plan.Enter != "" {
		if _, err := run(plan.Enter); err != nil {
			return QueryResult{}, err
		}
	}
	out, err := run(plan.Command)
	if plan.Enter != "" {
		_, _ = s.Run(ctx, "quit") // leave the interface context even when the query failed; the error that matters is the query's
	}
	if err != nil {
		return QueryResult{}, err
	}
	if Paginated(out) {
		return QueryResult{}, ErrPaginated
	}
	res := QueryResult{ID: q.ID, Output: out}
	if len(res.Output) > MaxQueryOutput {
		res.Output, res.Truncated = res.Output[:MaxQueryOutput], true
	}
	return res, nil
}
