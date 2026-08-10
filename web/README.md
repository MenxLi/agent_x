# Xun web

Vue 3 and TypeScript frontend for `xun.WebDisplay`.

```bash
npm install
npm run dev
```

The development server runs at `http://127.0.0.1:5173` and proxies `/api` and `/ws` to FastAPI at `http://127.0.0.1:18960`. Set `VITE_XUN_BASE_PATH=/agents/research` when the backend uses that `base_path`; `VITE_XUN_BACKEND` overrides the backend origin.

```bash
npm run build
```

The production build is written to `../src/xun/assets/web`, where `WebDisplay` serves it and the Python wheel includes it as package data.
