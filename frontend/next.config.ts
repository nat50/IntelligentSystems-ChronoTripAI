import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.1.22"],
  cacheComponents: true,
  partialPrefetching: true,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
