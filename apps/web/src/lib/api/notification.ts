import { del, get, patch, post, put } from "../api-client";

// Types mirror services/notification/src/schemas/__init__.py.
// Routes: services/notification/src/main.py mounts
//   /api/v1/notifications           (api/notifications.py)
//   /api/v1/notification-templates  (api/templates.py)
// api-client prepends "/api/v1", so paths below are relative to it.
// Notification policies are not implemented by the service, so no client exists.

/** Standard response envelope (APIResponse) returned by the notification service. */
export interface NotificationApiResponse<T> {
  success: boolean;
  data: T;
  error?: { code: string; message: string; details?: unknown[] | null } | null;
  meta?: {
    page?: number | null;
    per_page?: number | null;
    total?: number | null;
    total_pages?: number | null;
  } | null;
}

export interface PaginationMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export type NotificationStatus = "pending" | "sent" | "read" | "failed";
export type NotificationPriority = "low" | "normal" | "high" | "urgent";

export interface Notification {
  id: number;
  template_id: string | null;
  recipient_id: string;
  title: string;
  body: string;
  metadata: Record<string, unknown> | null;
  channels: string[];
  status: NotificationStatus;
  read_at: string | null;
  created_at: string;
}

export interface NotificationList {
  notifications: Notification[];
  pagination: PaginationMeta;
}

export interface NotificationTemplate {
  id: string;
  code: string;
  name: string;
  channels: string[];
  title_template: string;
  body_template: string;
  priority: NotificationPriority;
  category: string;
  created_at: string;
  updated_at: string;
}

export interface NotificationTemplateList {
  templates: NotificationTemplate[];
  pagination: PaginationMeta;
}

export interface NotificationTemplateCreate {
  code: string;
  name: string;
  channels?: string[];
  title_template: string;
  body_template: string;
  priority?: NotificationPriority;
  category: string;
}

export type NotificationTemplateUpdate = Partial<
  Omit<NotificationTemplateCreate, "code">
>;

function withQuery(path: string, q: URLSearchParams) {
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

/** GET /api/v1/notifications — recipient is derived from the access token. */
export function listNotifications(params?: {
  status?: NotificationStatus;
  category?: string;
  page?: number;
  per_page?: number;
}) {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.category) q.set("category", params.category);
  if (params?.page) q.set("page", String(params.page));
  if (params?.per_page) q.set("per_page", String(params.per_page));
  return get<NotificationApiResponse<NotificationList>>(
    withQuery("/notifications", q),
  );
}

/** GET /api/v1/notifications/unread-count */
export function getUnreadCount() {
  return get<NotificationApiResponse<{ unread_count: number }>>(
    "/notifications/unread-count",
  );
}

/** PATCH /api/v1/notifications/{id}/read */
export function markAsRead(id: number) {
  return patch<NotificationApiResponse<Notification>>(
    `/notifications/${id}/read`,
    {},
  );
}

/** PATCH /api/v1/notifications/read-all */
export function markAllAsRead() {
  return patch<NotificationApiResponse<{ marked_read: number }>>(
    "/notifications/read-all",
    {},
  );
}

/** GET /api/v1/notification-templates */
export function listTemplates(params?: {
  category?: string;
  page?: number;
  per_page?: number;
}) {
  const q = new URLSearchParams();
  if (params?.category) q.set("category", params.category);
  if (params?.page) q.set("page", String(params.page));
  if (params?.per_page) q.set("per_page", String(params.per_page));
  return get<NotificationApiResponse<NotificationTemplateList>>(
    withQuery("/notification-templates", q),
  );
}

/** GET /api/v1/notification-templates/{code} */
export function getTemplate(code: string) {
  return get<NotificationApiResponse<NotificationTemplate>>(
    `/notification-templates/${encodeURIComponent(code)}`,
  );
}

/** POST /api/v1/notification-templates */
export function createTemplate(body: NotificationTemplateCreate) {
  return post<NotificationApiResponse<NotificationTemplate>>(
    "/notification-templates",
    body,
  );
}

/** PUT /api/v1/notification-templates/{template_id} */
export function updateTemplate(id: string, body: NotificationTemplateUpdate) {
  return put<NotificationApiResponse<NotificationTemplate>>(
    `/notification-templates/${encodeURIComponent(id)}`,
    body,
  );
}

/** DELETE /api/v1/notification-templates/{template_id} (204 No Content) */
export function deleteTemplate(id: string) {
  return del<void>(`/notification-templates/${encodeURIComponent(id)}`);
}
