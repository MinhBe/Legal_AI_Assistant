import type { NextConfig } from "next";

/* Bản gộp một máy chủ (HF Space): giao diện và API cùng một địa chỉ. API_INTERNAL_URL trỏ tới
   uvicorn trong cùng container; trình duyệt gọi /api/* cùng origin, Next chuyển tiếp. */
const internal = process.env.API_INTERNAL_URL;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(internal
    ? { async rewrites() { return [{ source: "/api/:path*", destination: `${internal}/api/:path*` }]; } }
    : {}),
};

export default nextConfig;
