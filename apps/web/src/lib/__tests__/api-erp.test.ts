import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listBudgetItems,
  createBudgetItem,
  updateBudgetItem,
  listCosts,
  createCost,
  approveCost,
  listInvoices,
  getInvoice,
  createInvoice,
  payInvoice,
  listLedger,
  createLedgerEntry,
  getLedgerSummary,
} from "../api/erp";

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

describe("listBudgetItems", () => {
  it("sends GET to /erp/ledger/:ledgerId/budgets without params", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listBudgetItems("l1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger/l1/budgets",
      expect.any(Object),
    );
  });

  it("appends fiscal_year filter", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listBudgetItems("l1", { fiscal_year: 2026, organization_id: "org1" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("/erp/ledger/l1/budgets?");
    expect(url).toContain("fiscal_year=2026");
    expect(url).toContain("organization_id=org1");
  });
});

describe("createBudgetItem", () => {
  it("sends POST to /erp/ledger/:ledgerId/budgets", async () => {
    const item = {
      organization_id: "org1",
      category: "equipment",
      planned_amount: 100000,
      status: "draft",
    };
    mockFetch.mockReturnValueOnce(mockResponse({ id: "b1", ...item }));
    await createBudgetItem("l1", item);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger/l1/budgets",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("updateBudgetItem", () => {
  it("sends PUT to /erp/budgets/:id", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({
        id: "b1",
        organization_id: "org1",
        category: "equipment",
        planned_amount: 120000,
        status: "approved",
      }),
    );
    await updateBudgetItem("b1", { planned_amount: 120000 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/budgets/b1",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});

describe("listCosts", () => {
  it("sends GET to /erp/ledger/:ledgerId/costs", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listCosts("l1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger/l1/costs",
      expect.any(Object),
    );
  });
});

describe("createCost", () => {
  it("sends POST to /erp/ledger/:ledgerId/costs", async () => {
    const cost = {
      organization_id: "org1",
      category: "labor",
      amount: 50000,
      status: "pending" as const,
    };
    mockFetch.mockReturnValueOnce(mockResponse({ id: "c1", ...cost }));
    await createCost("l1", cost);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger/l1/costs",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("approveCost", () => {
  it("sends POST to /erp/costs/:id/approve", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({
        id: "c1",
        organization_id: "org1",
        category: "labor",
        amount: 50000,
        status: "approved" as const,
      }),
    );
    const result = await approveCost("c1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/costs/c1/approve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("approved");
  });
});

describe("listInvoices", () => {
  it("sends GET to /erp/invoices", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listInvoices();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/invoices",
      expect.any(Object),
    );
  });

  it("filters by status", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listInvoices({ status: "overdue" });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("status=overdue");
  });
});

describe("getInvoice", () => {
  it("sends GET to /erp/invoices/:id", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({
        id: "inv1",
        organization_id: "org1",
        invoice_number: "INV-001",
        amount: 10000,
        status: "sent" as const,
      }),
    );
    await getInvoice("inv1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/invoices/inv1",
      expect.any(Object),
    );
  });
});

describe("createInvoice", () => {
  it("sends POST to /erp/invoices", async () => {
    const inv = {
      organization_id: "org1",
      invoice_number: "INV-002",
      amount: 20000,
      status: "draft" as const,
    };
    mockFetch.mockReturnValueOnce(mockResponse({ id: "inv2", ...inv }));
    await createInvoice(inv);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/invoices",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("payInvoice", () => {
  it("sends POST to /erp/invoices/:id/pay", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse({
        id: "inv1",
        organization_id: "org1",
        invoice_number: "INV-001",
        amount: 10000,
        status: "paid" as const,
      }),
    );
    const result = await payInvoice("inv1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/invoices/inv1/pay",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("paid");
  });
});

describe("listLedger", () => {
  it("sends GET to /erp/ledger", async () => {
    mockFetch.mockReturnValueOnce(mockResponse({ items: [], total: 0 }));
    await listLedger();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger",
      expect.any(Object),
    );
  });
});

describe("createLedgerEntry", () => {
  it("sends POST to /erp/ledger", async () => {
    const entry = {
      organization_id: "org1",
      account_code: "1001",
      debit: 10000,
    };
    mockFetch.mockReturnValueOnce(mockResponse({ id: "le1", ...entry }));
    await createLedgerEntry(entry);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("getLedgerSummary", () => {
  it("sends GET to /erp/ledger/:id/summary", async () => {
    const summary = {
      total_budget: 1000000,
      total_actual: 800000,
      variance: 200000,
      variance_pct: 20,
      by_category: {},
    };
    mockFetch.mockReturnValueOnce(mockResponse(summary));
    const result = await getLedgerSummary("le1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/v1/erp/ledger/le1/summary",
      expect.any(Object),
    );
    expect(result.variance_pct).toBe(20);
  });
});
