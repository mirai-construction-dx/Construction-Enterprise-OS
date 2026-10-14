/** @type {import('next').NextConfig} */
// API_GATEWAY (NEXT_PUBLIC_ 接頭辞なし) はサーバー専用。
// 注意: `output: "standalone"` では rewrites() が**ビルド時**に評価され .next/standalone へ
// 焼き込まれるため、Docker の runtime 環境変数では上書きできない（2026-10-14 実測）。
// Docker では apps/web/Dockerfile の ARG API_GATEWAY（compose の build.args）で渡す。
const API_GATEWAY =
  process.env.API_GATEWAY ??
  process.env.NEXT_PUBLIC_API_GATEWAY ??
  "http://localhost:9000";

const nextConfig = {
  transpilePackages: [
    "@construction-enterprise-os/ui",
    "@construction-enterprise-os/core",
  ],
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_GATEWAY}/api/v1/:path*`,
      },
    ];
  },
};
module.exports = nextConfig;
