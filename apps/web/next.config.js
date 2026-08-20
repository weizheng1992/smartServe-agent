/** @type {import('next').NextConfig} */
const nextConfig = {
  serverExternalPackages: [
    "puppeteer-core",
    "@puppeteer/browsers",
    "ioredis",
    "pg",
    "@temporalio/client",
  ],
};

module.exports = nextConfig;
