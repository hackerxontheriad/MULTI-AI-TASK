import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: resolve(__dirname, '../static/landing-tsx'),
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: { input: resolve(__dirname, 'index.html') }
  }
});
