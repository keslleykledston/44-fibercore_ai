export type Olt = { id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; onu_count: number; observed_at: string | null; freshness: string };
export type Onu = { id: string; olt_id: string; serial: string; pon_path: string | null; status: string; rx_dbm: number | null; observed_at: string | null; freshness: string };
export type Incident = { id: string; kind: string; status: string; suspected_cause: string; evidence: { pon_path?: string; onus_observed?: number; onus_down?: number; los?: number; dying_gasp?: number; ratio?: number }; olt: string; opened_at: string; resolved_at: string | null; acknowledged: boolean; edge_silent: boolean };
export type IncidentList = { incidents: Incident[]; alerts: { kind: string; edge: string; last_heartbeat_at: string; note: string }[] };
export type Edge = { id: string; name: string; status: string; last_heartbeat_at: string | null; version: string | null };
export type Mod = { id: string; version: string; status: string; reason: string | null; capabilities: string[]; checked_at: string };
export type Workspace = { tenant_id: string; name: string; role: string };
export type Association = { id: string; status: string; score: number; evidence: { ambiguous_serial?: boolean; conflicts_with_approved?: string | null; match?: string }; onu_serial: string; customer_name: string };
export type Job = { id: string; operation: string; target_type: string; risk: string; status: string; required_approvals: number; blocked_reason: string | null; expires_at: string | null; created_at: string };
export type Onu360 = {
  id: string; serial: string; status: string; rx_dbm: number | null; observed_at: string | null; freshness: string;
  last_online_at: string | null; down_since: string | null; source: string;
  olt: { id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; observed_at: string | null; freshness: string };
  pon: { path: string | null; onus: number; online: number } | null;
  incident: { id: string; kind: string; suspected_cause: string; opened_at: string } | null; incident_hidden: boolean;
};
export type OnuCustomer = { association: "approved" | "suggested" | "none"; pending_suggestions: number; display_name?: string; document_last4?: string | null; contract_status?: string };
