import type { NextConfig } from 'next';

// 生产（Docker）构建时由 Dockerfile 传入 http://api:8000（compose 服务名）；
// 本地开发保持默认值，且开发时前端直连 8300、不经反代，该值不生效。
const INTERNAL_API_URL = process.env.INTERNAL_API_URL || 'http://localhost:8300';

const nextConfig: NextConfig = {
  output: 'standalone',
  eslint: {
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    // 生产模式前端与 API 同源：浏览器请求 /api/* 由 Next 服务端转发到后端容器
    return [{ source: '/api/:path*', destination: `${INTERNAL_API_URL}/api/:path*` }];
  },
};

export default nextConfig;
