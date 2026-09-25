import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react-swc';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    cors: true,
    proxy: {
      '/api': {
        // E2E_GATEWAY_TARGET:熔断 E2E 用独立网关(死 LLM 注入)时覆写代理目标
        target: process.env.E2E_GATEWAY_TARGET ?? 'http://localhost:4000',
        changeOrigin: true,
      },
      '/ws': {
        target: (process.env.E2E_GATEWAY_TARGET ?? 'http://localhost:4000').replace('http', 'ws'),
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
