export type Olt = { id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; onu_count: number; observed_at: string | null; freshness: string };
export type Onu = { id: string; olt_id: string; serial: string; pon_path: string | null; status: string; rx_dbm: number | null; observed_at: string | null; freshness: string };
export type Incident = { id: string; kind: string; status: string; suspected_cause: string; evidence: { pon_path?: string; onus_observed?: number; onus_down?: number; los?: number; dying_gasp?: number; ratio?: number }; olt: string; opened_at: string; resolved_at: string | null; acknowledged: boolean; edge_silent: boolean };
export type IncidentList = { incidents: Incident[]; alerts: { kind: string; edge: string; last_heartbeat_at: string; note: string }[] };
export type Edge = { id: string; name: string; status: string; last_heartbeat_at: string | null; version: string | null };
export type Mod = { id: string; version: string; status: string; reason: string | null; capabilities: string[]; checked_at: string };
export type Workspace = { tenant_id: string; name: string; role: string };
