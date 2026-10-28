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
	Retries   int           // default 1
	// Pace is the pause before every request. The OLT's SNMP agent rate-limits: on the measured MA5608T it answers in
	// 20-200 ms, then stops answering ANY request for over a minute after ~17 requests in ~20 s. Default 1s; lower it only
	// after measuring the target.
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
	if cfg.Pace == 0 {
		cfg.Pace = time.Second
	}
	if cfg.MaxReqs == 0 {
		cfg.MaxReqs = 400
	}
	g := &gosnmp.GoSNMP{
		Target: host, Port: uint16(p), Community: cfg.Community, Version: gosnmp.Version2c,
		Timeout: cfg.Timeout, Retries: cfg.Retries, MaxRepetitions: 10, Context: ctx, Transport: "udp",
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
		if err := c.tick(ctx); err != nil {
			return nil, err
		}
		res, err := c.g.Get(oids[:n])
		if err != nil {
			return nil, errors.New(redact(err.Error(), c.cfg.Community))
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
	return walkBulk(ctx, root, maxRows, c.tick, func(oid string) ([]gosnmp.SnmpPDU, error) {
		res, err := c.g.GetBulk([]string{oid}, 0, 10)
		if err != nil {
			return nil, errors.New(redact(err.Error(), c.cfg.Community))
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
			v := toValue(pdu)
			if v.Missing || !strings.HasPrefix(name, prefix) {
				return rows, nil // left the subtree (or endOfMibView): the table is finished
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
