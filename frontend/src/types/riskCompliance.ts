/**
 * Risk & Compliance checks agent contract (final review-pack check before G4). Mirrors
 * backend/app/agents/risk_compliance/schemas.py - keep in sync. The agent never approves:
 * it only says whether the RM may sign off (`rm_signoff_allowed`).
 */
import type { GateId, GateState } from "./arc";
import type { PaClientProfile } from "./portfolio";

export type RcStatus = "PASS" | "PASS_WITH_CONDITIONS" | "BLOCKED" | "NEEDS_INFO";
export type RcEffect = "BLOCK" | "NEEDS_INFO" | "CONDITION" | "NOTE";

export interface RcAllocationRow { asset_class: string; saa: number; current: number; old_taa: number; new_taa: number; band: number }
export interface RcPackProduct { product_id?: string | null; product_name: string; asset_class?: string | null; weight_pct?: number | null }
export interface RcPackSection { n: number; title: string; owner: "rm" | "pm"; gate: GateId | null; status: "draft" | "ready" | "flagged" | "approved"; text: string; kind?: "signoff" | null }

export interface RcPackRequest {
  request_id?: string; client_id: string; pack_version?: string | null; reference_date: string; policy_version?: string | null;
  client_profile: PaClientProfile;
  allocation: RcAllocationRow[]; products: RcPackProduct[]; sections: RcPackSection[];
  gates: Partial<Record<GateId, GateState>>;
  data_as_of: { profile: string | null; market: string | null };
}

export interface RcFinding {
  code: string; severity: "BLOCKING" | "MATERIAL" | "MINOR"; effect: RcEffect; rule_id: string; policy_version: string | null;
  fields: string[]; observed: number | string | null; threshold: number | string | null; message: string;
}
export interface RcMissing { field: string; severity: "BLOCKING" | "MATERIAL" | "MINOR"; impact: string }
export interface RcConflict { fields: string[]; severity: "BLOCKING" | "MATERIAL" | "INFO"; description: string; resolution: string }

export interface RcPackReport {
  status: RcStatus; rm_signoff_allowed: boolean; request_id: string | null; client_id: string; pack_version: string | null;
  findings: RcFinding[]; missing_information: RcMissing[]; conflicts: RcConflict[];
  inputs_fingerprint: string; policy_id: string | null; policy_version: string | null; computed_at: string;
}
