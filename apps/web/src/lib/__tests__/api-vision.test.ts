import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  processOcr,
  listOcrResults,
  getOcrResult,
  analyzeImage,
  listImageAnalyses,
  getImageAnalysis,
  createVectorIndex,
  listVectorIndices,
  getVectorIndex,
  updateVectorIndex,
  deleteVectorIndex,
  vectorSearch,
  indexDocuments,
} from "../api/vision";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

const mockOcrResult = {
  id: "ocr1",
  organization_id: "org1",
  language: "ja",
  extracted_text: "サンプルテキスト",
  status: "completed" as const,
};

const mockAnalysis = {
  id: "ana1",
  organization_id: "org1",
  file_key: "images/site.jpg",
  analysis_type: "defect_detection",
  status: "completed" as const,
};

const mockIndex = {
  id: "idx1",
  organization_id: "org1",
  collection_name: "documents",
  dimension: 1536,
  index_type: "hnsw",
  metric: "cosine",
  document_count: 0,
  total_vectors: 0,
  is_active: true,
};

// ── OCR ──

describe("processOcr", () => {
  it("sends POST to /ocr/process", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockOcrResult));
    await processOcr({ organization_id: "org1", file_key: "docs/invoice.pdf" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/ocr/process",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("listOcrResults", () => {
  it("sends GET to /ocr/results without params", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listOcrResults();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/ocr/results",
      expect.any(Object),
    );
  });

  it("appends status filter when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listOcrResults({ status: "completed" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("status=completed");
  });

  it("appends organization_id when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listOcrResults({ organization_id: "org1" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("organization_id=org1");
  });
});

describe("getOcrResult", () => {
  it("sends GET to /ocr/results/:id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockOcrResult));
    const result = await getOcrResult("ocr1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/ocr/results/ocr1",
      expect.any(Object),
    );
    expect(result.id).toBe("ocr1");
  });
});

// ── Image AI ──

describe("analyzeImage", () => {
  it("sends POST to /vision/analyze", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockAnalysis));
    await analyzeImage({
      organization_id: "org1",
      file_key: "images/site.jpg",
      analysis_type: "defect_detection",
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vision/analyze",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("listImageAnalyses", () => {
  it("sends GET to /vision/analyses without params", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listImageAnalyses();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vision/analyses",
      expect.any(Object),
    );
  });

  it("appends analysis_type when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listImageAnalyses({ analysis_type: "crack_detection" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("analysis_type=crack_detection");
  });
});

describe("getImageAnalysis", () => {
  it("sends GET to /vision/analyses/:id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockAnalysis));
    const result = await getImageAnalysis("ana1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vision/analyses/ana1",
      expect.any(Object),
    );
    expect(result.id).toBe("ana1");
  });
});

// ── Vector DB ──

describe("createVectorIndex", () => {
  it("sends POST to /vectors/indices", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockIndex));
    await createVectorIndex({
      organization_id: "org1",
      collection_name: "documents",
      dimension: 1536,
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/indices",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("listVectorIndices", () => {
  it("sends GET to /vectors/indices without params", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listVectorIndices();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/indices",
      expect.any(Object),
    );
  });

  it("appends is_active filter when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listVectorIndices({ is_active: true });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("is_active=true");
  });
});

describe("getVectorIndex", () => {
  it("sends GET to /vectors/indices/:id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockIndex));
    const result = await getVectorIndex("idx1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/indices/idx1",
      expect.any(Object),
    );
    expect(result.id).toBe("idx1");
  });
});

describe("updateVectorIndex", () => {
  it("sends PATCH to /vectors/indices/:id", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ ...mockIndex, is_active: false }),
    );
    await updateVectorIndex("idx1", { is_active: false });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/indices/idx1",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});

describe("deleteVectorIndex", () => {
  it("sends DELETE to /vectors/indices/:id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ deleted: true }));
    const result = await deleteVectorIndex("idx1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/indices/idx1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(result.deleted).toBe(true);
  });
});

describe("vectorSearch", () => {
  it("sends POST to /vectors/search", async () => {
    const searchResults = [
      {
        source_id: "doc1",
        source_type: "document",
        chunk_index: 0,
        content: "result",
        similarity: 0.95,
        metadata: {},
      },
    ];
    mockFetch.mockReturnValueOnce(mockResponse(searchResults));
    const results = await vectorSearch({
      index_id: "idx1",
      query_text: "建設工事",
      top_k: 5,
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/search",
      expect.objectContaining({ method: "POST" }),
    );
    expect(results).toHaveLength(1);
  });
});

describe("indexDocuments", () => {
  it("sends POST to /vectors/index", async () => {
    const indexResponse = {
      indexed_count: 2,
      total_vectors: 2,
      documents: [
        {
          source_id: "doc1",
          source_type: "document",
          chunks_indexed: 1,
          status: "completed",
        },
        {
          source_id: "doc2",
          source_type: "document",
          chunks_indexed: 1,
          status: "completed",
        },
      ],
    };
    mockFetch.mockReturnValueOnce(mockResponse(indexResponse));
    const result = await indexDocuments({
      index_id: "idx1",
      documents: [
        { source_id: "doc1", source_type: "document", content: "施工計画書" },
        { source_id: "doc2", source_type: "document", content: "設計図面" },
      ],
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/vectors/index",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.indexed_count).toBe(2);
  });

  it("includes documents array in request body", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ indexed_count: 1, total_vectors: 1, documents: [] }),
    );
    await indexDocuments({
      index_id: "idx1",
      documents: [{ source_id: "doc1", source_type: "document", content: "設計図" }],
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.documents).toHaveLength(1);
    expect(body.index_id).toBe("idx1");
  });
});

// ── 追加パラメータテスト ──

describe("listOcrResults — additional params", () => {
  it("appends document_id when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listOcrResults({ document_id: "doc-abc" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("document_id=doc-abc");
  });

  it("appends skip and limit when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listOcrResults({ skip: 10, limit: 5 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("skip=10");
    expect(url).toContain("limit=5");
  });

  it("returns array with correct shape", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([mockOcrResult]));
    const results = await listOcrResults();
    expect(Array.isArray(results)).toBe(true);
    expect(results[0].extracted_text).toBe("サンプルテキスト");
    expect(results[0].status).toBe("completed");
  });
});

describe("processOcr — optional fields", () => {
  it("includes language and document_id when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockOcrResult));
    await processOcr({
      organization_id: "org1",
      file_key: "docs/report.pdf",
      language: "en",
      document_id: "doc-123",
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.language).toBe("en");
    expect(body.document_id).toBe("doc-123");
  });

  it("returns OcrResult with an id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockOcrResult));
    const result = await processOcr({ organization_id: "org1", file_key: "f.pdf" });
    expect(result.id).toBe("ocr1");
  });
});

describe("listImageAnalyses — additional params", () => {
  it("appends organization_id when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listImageAnalyses({ organization_id: "org2" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("organization_id=org2");
  });

  it("appends skip and limit when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listImageAnalyses({ skip: 0, limit: 20 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("skip=0");
    expect(url).toContain("limit=20");
  });

  it("returns ImageAnalysis with correct analysis_type", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([mockAnalysis]));
    const results = await listImageAnalyses();
    expect(results[0].analysis_type).toBe("defect_detection");
    expect(results[0].status).toBe("completed");
  });
});

describe("listVectorIndices — additional params", () => {
  it("appends organization_id when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listVectorIndices({ organization_id: "org3" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("organization_id=org3");
  });

  it("appends is_active=false when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listVectorIndices({ is_active: false });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("is_active=false");
  });

  it("appends skip and limit when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listVectorIndices({ skip: 5, limit: 10 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("skip=5");
    expect(url).toContain("limit=10");
  });

  it("returns VectorIndex with correct shape", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([mockIndex]));
    const results = await listVectorIndices();
    expect(results[0].collection_name).toBe("documents");
    expect(results[0].is_active).toBe(true);
    expect(results[0].dimension).toBe(1536);
  });
});

describe("createVectorIndex — optional fields", () => {
  it("includes index_type and metric in body when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockIndex));
    await createVectorIndex({
      organization_id: "org1",
      collection_name: "blueprints",
      dimension: 768,
      index_type: "flat",
      metric: "l2",
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.index_type).toBe("flat");
    expect(body.metric).toBe("l2");
  });

  it("returns VectorIndex with is_active true by default", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockIndex));
    const result = await createVectorIndex({
      organization_id: "org1",
      collection_name: "docs",
      dimension: 1536,
    });
    expect(result.is_active).toBe(true);
  });
});

describe("vectorSearch — edge cases", () => {
  it("returns empty array when no results found", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    const results = await vectorSearch({
      index_id: "idx1",
      query_text: "存在しないクエリ",
    });
    expect(results).toHaveLength(0);
  });
});

// ── エラーケーステスト ──

describe("API error handling", () => {
  it("getOcrResult throws ApiError on 404", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ detail: "Not found" }, 404));
    await expect(getOcrResult("missing-id")).rejects.toThrow();
  });

  it("getImageAnalysis throws ApiError on 500", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ detail: "Server error" }, 500));
    await expect(getImageAnalysis("broken-id")).rejects.toThrow();
  });

  it("getVectorIndex throws ApiError on 404", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ detail: "Not found" }, 404));
    await expect(getVectorIndex("no-such-index")).rejects.toThrow();
  });
});
