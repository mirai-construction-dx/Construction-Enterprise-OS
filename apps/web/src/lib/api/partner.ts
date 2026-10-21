import { get, post, put } from "../api-client";

export interface Partner {
  id: string;
  organization_id: string;
  name: string;
  partner_type: string;
  registration_number?: string;
  address?: string;
  phone?: string;
  email?: string;
  status: "active" | "inactive" | "suspended";
  rating?: number;
  created_at?: string;
  updated_at?: string;
}

export interface PartnerContact {
  id: string;
  partner_id: string;
  name: string;
  role?: string;
  phone?: string;
  email?: string;
  is_primary?: boolean;
  created_at?: string;
}

export interface PartnerContract {
  id: string;
  partner_id: string;
  title: string;
  contract_type: string;
  amount?: number;
  currency?: string;
  status: "draft" | "active" | "expired" | "terminated";
  start_date?: string;
  end_date?: string;
  created_at?: string;
  updated_at?: string;
}

export interface PartnerEvaluation {
  id: string;
  partner_id: string;
  evaluated_by?: string;
  score: number;
  quality_score?: number;
  delivery_score?: number;
  safety_score?: number;
  comment?: string;
  evaluated_at?: string;
  created_at?: string;
}

export interface PartnerAssignment {
  id: string;
  partner_id: string;
  project_id?: string;
  role?: string;
  status: string;
  start_date?: string;
  end_date?: string;
  created_at?: string;
}

interface ListResponse<T> {
  items: T[];
  total: number;
}

export function listPartners(params?: {
  organization_id?: string;
  status?: string;
  partner_type?: string;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.status) q.set("status", params.status);
  if (params?.partner_type) q.set("partner_type", params.partner_type);
  return get<ListResponse<Partner>>(`/partner${q.toString() ? `?${q}` : ""}`);
}

export function getPartner(id: string) {
  return get<Partner>(`/partner/${id}`);
}

export function createPartner(
  body: Omit<Partner, "id" | "created_at" | "updated_at">,
) {
  return post<Partner>("/partner", body);
}

export function updatePartner(id: string, body: Partial<Partner>) {
  return put<Partner>(`/partner/${id}`, body);
}

export function listPartnerContacts(partnerId: string) {
  return get<PartnerContact[]>(`/partner/${partnerId}/contacts`);
}

export function createPartnerContact(
  partnerId: string,
  body: Omit<PartnerContact, "id" | "partner_id" | "created_at">,
) {
  return post<PartnerContact>(`/partner/${partnerId}/contacts`, body);
}

export function listPartnerContracts(partnerId: string) {
  return get<ListResponse<PartnerContract>>(`/partner/${partnerId}/contracts`);
}

export function createPartnerContract(
  partnerId: string,
  body: Omit<
    PartnerContract,
    "id" | "partner_id" | "created_at" | "updated_at"
  >,
) {
  // 契約はトップレベルのコレクション。相手先はパスではなく本文で指定する。
  return post<PartnerContract>("/partners/contracts", {
    ...body,
    partner_id: partnerId,
  });
}

export function listPartnerEvaluations(partnerId: string) {
  return get<ListResponse<PartnerEvaluation>>(
    `/partner/${partnerId}/evaluations`,
  );
}

export function createPartnerEvaluation(
  partnerId: string,
  body: Omit<PartnerEvaluation, "id" | "partner_id" | "created_at">,
) {
  // 評価もトップレベルのコレクション。partner_id は本文で指定する。
  return post<PartnerEvaluation>("/partners/evaluations", {
    ...body,
    partner_id: partnerId,
  });
}

export function listPartnerAssignments(partnerId: string) {
  // アサインは一覧がトップレベル。相手先はクエリで絞り込む。
  return get<PartnerAssignment[]>(
    `/partners/assignments?partner_id=${encodeURIComponent(partnerId)}`,
  );
}

export function createPartnerAssignment(
  partnerId: string,
  body: Omit<PartnerAssignment, "id" | "partner_id" | "created_at">,
) {
  // 作成もトップレベル。partner_id は本文で指定する。
  return post<PartnerAssignment>("/partners/assignments", {
    ...body,
    partner_id: partnerId,
  });
}
