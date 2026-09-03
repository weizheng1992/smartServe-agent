import path from 'path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react-swc';
import { defineConfig } from 'vite';

// 服务端 API 已迁移至 gateway-py(FastAPI, 端口 4000)。
// /api/* 与 /spi/* 由 Vite dev server 代理至网关(替代原 Next.js rewrites)。
const GATEWAY_URL = process.env.GATEWAY_URL ?? 'http://localhost:4000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3005,
    cors: true,
    proxy: {
      '/api': {
        target: GATEWAY_URL,
        changeOrigin: true,
      },
      '/spi': {
        target: GATEWAY_URL,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
