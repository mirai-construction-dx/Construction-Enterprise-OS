import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listPartners,
  getPartner,
  createPartner,
  updatePartner,
  listPartnerContacts,
  createPartnerContact,
  listPartnerContracts,
  createPartnerContract,
  listPartnerEvaluations,
  createPartnerEvaluation,
  listPartnerAssignments,
  createPartnerAssignment,
} from "../api/partner";

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

const mockPartner = {
  id: "p1",
  organization_id: "org1",
  name: "ABC Construction",
  partner_type: "subcontractor",
  status: "active" as const,
};

describe("listPartners", () => {
  it("sends GET to /partner without params", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listPartners();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner",
      expect.any(Object),
    );
  });

  it("appends status filter when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listPartners({ status: "active" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("status=active");
  });

  it("appends partner_type filter when provided", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listPartners({ partner_type: "supplier" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("partner_type=supplier");
  });
});

describe("getPartner", () => {
  it("sends GET to /partner/:id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockPartner));
    const result = await getPartner("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1",
      expect.any(Object),
    );
    expect(result.id).toBe("p1");
  });
});

describe("createPartner", () => {
  it("sends POST to /partner", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(mockPartner));
    await createPartner({
      organization_id: "org1",
      name: "ABC Construction",
      partner_type: "subcontractor",
      status: "active",
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("updatePartner", () => {
  it("sends PUT to /partner/:id", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ ...mockPartner, name: "Updated" }),
    );
    await updatePartner("p1", { name: "Updated" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});

describe("listPartnerContacts", () => {
  it("sends GET to /partner/:id/contacts", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listPartnerContacts("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1/contacts",
      expect.any(Object),
    );
  });
});

describe("createPartnerContact", () => {
  it("sends POST to /partner/:id/contacts", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ id: "c1", partner_id: "p1", name: "Taro Yamada" }),
    );
    await createPartnerContact("p1", { name: "Taro Yamada" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1/contacts",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("listPartnerContracts", () => {
  it("sends GET to /partner/:id/contracts", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listPartnerContracts("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1/contracts",
      expect.any(Object),
    );
  });
});

describe("createPartnerContract", () => {
  it("sends POST to /partners/contracts with partner_id in the body", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ id: "ct1", partner_id: "p1", title: "Contract A", contract_type: "service", status: "draft" }),
    );
    await createPartnerContract("p1", {
      title: "Contract A",
      contract_type: "service",
      status: "draft",
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partners/contracts",
      expect.objectContaining({ method: "POST" }),
    );
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({ partner_id: "p1" });
  });
});

describe("listPartnerEvaluations", () => {
  it("sends GET to /partner/:id/evaluations", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listPartnerEvaluations("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partner/p1/evaluations",
      expect.any(Object),
    );
  });
});

describe("createPartnerEvaluation", () => {
  it("sends POST to /partners/evaluations with partner_id in the body", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ id: "e1", partner_id: "p1", score: 4.5 }),
    );
    await createPartnerEvaluation("p1", { score: 4.5 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partners/evaluations",
      expect.objectContaining({ method: "POST" }),
    );
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({ partner_id: "p1" });
  });
});

describe("listPartnerAssignments", () => {
  it("sends GET to /partners/assignments filtered by partner_id", async () => {
    mockFetch.mockReturnValueOnce(mockResponse([]));
    await listPartnerAssignments("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partners/assignments?partner_id=p1",
      expect.any(Object),
    );
  });
});

describe("createPartnerAssignment", () => {
  it("sends POST to /partners/assignments with partner_id in the body", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({ id: "a1", partner_id: "p1", status: "active" }),
    );
    await createPartnerAssignment("p1", { status: "active" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/partners/assignments",
      expect.objectContaining({ method: "POST" }),
    );
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({ partner_id: "p1" });
  });
});
