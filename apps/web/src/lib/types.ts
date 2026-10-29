export type Olt = { id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; onu_count: number; observed_at: string | null; freshness: string };
export type Onu = { id: string; olt_id: string; serial: string; pon_path: string | null; status: string; rx_dbm: number | null; observed_at: string | null; freshness: string };
export type Impact = { customers_affected: number | null; source: string; hidden: boolean; members_known: boolean };
export type Incident = { id: string; kind: string; status: string; suspected_cause: string; evidence: { pon_path?: string; onus_observed?: number; onus_down?: number; los?: number; dying_gasp?: number; ratio?: number; chronic_offline?: number }; olt: string; opened_at: string; resolved_at: string | null; acknowledged: boolean; edge_silent: boolean; impact: Impact };
export type NocSummary = { open: number; unacknowledged: number; silent_edges: number; open_suppressed: number; customers_affected: number | null; customers_source: string; customers_hidden: boolean };
export type IncidentList = { truncated: boolean; incidents: Incident[]; alerts: { kind: string; edge: string; last_heartbeat_at: string; note: string }[]; summary: NocSummary };
export type IncidentDetail = Incident & { members_total: number; members_truncated: boolean; members: { id: string; serial: string; status: string; observed_at: string | null }[] };
export type Edge = { id: string; name: string; status: string; last_heartbeat_at: string | null; version: string | null };
export type Mod = { id: string; version: string; status: string; reason: string | null; capabilities: string[]; checked_at: string };
export type Workspace = { tenant_id: string; name: string; role: string };
export type Association = { id: string; status: string; score: number; evidence: { ambiguous_serial?: boolean; conflicts_with_approved?: string | null; match?: string }; onu_serial: string; customer_name: string };
export type Job = { id: string; operation: string; target_type: string; risk: string; status: string; required_approvals: number; blocked_reason: string | null; expires_at: string | null; created_at: string };
export type Provenance = { source: string; observed_at: string | null; quality: "fresh" | "stale" | "unknown" | "conflict" };
export type Onu360 = {
  id: string; serial: string; status: string; rx_dbm: number | null; observed_at: string | null; freshness: string;
  last_online_at: string | null; down_since: string | null; source: string;
  olt: { id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; observed_at: string | null; freshness: string };
  pon: { path: string | null; onus: number; online: number; observed_at: string | null; freshness: string } | null;
  incident: { id: string; kind: string; suspected_cause: string; opened_at: string } | null; incident_hidden: boolean;
  provenance: { state: Provenance; olt: Provenance; pon?: Provenance };
  cpe?: CpeBlock; // só com a flag onu_cpe_links ligada para o provedor
};
export type CpeBlock = {
  link: "confirmed" | "suggested" | "none" | "unavailable"; pending_suggestions: number; has_more_suggestions: boolean; can_review: boolean;
  suggestions: { id: string; confidence: number; rule: string | null; ambiguous: boolean }[];
  device: { id: string; vendor: string | null; model: string | null; firmware: string | null; protocols: string[] } | null;
  provenance: Provenance | null;
};
export type OnuCustomer = { association: "approved" | "suggested" | "none"; pending_suggestions: number; display_name?: string; document_last4?: string | null; contract_status?: string };
export type Member = { user_id: string; email: string; display_name: string; role: string; mfa_enabled: boolean; is_self: boolean };
export type MemberList = { can_reset_mfa: boolean; members: Member[] };
export type Capability = { name: string; protocol: string; status: "supported" | "unsupported" | "unknown"; certification: "identified" | "observed" | "certified"; vendor: string | null; model: string | null; firmware: string | null; writes: boolean; blocked_reason: string | null; verified_at: string | null; evidence_ref: string | null };
export type CustomerOnu = {
  id: string; pon_id: string | null; serial: string; status: string; rx_dbm: number | null; olt: string; pon_path: string | null; provenance: Provenance;
  incident: { suspected_cause: string } | null; incident_hidden: boolean; cpe: CpeBlock;
};
export type CustomerContext = {
  customer_id: string; status: "complete" | "partial" | "stale" | "unknown"; onus_truncated: boolean;
  customer: { display_name: string; document_last4: string | null; contract_status: string; provenance: Provenance };
  onus: CustomerOnu[];
};
export type CustomerRow = { id: string; display_name: string; document_last4: string | null; contract_status: string };
export type TenantFeature = { feature: string; enabled: boolean; source: string };
export type DiagnosticFinding = {
  finding_id: string; status: "observed" | "inferred" | "unknown"; hypothesis: string | null; reason?: string; suspected_cause?: string;
  evidence: { pon_path: string; onus_observed: number; onus_down_recent: number; online: number; los: number; dying_gasp: number; chronic_offline: number; ratio: number };
  requires_human_confirmation: boolean; next_read_action: string; rule_id: string; rule_version: number;
};
export type DiagnosticRun = { run_id: string; rule_id: string; rule_version: number; scope: { onu_id: string | null; pon_id: string | null }; created_at: string; findings: DiagnosticFinding[]; reproducible: boolean | null };

