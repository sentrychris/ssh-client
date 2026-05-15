import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { resolve } from 'node:path';

const root = import.meta.dirname;

export default defineConfig({
  root,
  plugins: [
    viteStaticCopy({
      targets: [
        { src: 'views/index.html', dest: '.', rename: { stripBase: 1 } },
        { src: 'assets/img/*.svg', dest: 'img', rename: { stripBase: 2 } }
      ]
    })
  ],
  publicDir: false,
  build: {
    outDir: 'public',
    emptyOutDir: true,
    assetsDir: '',
    rollupOptions: {
      input: resolve(root, 'assets/js/index.js'),
      output: {
        entryFileNames: 'js/main.min.js',
        chunkFileNames: 'js/[name].js',
        assetFileNames: (assetInfo) => {
          const name = assetInfo.name || '';
          if (name.endsWith('.css')) {
            return 'css/main.min.css';
          }
          if (/\.(png|jpe?g|gif|svg|webp|ico)$/i.test(name)) {
            return 'img/[name][extname]';
          }
          return '[name][extname]';
        }
      }
    }
  }
});
