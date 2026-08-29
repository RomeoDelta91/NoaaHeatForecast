import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Relative asset paths keep the build host-agnostic: the same dist/ folder
// works on GitHub Pages, in a WordPress subfolder, or inside an iframe.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: 'dist', assetsDir: 'assets', chunkSizeWarningLimit: 900 },
});
