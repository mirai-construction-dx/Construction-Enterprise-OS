/**
 * ログイン画面のアクセシビリティ / キーボード操作テスト。
 *
 * 重点確認「キーボード操作、画面幅、読取性、利用者への誤認防止」に対応する。
 * - 入力欄がラベルと関連付き、支援技術から名前が取れること
 * - Tab で移動でき、Enter で送信できること
 * - パスワードが平文で露出しないこと
 * - 認証エラーが支援技術へ通知されること（誤認防止）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  login: vi.fn(),
  state: { isLoading: false, error: null as string | null },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/lib/store/auth", () => ({
  useAuthStore: () => ({
    login: mocks.login,
    isLoading: mocks.state.isLoading,
    error: mocks.state.error,
  }),
}));

import LoginPage from "../page";

beforeEach(() => {
  mocks.push.mockReset();
  mocks.login.mockReset();
  mocks.state.isLoading = false;
  mocks.state.error = null;
});

// auto-cleanup に依存すると同一プロセス実行時に DOM が残り、
// 「複数の要素が見つかる」で不安定になるため明示的に破棄する。
afterEach(() => {
  cleanup();
});

describe("ログイン画面 a11y", () => {
  it("入力欄がラベルと関連付いている（読取性）", () => {
    render(<LoginPage />);

    // accessible name で取得できる = label と関連付いている
    expect(screen.getByLabelText("メールアドレス")).toHaveAttribute(
      "type",
      "email",
    );
    expect(screen.getByLabelText("パスワード")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("パスワードは平文で表示されない", () => {
    render(<LoginPage />);
    const password = screen.getByLabelText("パスワード");
    expect(password).toHaveAttribute("type", "password");
  });

  it("Tab で次の入力欄へ移動できる（キーボード操作）", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.tab();
    expect(screen.getByLabelText("メールアドレス")).toHaveFocus();

    await user.tab();
    expect(screen.getByLabelText("パスワード")).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "ログイン" })).toHaveFocus();
  });

  it("Enter キーでフォームを送信できる（キーボード操作）", async () => {
    const user = userEvent.setup();
    mocks.login.mockResolvedValue(undefined);
    render(<LoginPage />);

    await user.type(screen.getByLabelText("メールアドレス"), "test@example.invalid");
    await user.type(screen.getByLabelText("パスワード"), "synthetic-password");
    await user.keyboard("{Enter}");

    expect(mocks.login).toHaveBeenCalledWith(
      "test@example.invalid",
      "synthetic-password",
    );
  });

  it("認証エラーが支援技術へ通知される（誤認防止）", () => {
    mocks.state.error = "メールアドレスまたはパスワードが正しくありません";
    render(<LoginPage />);

    const message = screen.getByText(
      "メールアドレスまたはパスワードが正しくありません",
    );
    const announced = message.closest('[role="alert"], [aria-live]');
    expect(
      announced,
      "エラー表示が role=\"alert\" / aria-live を持たず、スクリーンリーダーに通知されない",
    ).not.toBeNull();
  });

  it("送信中の二重操作を防ぐ（誤認防止・重複送信の抑止）", () => {
    mocks.state.isLoading = true;
    render(<LoginPage />);

    expect(screen.getByRole("button", { name: "ログイン中..." })).toBeDisabled();
  });
});
