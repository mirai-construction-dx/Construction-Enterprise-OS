import { get, post, patch, del } from "../api-client";

export interface OcrResult {
  id: string;
  organization_id: string;
  document_id?: string | null;
  file_key?: string | null;
  language: string;
  extracted_text: string;
  confidence?: number | null;
  page_count?: number | null;
  processing_time_ms?: number | null;
  entities?: Record<string, unknown>;
  status: "pending" | "processing" | "completed" | "failed";
  error_message?: string | null;
  processed_by?: string | null;
  created_at?: string;
}

export interface ImageAnalysis {
  id: string;
  organization_id: string;
  file_key: string;
  analysis_type: string;
  status: "pending" | "processing" | "completed" | "failed";
  results?: Record<string, unknown>;
  confidence?: number | null;
  processing_time_ms?: number | null;
  created_at?: string;
}

export interface VectorIndex {
  id: string;
  organization_id: string;
  collection_name: string;
  dimension: number;
  index_type: string;
  metric: string;
  document_count: number;
  total_vectors: number;
  is_active: boolean;
  created_at?: string;
}

export interface VectorSearchResult {
  source_id: string;
  source_type: string;
  chunk_index: number;
  content: string;
  similarity: number;
  metadata: Record<string, unknown>;
}

// ── OCR ──

export function processOcr(body: {
  organization_id: string;
  file_key?: string;
  document_id?: string;
  language?: string;
}) {
  return post<OcrResult>("/ocr/process", body);
}

export function listOcrResults(params?: {
  organization_id?: string;
  status?: string;
  document_id?: string;
  skip?: number;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.status) q.set("status", params.status);
  if (params?.document_id) q.set("document_id", params.document_id);
  if (params?.skip !== undefined) q.set("skip", String(params.skip));
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  return get<OcrResult[]>(`/ocr/results${q.toString() ? `?${q}` : ""}`);
}

export function getOcrResult(resultId: string) {
  return get<OcrResult>(`/ocr/results/${resultId}`);
}

// ── Image AI ──

export function analyzeImage(body: {
  organization_id: string;
  file_key: string;
  analysis_type: string;
}) {
  return post<ImageAnalysis>("/vision/analyze", body);
}

export function listImageAnalyses(params?: {
  organization_id?: string;
  analysis_type?: string;
  skip?: number;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.analysis_type) q.set("analysis_type", params.analysis_type);
  if (params?.skip !== undefined) q.set("skip", String(params.skip));
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  return get<ImageAnalysis[]>(`/vision/analyses${q.toString() ? `?${q}` : ""}`);
}

export function getImageAnalysis(analysisId: string) {
  return get<ImageAnalysis>(`/vision/analyses/${analysisId}`);
}

// ── Vector DB ──

export function createVectorIndex(body: {
  organization_id: string;
  collection_name: string;
  dimension: number;
  index_type?: string;
  metric?: string;
}) {
  return post<VectorIndex>("/vectors/indices", body);
}

export function listVectorIndices(params?: {
  organization_id?: string;
  is_active?: boolean;
  skip?: number;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.is_active !== undefined)
    q.set("is_active", String(params.is_active));
  if (params?.skip !== undefined) q.set("skip", String(params.skip));
  if (params?.limit !== undefined) q.set("limit", String(params.limit));
  return get<VectorIndex[]>(`/vectors/indices${q.toString() ? `?${q}` : ""}`);
}

export function getVectorIndex(indexId: string) {
  return get<VectorIndex>(`/vectors/indices/${indexId}`);
}

export function updateVectorIndex(
  indexId: string,
  body: { is_active?: boolean },
) {
  // サービス側は PATCH のみ（PUT は 405）。Issue #125。
  return patch<VectorIndex>(`/vectors/indices/${indexId}`, body);
}

export function deleteVectorIndex(indexId: string) {
  return del<{ deleted: boolean }>(`/vectors/indices/${indexId}`);
}

export function vectorSearch(body: {
  index_id: string;
  query_text: string;
  top_k?: number;
}) {
  return post<VectorSearchResult[]>("/vectors/search", body);
}

export function indexDocuments(body: {
  index_id: string;
  documents: Array<{
    source_id: string;
    source_type: string;
    content: string;
    metadata?: Record<string, unknown>;
  }>;
}) {
  return post<{
    indexed_count: number;
    total_vectors: number;
    documents: Array<{
      source_id: string;
      source_type: string;
      chunks_indexed: number;
      status: string;
    }>;
  }>("/vectors/index", body);
}
