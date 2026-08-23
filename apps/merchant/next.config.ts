import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['db', 'types', 'tools', 'ui'],
};

export default nextConfig;
