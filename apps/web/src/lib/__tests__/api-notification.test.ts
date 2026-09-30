import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as notificationApi from "../api/notification";
import {
  listNotifications,
  getUnreadCount,
  markAsRead,
  markAllAsRead,
  listTemplates,
  getTemplate,
  createTemplate,
  updateTemplate,
  deleteTemplate,
} from "../api/notification";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
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
    text: () =>
      Promise.resolve(body === undefined ? "" : JSON.stringify(body)),
  });
}

function envelope<T>(data: T) {
  return { success: true, data, error: null, meta: null };
}

const pagination = { page: 1, per_page: 20, total: 0, total_pages: 0 };

const template = {
  id: "7b0c7f0e-0000-4000-8000-000000000001",
  code: "welcome",
  name: "Welcome",
  channels: ["in_app", "email"],
  title_template: "Hi {{name}}",
  body_template: "Welcome, {{name}}",
  priority: "normal",
  category: "system",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function lastCall() {
  const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
  return { url, method: init?.method ?? "GET", body: init?.body };
}

describe("listNotifications", () => {
  it("sends GET to /api/v1/notifications without params", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(envelope({ notifications: [], pagination })),
    );
    const res = await listNotifications();
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notifications");
    expect(method).toBe("GET");
    expect(res.data.notifications).toEqual([]);
    expect(res.data.pagination.total).toBe(0);
  });

  it("appends status / category / page / per_page query params", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(envelope({ notifications: [], pagination })),
    );
    await listNotifications({
      status: "read",
      category: "safety",
      page: 2,
      per_page: 50,
    });
    const url = new URL(lastCall().url, "http://localhost");
    expect(url.pathname).toBe("/api/v1/notifications");
    expect(url.searchParams.get("status")).toBe("read");
    expect(url.searchParams.get("category")).toBe("safety");
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("per_page")).toBe("50");
  });
});

describe("getUnreadCount", () => {
  it("sends GET to /api/v1/notifications/unread-count", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(envelope({ unread_count: 5 })));
    const res = await getUnreadCount();
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notifications/unread-count");
    expect(method).toBe("GET");
    expect(res.data.unread_count).toBe(5);
  });
});

describe("markAsRead", () => {
  it("sends PATCH to /api/v1/notifications/:id/read", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(
        envelope({
          id: 42,
          template_id: null,
          recipient_id: "u1",
          title: "Test",
          body: "Body",
          metadata: null,
          channels: ["in_app"],
          status: "read",
          read_at: "2026-01-01T00:00:00Z",
          created_at: "2026-01-01T00:00:00Z",
        }),
      ),
    );
    const res = await markAsRead(42);
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notifications/42/read");
    expect(method).toBe("PATCH");
    expect(res.data.status).toBe("read");
  });
});

describe("markAllAsRead", () => {
  it("sends PATCH to /api/v1/notifications/read-all", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(envelope({ marked_read: 3 })));
    const res = await markAllAsRead();
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notifications/read-all");
    expect(method).toBe("PATCH");
    expect(res.data.marked_read).toBe(3);
  });
});

describe("listTemplates", () => {
  it("sends GET to /api/v1/notification-templates without params", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(envelope({ templates: [template], pagination })),
    );
    const res = await listTemplates();
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notification-templates");
    expect(method).toBe("GET");
    expect(res.data.templates[0].code).toBe("welcome");
  });

  it("appends category / page / per_page query params", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(envelope({ templates: [], pagination })),
    );
    await listTemplates({ category: "system", page: 3, per_page: 10 });
    const url = new URL(lastCall().url, "http://localhost");
    expect(url.pathname).toBe("/api/v1/notification-templates");
    expect(url.searchParams.get("category")).toBe("system");
    expect(url.searchParams.get("page")).toBe("3");
    expect(url.searchParams.get("per_page")).toBe("10");
  });
});

describe("getTemplate", () => {
  it("sends GET to /api/v1/notification-templates/:code", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(envelope(template)));
    const res = await getTemplate("welcome");
    const { url, method } = lastCall();
    expect(url).toBe("/api/v1/notification-templates/welcome");
    expect(method).toBe("GET");
    expect(res.data.code).toBe("welcome");
  });
});

describe("createTemplate", () => {
  it("sends POST to /api/v1/notification-templates with the create schema body", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(envelope(template), 201));
    const body = {
      code: "welcome",
      name: "Welcome",
      title_template: "Hi {{name}}",
      body_template: "Welcome, {{name}}",
      category: "system",
    };
    await createTemplate(body);
    const call = lastCall();
    expect(call.url).toBe("/api/v1/notification-templates");
    expect(call.method).toBe("POST");
    expect(JSON.parse(call.body as string)).toEqual(body);
  });
});

describe("updateTemplate", () => {
  it("sends PUT to /api/v1/notification-templates/:id", async () => {
    mockFetch.mockReturnValueOnce(
      mockResponse(envelope({ ...template, name: "Updated" })),
    );
    await updateTemplate(template.id, { name: "Updated" });
    const call = lastCall();
    expect(call.url).toBe(`/api/v1/notification-templates/${template.id}`);
    expect(call.method).toBe("PUT");
    expect(JSON.parse(call.body as string)).toEqual({ name: "Updated" });
  });
});

describe("deleteTemplate", () => {
  it("sends DELETE to /api/v1/notification-templates/:id and handles 204", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(undefined, 204));
    const res = await deleteTemplate(template.id);
    const call = lastCall();
    expect(call.url).toBe(`/api/v1/notification-templates/${template.id}`);
    expect(call.method).toBe("DELETE");
    expect(res).toBeUndefined();
  });
});

describe("template id path encoding", () => {
  it("URL-encodes ids in updateTemplate and deleteTemplate", async () => {
    mockFetch.mockReturnValueOnce(mockResponse(envelope(template)));
    await updateTemplate("a/b?c#d", { name: "x" });
    expect(lastCall().url).toBe("/api/v1/notification-templates/a%2Fb%3Fc%23d");

    mockFetch.mockReturnValueOnce(mockResponse(undefined, 204));
    await deleteTemplate("a/b?c#d");
    expect(lastCall().url).toBe("/api/v1/notification-templates/a%2Fb%3Fc%23d");
  });
});

describe("notification policies", () => {
  it("are not exposed because the notification service has no policy API", () => {
    expect(notificationApi).not.toHaveProperty("listPolicies");
    expect(notificationApi).not.toHaveProperty("createPolicy");
    expect(notificationApi).not.toHaveProperty("updatePolicy");
  });
});
