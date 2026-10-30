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
export type Member = { user_id: string; email: string; display_name: string; role: string; mfa_enabled: boolean; is_self: boolean; can_change_role?: boolean };
export type MemberList = { can_reset_mfa: boolean; can_manage_roles?: boolean; members: Member[] };
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

export type OfflineBasis = "transition_observed" | "olt_reported" | "since_last_online";
export type OfflineOnu = {
  onu_id: string; serial: string; olt: string; pon_path: string | null; status: "offline" | "los" | "dying_gasp"; offline_since: string; offline_hours: number;
  basis: OfflineBasis; last_online_at: string | null; observed_at: string | null; olt_observed_at: string | null; freshness: string;
  drops_30d?: number; offline_hours_30d?: number;
};
export type OfflineOnuReport = {
  generated_at: string; criteria: { min_hours: number; olt_id: string | null; pon_path: string | null; include_stale: boolean };
  excluded: { stale: number; unknown_start: number }; truncated: boolean; count: number; items: OfflineOnu[];
};
export type CpeBinding = { protocol: string; connector_id: string; external_id: string };
export type Cpe = { id: string; canonical_serial: string; vendor: string | null; model: string | null; firmware: string | null; bindings: CpeBinding[]; observed_at: string | null; freshness: string };
export type CpeMetric = { metric: string; scope: string; value: unknown; captured_at: string; received_at: string; age_seconds: number; fresh: boolean };
export type CpeStateView = { cpe_id: string; source: string; metrics: CpeMetric[] };
export type OnuCpeLink = { id: string; status: "suggested" | "confirmed" | "rejected"; confidence: number; onu: { id: string; serial: string }; cpe: { id: string; canonical_serial: string } };
export type EdgeRow = { id: string; name: string; site_name: string | null; version: string | null; last_heartbeat_at: string | null; status: "online" | "offline" | "unknown" | "revoked" };
export type PermissionInfo = { name: string; risk: "R0" | "R1" | "R2" | "R3"; description: string };
export type RoleInfo = { role: string; label: string; assignable_by_me: boolean; permissions: PermissionInfo[] };
export type RoleList = { roles: RoleInfo[] };
export type MeInfo = { id: string; kind: string; tenant_id: string; role: string; mfa_recent?: { enforced: boolean; window_seconds: number; satisfied: boolean }; permissions: PermissionInfo[] };
export type RoleChange = {
  id: string; at: string; from: string | null; to: string | null; reason: string | null; revoked_sessions: number | null;
  actor: { id: string | null; name: string | null; email: string | null }; target: { id: string; name: string | null; email: string | null };
};
export type RoleHistory = { truncated: boolean; items: RoleChange[] };

export type PlatformDelegation = {
  id: string; delegate_email: string; delegate_name: string; granted_by_email: string; reason: string;
  created_at: string; expires_at: string; revoked_at: string | null; status: "active" | "expired" | "revoked";
};
export type PlatformDelegationList = { can_delegate: boolean; max_hours: number; items: PlatformDelegation[] };

export type CpeAction = {
  operation: string; label: string; risk: string; needs_params: boolean; offered: boolean; reason: string | null;
  certification: string; status: string; homologated: boolean; bench_target: boolean;
};
export type CpeActions = { cpe_id: string; items: CpeAction[] };

export type BenchAuthorization = {
  id: string; operation: string; cpe_id: string; state: "open" | "consumed" | "revoked"; live: boolean;
  window_start: string; window_end: string; via: "owner_cli" | "api"; mine: boolean; by: string | null;
};
export type BenchAuthorizations = { can_authorize: boolean; operations: string[]; items: BenchAuthorization[] };

export type TeamMember = {
  user_id: string; email: string; name: string; role: string; role_label: string; role_summary: string; mfa_enabled: boolean; is_self: boolean;
  can_change_role: boolean; can_remove: boolean; can_reset_password: boolean;
};
export type TeamInvite = { id: string; email: string; name: string | null; role: string; role_label: string; created_at: string; expires_at: string; by: string | null; expired: boolean };
export type TeamRole = { role: string; label: string; summary: string; can: string[]; cannot: string[]; assignable_by_me: boolean };
export type Team = {
  me: { id: string; role: string; role_label: string; can_manage: boolean; assignable_roles: string[] };
  summary: { active: number; pending_invites: number; without_mfa: number };
  members: TeamMember[]; invites: TeamInvite[]; roles: TeamRole[];
  capabilities: { groups: { id: string; label: string }[]; matrix: Record<string, Record<string, "all" | "some" | "none">> };
};
export type TeamActivityItem = {
  id: string; kind: string; at: string; actor: string | null; target: string | null; email: string | null; from: string | null; to: string | null;
  reason: string | null; hours: number | null; operation: string | null; from_label: string | null; to_label: string | null;
};
export type TeamActivity = { truncated: boolean; items: TeamActivityItem[] };
export type InvitePreview =
  | { state: "invalid" | "used" | "revoked" | "expired" }
  | { state: "valid"; purpose: "invite" | "reset"; tenant_name: string; email: string; name: string | null; role_label: string | null; inviter: string | null; expires_at: string; account_exists: boolean };

export type OnuHistory = {
  onu_id: string; truncated: boolean;
  summary: { window_days: number; offline_hours: number; drops: number; known_hours: number; availability_pct: number | null };
  events: { id: string; from: string | null; to: string; at: string; baseline: boolean }[];
};
