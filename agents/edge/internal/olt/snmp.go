package olt

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"

	"github.com/gosnmp/gosnmp"
)

// SNMP is read-only by construction: the only operations this file can issue are GET and (BULK)WALK. There is no Set, no
// trap sender and no community/credential in any error text.

// SNMPValue is one varbind, already reduced to what the drivers need.
type SNMPValue struct {
	Int     int64
	Bytes   []byte
	IsInt   bool
	IsBytes bool
	Missing bool // noSuchObject / noSuchInstance / endOfMibView
}

// SNMPRow is one walked varbind: Suffix is the OID below the walked root ("<ifIndex>.<ontId>" style), without a leading dot.
type SNMPRow struct {
	Suffix string
	Value  SNMPValue
}

// SNMPReader is what an SNMP-based driver may use. Walk returns an error unless the subtree was walked to its end, so a nil
// error IS the proof that the listing is complete (SNMP, unlike a CLI, has an unambiguous end of table).
type SNMPReader interface {
	Get(ctx context.Context, oids []string) (map[string]SNMPValue, error)
	Walk(ctx context.Context, root string, maxRows int) ([]SNMPRow, error)
}

// snmpMinPace is a hard floor on the pause between SNMP requests (a variable only so tests can run fast).
var snmpMinPace = time.Second

var (
	ErrSNMPDenied   = errors.New("snmp: destination not in local allowlist or not an IP literal")
	ErrSNMPTooLarge = errors.New("snmp: walk exceeded the row limit (treated as incomplete)")
	ErrSNMPBudget   = errors.New("snmp: request budget exhausted")
)

type SNMPConfig struct {
	Addr      string // "ip:161": must be an IP literal AND listed in the local allowlist (no DNS => no rebinding)
	Community string // v2c community; read-only account; never logged
	Allowed   func(hostport string) bool
	Timeout   time.Duration // per request (default 5s)
	Retries   int           // retransmissions after a timeout, each one paced and budgeted (default 1)
	// Pace is the pause before every request. The OLT's SNMP agent rate-limits: on the measured MA5608T it answers in
	// 20-200 ms, then stops answering ANY request for over a minute after ~17 requests in ~20 s (about 1 request/s). The
	// floor (snmpMinPace) is the fastest rate ever observed to be survivable only in short bursts, NOT a proven-safe
	// sustained rate: values below it are raised to it.
	Pace    time.Duration
	MaxReqs int // total requests per client, i.e. per collection cycle (default 400)
}

type snmpClient struct {
	g    *gosnmp.GoSNMP
	cfg  SNMPConfig
	reqs int
}

// DialSNMP validates the destination, then opens a connected UDP socket. GET/WALK only.
func DialSNMP(ctx context.Context, cfg SNMPConfig) (SNMPReader, func(), error) {
	host, port, err := net.SplitHostPort(cfg.Addr)
	if err != nil || cfg.Allowed == nil || !cfg.Allowed(cfg.Addr) || net.ParseIP(host) == nil || cfg.Community == "" {
		return nil, nil, ErrSNMPDenied
	}
	ip := net.ParseIP(host)
	if ip.IsUnspecified() || ip.IsMulticast() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
		return nil, nil, ErrSNMPDenied
	}
	p, err := strconv.Atoi(port)
	if err != nil || p < 1 || p > 65535 {
		return nil, nil, ErrSNMPDenied
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 5 * time.Second
	}
	if cfg.Retries == 0 {
		cfg.Retries = 1
	}
	if cfg.Pace < snmpMinPace {
		cfg.Pace = snmpMinPace
	}
	if cfg.MaxReqs == 0 {
		cfg.MaxReqs = 400
	}
	g := &gosnmp.GoSNMP{
		Target: host, Port: uint16(p), Community: cfg.Community, Version: gosnmp.Version2c,
		// gosnmp's own retransmission is OFF: it would resend outside the pace and the request budget. Retries are done by
		// do(), which spends one paced, budgeted slot per packet actually sent.
		Timeout: cfg.Timeout, Retries: 0, MaxRepetitions: 10, Context: ctx, Transport: "udp",
	}
	if err := g.Connect(); err != nil {
		return nil, nil, fmt.Errorf("snmp: connect %s: %w", cfg.Addr, errors.New(redact(err.Error(), cfg.Community)))
	}
	return &snmpClient{g: g, cfg: cfg}, func() { g.Conn.Close() }, nil
}

func redact(s, secret string) string {
	if secret == "" {
		return s
	}
	return strings.ReplaceAll(s, secret, "***")
}

func (c *snmpClient) tick(ctx context.Context) error {
	if c.reqs >= c.cfg.MaxReqs {
		return ErrSNMPBudget
	}
	c.reqs++
	select {
	case <-time.After(c.cfg.Pace):
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// do sends ONE request with up to cfg.Retries retransmissions after a timeout. Every packet takes a paced, budgeted slot,
// and the operation's own context (not the one the socket was opened with) bounds the call.
func (c *snmpClient) do(ctx context.Context, fn func() error) error {
	var err error
	for attempt := 0; attempt <= c.cfg.Retries; attempt++ {
		if e := c.tick(ctx); e != nil {
			return e
		}
		c.g.Context = ctx
		if err = fn(); err == nil || ctx.Err() != nil || !isTimeout(err) {
			return err
		}
	}
	return err
}

// scrub keeps our own sentinels (budget, cancellation) matchable and strips the community from anything the library says.
func (c *snmpClient) scrub(err error) error {
	if errors.Is(err, ErrSNMPBudget) || errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	return errors.New(redact(err.Error(), c.cfg.Community))
}

func isTimeout(err error) bool {
	var ne net.Error
	return (errors.As(err, &ne) && ne.Timeout()) || strings.Contains(err.Error(), "timeout")
}

func toValue(pdu gosnmp.SnmpPDU) SNMPValue {
	switch pdu.Type {
	case gosnmp.NoSuchObject, gosnmp.NoSuchInstance, gosnmp.EndOfMibView, gosnmp.Null:
		return SNMPValue{Missing: true}
	case gosnmp.OctetString:
		if b, ok := pdu.Value.([]byte); ok {
			return SNMPValue{Bytes: b, IsBytes: true}
		}
	case gosnmp.Integer, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Counter64, gosnmp.Uinteger32, gosnmp.TimeTicks:
		return SNMPValue{Int: gosnmp.ToBigInt(pdu.Value).Int64(), IsInt: true}
	}
	return SNMPValue{Missing: true}
}

func (c *snmpClient) Get(ctx context.Context, oids []string) (map[string]SNMPValue, error) {
	out := map[string]SNMPValue{}
	for len(oids) > 0 { // at most 10 OIDs per PDU: the agent is weak and large PDUs time out
		n := min(len(oids), 10)
		var res *gosnmp.SnmpPacket
		if err := c.do(ctx, func() (e error) { res, e = c.g.Get(oids[:n]); return e }); err != nil {
			return nil, c.scrub(err)
		}
		if res.Error != gosnmp.NoError {
			return nil, fmt.Errorf("snmp: agent error status %d", res.Error)
		}
		for _, v := range res.Variables {
			out[strings.TrimPrefix(v.Name, ".")] = toValue(v)
		}
		oids = oids[n:]
	}
	return out, nil
}

// Walk is a GETBULK loop driven here (not gosnmp's BulkWalk) so that every request is paced and budgeted and so that the
// ONLY success exit is "the agent answered with an OID outside the subtree or endOfMibView": nil error == complete listing.
func (c *snmpClient) Walk(ctx context.Context, root string, maxRows int) ([]SNMPRow, error) {
	return walkBulk(ctx, root, maxRows, func(ctx context.Context) error { return ctx.Err() }, func(oid string) ([]gosnmp.SnmpPDU, error) {
		var res *gosnmp.SnmpPacket
		if err := c.do(ctx, func() (e error) { res, e = c.g.GetBulk([]string{oid}, 0, 10); return e }); err != nil {
			return nil, c.scrub(err)
		}
		if res.Error != gosnmp.NoError {
			return nil, fmt.Errorf("snmp: agent error status %d", res.Error)
		}
		return res.Variables, nil
	})
}

// walkBulk is the transport-free core of Walk (tested without a network).
func walkBulk(ctx context.Context, root string, maxRows int, tick func(context.Context) error,
	bulk func(oid string) ([]gosnmp.SnmpPDU, error)) ([]SNMPRow, error) {
	root = strings.TrimPrefix(root, ".")
	prefix := root + "."
	var rows []SNMPRow
	cur, prev := root, ""
	for {
		if err := tick(ctx); err != nil {
			return nil, err
		}
		vars, err := bulk(cur)
		if err != nil {
			return nil, err
		}
		if len(vars) == 0 {
			return nil, errors.New("snmp: empty bulk response")
		}
		for _, pdu := range vars {
			name := strings.TrimPrefix(pdu.Name, ".")
			// The ONLY two ways a table ends: the agent says endOfMibView, or the answer is outside the subtree.
			if pdu.Type == gosnmp.EndOfMibView || !strings.HasPrefix(name, prefix) {
				return rows, nil
			}
			v := toValue(pdu)
			if v.Missing { // noSuchObject/noSuchInstance/null/unsupported type INSIDE the table is a broken answer, never an end
				return nil, errors.New("snmp: missing or unsupported value inside the table (not an end of table)")
			}
			if prev != "" && !oidLess(prev, name) {
				return nil, errors.New("snmp: agent returned non-increasing OIDs")
			}
			if len(rows) >= maxRows {
				return nil, ErrSNMPTooLarge
			}
			rows = append(rows, SNMPRow{Suffix: strings.TrimPrefix(name, prefix), Value: v})
			prev, cur = name, name
		}
	}
}

// oidLess compares dotted OIDs numerically, component by component.
func oidLess(a, b string) bool {
	as, bs := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(as) && i < len(bs); i++ {
		x, _ := strconv.ParseUint(as[i], 10, 64)
		y, _ := strconv.ParseUint(bs[i], 10, 64)
		if x != y {
			return x < y
		}
	}
	return len(as) < len(bs)
}
