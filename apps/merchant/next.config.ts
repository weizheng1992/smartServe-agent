import type { NextConfig } from 'next';

// 服务端 API 已迁移至 gateway-py(FastAPI, 端口 4000)。
// /api/* 与 /spi/* 代理到网关;本地 app/api、app/spi 路由删除后重写自动接管。
const GATEWAY_URL = process.env.GATEWAY_URL ?? 'http://localhost:4000';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['db', 'types', 'tools', 'ui'],
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${GATEWAY_URL}/api/:path*` },
      { source: '/spi/:path*', destination: `${GATEWAY_URL}/spi/:path*` },
    ];
  },
};

export default nextConfig;
