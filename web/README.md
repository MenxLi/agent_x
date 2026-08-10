# Xun web

Vue 3 and TypeScript frontend for `xun.DisplayWeb`.

```bash
npm install
npm run dev
```

The development server runs at `http://127.0.0.1:5173` and proxies `/api` and `/ws` to FastAPI at `http://127.0.0.1:18960`.

```bash
npm run build
```

The production build is written to `../src/xun/assets/web`, where `DisplayWeb` serves it and the Python wheel includes it as package data.
