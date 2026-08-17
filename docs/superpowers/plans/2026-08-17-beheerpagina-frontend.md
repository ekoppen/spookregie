# Beheerpagina — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bouw de React/Vite-beheerpagina die tegen de af­geronde backend (plan 2) praat: inloggen, dashboard met node-status/noodstop/tijdvenster, mirror-effect kiezen met live preview en sleep/schaal-overlay, scare-audio per zone beheren, WLED-snelbediening, en een live log-viewer. Dit is plan 3 van 3 — het laatste stuk van de beheerpagina-feature.

**Architecture:** Eén Vite/React/TypeScript-SPA (`admin/frontend/`) die via `fetch` (met cookies) tegen de 21 HTTP-routes en 1 WebSocket-route van de backend praat, en voor de live camera-preview rechtstreeks (buiten de backend om) met mirror-node's eigen MJPEG-endpoint verbindt. Geen zware state-library (React Context + hooks volstaat op deze schaal), geen zware E2E-testsuite (bewust besloten tijdens het brainstormgesprek) — wel TypeScript voor type-veiligheid en lichte Vitest-tests voor de paar stukjes pure logica die dat rechtvaardigen (coördinaat-wiskunde voor de overlay-sleepfunctie, WebSocket-payload-parsing).

**Tech Stack:** React 18 + TypeScript + Vite (build tool + dev server), `react-router-dom` (standaard SPA-routering, geen reden dit zelf te bouwen), plain CSS met custom properties (geen UI-kit/Tailwind — houdt dependencies minimaal, visuele kwaliteit komt uit bewust toegepaste ontwerpkeuzes, niet uit een framework). Vitest voor de paar pure-logica-tests.

**Spec:** `docs/superpowers/specs/2026-08-16-beheerpagina-design.md`

**Bevestigd API-contract uit plan 2 (werkende code, exact overgenomen — niet opnieuw verzinnen):**

```
POST /api/login              {password} -> 200 {ok:true} + session-cookie | 401
POST /api/logout             -> 200 {ok:true}
GET  /api/media?category=    -> [{hash, filename, category, uploaded_at}]
POST /api/media               multipart {file, category: "mirror_overlay"|"scare_audio"} -> 200 {hash, filename, category} | 400
GET  /api/media/{hash}         -> bytes (PUBLIEK, geen auth) | 404
DELETE /api/media/{hash}        -> {deleted: bool}
GET/PUT /api/mirror/config       {effect, params, overlay_hash, scale, position:[x,y]} (PUT normaliseert+publiceert)
POST /api/mirror/preview          zelfde vorm, alleen publiceren (niet opslaan)
POST /api/mirror/test              -> {ok:true}
GET/PUT /api/scare/{zone}/config    {enabled_hashes:[...]}  (zone: alleen a-z0-9-, anders 400)
POST /api/scare/{zone}/test          -> {ok:true}
GET  /api/nodes                       -> {node: {status: "online"|"offline"}}
GET  /api/logs?node=&limit=            -> [{node, ts, level, msg}]
GET/PUT /api/schedule                   {on_time, off_time, enabled}  (HH:MM, anders 400)
POST /api/system/emergency-stop          -> {ok:true}
POST /api/system/wake                     -> {ok:true}
GET  /api/ha/states                        -> [{entity_id, state, ...}] (lege lijst ook bij HA-storing, niet te onderscheiden)
POST /api/ha/service                        {domain, service, data} -> {ok:true} (weigert stil bij ongeldige domain/service)
WS   /api/ws                                 (PUBLIEK, geen auth) -> {"type":"status"|"log","topic":str,"payload":<ruwe string>}
```

Effect-namen (mirror): `xray`, `thermal`, `contour`, `posterize` — uit `mirror_node/effects/__init__.py`'s `EFFECTS`-register. Parameters per effect: `xray`/`thermal` → `intensity` (float 0.0-1.0); `contour` → `threshold1`/`threshold2` (int); `posterize` → `levels` (int ≥2). De backend valideert de effectnaam niet — een onbekende naam wordt stil genegeerd door de mirror-node (logt een fout, toont het vorige beeld). De frontend moet dus zelf een whitelist hanteren (geen vrije-tekst-invoer voor `effect`).

**Belangrijke asymmetrie om in de UI te verwerken:** `GET /api/logs` geeft al-geparste objecten terug (`{node, ts, level, msg}`), maar WebSocket-logberichten (`{"type":"log", "payload": "<ruwe JSON-string>"}`) zijn ongeparsed — de frontend moet `JSON.parse(payload)` zelf doen voor WS-logberichten, maar niet voor de initiële `GET /api/logs`-lading.

## Global Constraints

- Nieuwe pip-dependencies zijn hier niet van toepassing (dit is een JS/TS-project); nieuwe npm-dependencies zijn toegestaan waar een goede reden is (routering), maar geen state-library, geen UI-kit, geen zware testing-library — dat is expliciet te veel voor dit hobbyproject.
- Elke fetch naar `/api/...` (behalve login/media-download/WS) stuurt cookies mee (`credentials: "include"`) en behandelt een `401`-response door terug te sturen naar de inlogpagina.
- `effect`-keuze in de UI is altijd een whitelist van de 4 bekende namen — nooit vrije tekst die rechtstreeks naar de backend gaat.
- WebSocket-logberichten worden zelf geparsed (`JSON.parse` op `payload`); `GET /api/logs`-berichten zijn dat al.
- Geen zware E2E-testsuite (bewust besloten in het brainstormgesprek) — wel `tsc --noEmit`/`npm run build` als compileercontrole bij elke taak, en Vitest-tests voor de stukjes pure logica die dat rechtvaardigen. UI-componenten krijgen handmatige/visuele verificatie, conform hoe fysieke/IO-code in plan 1 en 2 ook al zonder geautomatiseerde tests werkt.
- Visuele afwerking: gebruik de `frontend-design`-skill tijdens het bouwen van pagina's/componenten met echte UI (niet voor pure logica-taken) — dit project moet er verzorgd uitzien, niet als een ongestileerde default-HTML-pagina.

---

## File Structure

```
admin/frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── .env.example                    # VITE_MIRROR_STREAM_URL enz.
└── src/
    ├── main.tsx
    ├── App.tsx                      # routering + layout
    ├── types.ts                      # TS-interfaces matchend het API-contract
    ├── api/
    │   ├── client.ts                   # fetch-wrapper (credentials, JSON, 401-afhandeling)
    │   ├── auth.ts
    │   ├── media.ts
    │   ├── mirror.ts
    │   ├── scare.ts
    │   ├── nodes.ts
    │   ├── schedule.ts
    │   └── ha.ts
    ├── hooks/
    │   ├── useAuth.ts
    │   └── useWebSocket.ts
    ├── lib/
    │   ├── overlayMath.ts              # pure sleep/schaal-coördinatenwiskunde (Vitest)
    │   └── wsMessage.ts                 # pure WS-payload-parsing (Vitest)
    ├── components/
    │   ├── Layout.tsx
    │   ├── NodeStatusCard.tsx
    │   ├── MediaLibrary.tsx
    │   └── OverlayCanvas.tsx
    └── pages/
        ├── LoginPage.tsx
        ├── DashboardPage.tsx
        ├── MirrorPage.tsx
        ├── ScarePage.tsx
        ├── HaPage.tsx
        └── LogsPage.tsx
tests/frontend/
├── overlayMath.test.ts
└── wsMessage.test.ts
```

---

### Task 1: Project-scaffolding + API-client + types

**Files:**
- Create: `admin/frontend/package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `.env.example`
- Create: `admin/frontend/src/main.tsx`, `App.tsx` (kaal, alleen een routerskelet)
- Create: `admin/frontend/src/types.ts`
- Create: `admin/frontend/src/api/client.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `MirrorConfig`, `ScareConfig`, `MediaItem`, `NodeStatus`, `LogEntry`, `Schedule`, `HaState`, `WsMessage` — TypeScript-interfaces die exact het bovenstaande contract volgen.
  - `api/client.ts`: `apiFetch<T>(path: string, options?: RequestInit) => Promise<T>` — voegt `credentials: "include"` toe, gooit een typed `ApiError` (met `status`) bij een non-2xx-response, en stuurt bij een `401` de browser naar `/login` (via `window.location`, simpel en robuust, geen router-context nodig in een niet-React module).

- [ ] **Step 1: Maak de projectstructuur en config**

```bash
mkdir -p admin/frontend/src/{api,hooks,lib,components,pages}
mkdir -p tests/frontend
```

`admin/frontend/package.json`:
```json
{
  "name": "beheerpagina-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

`admin/frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

`admin/frontend/vite.config.ts`:
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

`admin/frontend/index.html`:
```html
<!doctype html>
<html lang="nl">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Halloween beheerpagina</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`admin/frontend/.env.example`:
```
# URL van mirror-node's eigen MJPEG-live-preview-endpoint (rechtstreeks, niet
# via de backend — zie spec: live preview gaat direct browser<->mirror-node).
VITE_MIRROR_STREAM_URL=http://mirror-node.local:8091/stream
```

- [ ] **Step 2: Implementeer `src/types.ts`**

```typescript
export interface MirrorConfig {
  effect: "xray" | "thermal" | "contour" | "posterize";
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
}

export interface ScareConfig {
  enabled_hashes: string[];
}

export interface MediaItem {
  hash: string;
  filename: string;
  category: "mirror_overlay" | "scare_audio";
  uploaded_at: string;
}

export interface NodeStatusMap {
  [node: string]: { status: "online" | "offline" };
}

export interface LogEntry {
  node: string;
  ts: number;
  level: string;
  msg: string;
}

export interface Schedule {
  on_time: string;
  off_time: string;
  enabled: boolean;
}

export interface HaState {
  entity_id: string;
  state: string;
  [key: string]: unknown;
}

export interface WsMessage {
  type: "status" | "log";
  topic: string;
  payload: string;
}
```

- [ ] **Step 3: Implementeer `src/api/client.ts`**

```typescript
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (response.status === 401) {
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "niet ingelogd");
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, text || `HTTP ${response.status}`);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return undefined as T;
}
```

- [ ] **Step 4: Kale `App.tsx`/`main.tsx` zodat de build slaagt**

`admin/frontend/src/App.tsx`:
```typescript
export default function App() {
  return <div>Beheerpagina — wordt opgebouwd in latere taken.</div>;
}
```

`admin/frontend/src/main.tsx`:
```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 5: Installeer dependencies en controleer dat de build slaagt**

```bash
cd admin/frontend && npm install && npm run build
```

Expected: build slaagt zonder TypeScript-fouten, produceert een `dist/`-map (die je meteen weer kunt verwijderen of `.gitignore`n — zie Task 9 voor de definitieve `.gitignore`-regel).

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/package.json admin/frontend/tsconfig.json admin/frontend/vite.config.ts admin/frontend/index.html admin/frontend/.env.example admin/frontend/src/types.ts admin/frontend/src/api/client.ts admin/frontend/src/App.tsx admin/frontend/src/main.tsx
git commit -m "feat: frontend-scaffolding (Vite/React/TS) + API-client + types"
```

---

### Task 2: Auth (login-pagina + sessie-hook)

**Files:**
- Create: `admin/frontend/src/api/auth.ts`
- Create: `admin/frontend/src/hooks/useAuth.ts`
- Create: `admin/frontend/src/pages/LoginPage.tsx`
- Modify: `admin/frontend/src/App.tsx` (routering: `/login` publiek, rest beschermd)

**Interfaces:**
- Consumes: `api/client.ts`'s `apiFetch`/`ApiError` (Task 1)
- Produces:
  - `api/auth.ts`: `login(password: string) -> Promise<void>`, `logout() -> Promise<void>`
  - `hooks/useAuth.ts`: `useAuth() -> { isAuthenticated: boolean, checking: boolean }` — doet een lichte call (bijv. `GET /api/nodes`, die altijd auth vereist) om te bepalen of er al een geldige sessie is, zonder een apart "wie ben ik"-endpoint nodig te hebben (dat bestaat niet in de backend — hergebruik een bestaande beschermde route).

- [ ] **Step 1: Implementeer `src/api/auth.ts`**

```typescript
import { apiFetch } from "./client";

export async function login(password: string): Promise<void> {
  await apiFetch<{ ok: boolean }>("/api/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export async function logout(): Promise<void> {
  await apiFetch<{ ok: boolean }>("/api/logout", { method: "POST" });
}
```

- [ ] **Step 2: Implementeer `src/hooks/useAuth.ts`**

```typescript
import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "../api/client";

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    apiFetch("/api/nodes")
      .then(() => setIsAuthenticated(true))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setIsAuthenticated(false);
        }
      })
      .finally(() => setChecking(false));
  }, []);

  return { isAuthenticated, checking };
}
```

Let op: `apiFetch` stuurt bij een 401 zelf al door naar `/login` (Task 1) — deze hook is dus vooral relevant om te weten of je de inlogpagina zelf mag tonen zonder eerst tegen een beschermde route te botsen.

- [ ] **Step 3: Implementeer `src/pages/LoginPage.tsx`**

Gebruik de `frontend-design`-skill voor de visuele invulling van dit component (dit is de eerste pagina die bezoekers zien — het mag verzorgd ogen, niet een kaal formuliertje). Functionele eisen: een wachtwoordveld, een submit-knop, een foutmelding bij een verkeerd wachtwoord (401), en na succesvol inloggen navigeren naar `/` (via `react-router-dom`'s `useNavigate`).

```typescript
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { ApiError } from "../api/client";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(password);
      navigate("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Onjuist wachtwoord.");
      } else {
        setError("Inloggen mislukt, probeer het opnieuw.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Beheerpagina</h1>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Wachtwoord"
        autoFocus
      />
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting}>
        Inloggen
      </button>
    </form>
  );
}
```

(De echte styling/opmaak komt uit de `frontend-design`-skill-toepassing — bovenstaande is de functionele basis.)

- [ ] **Step 4: Bekabel routering in `App.tsx`**

```typescript
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, checking } = useAuth();
  if (checking) return <p>Laden…</p>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <div>Beheerpagina — wordt verder opgebouwd in latere taken.</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 5: Build-controle**

Run: `cd admin/frontend && npm run build`
Expected: geen TypeScript-fouten.

- [ ] **Step 6: Handmatige verificatie**

Run: `npm run dev` (met de backend uit plan 2 lokaal draaiend op poort 8000). Verwacht: navigeren naar `/` stuurt door naar `/login`; verkeerd wachtwoord toont een foutmelding; juist wachtwoord (uit `ADMIN_PASSWORD`) navigeert naar `/`.

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/api/auth.ts admin/frontend/src/hooks/useAuth.ts admin/frontend/src/pages/LoginPage.tsx admin/frontend/src/App.tsx
git commit -m "feat: login-pagina en sessie-hook"
```

---

### Task 3: Pure logica — overlay-wiskunde en WS-payload-parsing (Vitest)

**Files:**
- Create: `admin/frontend/src/lib/overlayMath.ts`
- Create: `admin/frontend/src/lib/wsMessage.ts`
- Create: `admin/frontend/vitest.config.ts`
- Test: `tests/frontend/overlayMath.test.ts`
- Test: `tests/frontend/wsMessage.test.ts`

**Interfaces:**
- Produces:
  - `lib/overlayMath.ts`: `pixelToFraction(px: number, containerSize: number) -> number`, `fractionToPixel(fraction: number, containerSize: number) -> number`, `clampFraction(fraction: number) -> number` (klemt tussen 0.0 en 1.0)
  - `lib/wsMessage.ts`: `parseLogPayload(payload: string) -> LogEntry | null` (retourneert `null` bij ongeldige JSON i.p.v. te crashen — dezelfde fail-safe-insteek als de rest van dit project)

Dit is de enige taak in dit plan met écht geautomatiseerde tests — de rest van de frontend krijgt handmatige/visuele verificatie, conform het project-brede patroon voor UI/glue-code.

- [ ] **Step 1: Vitest-config**

`admin/frontend/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["../../tests/frontend/**/*.test.ts"],
  },
});
```

- [ ] **Step 2: Schrijf de falende tests**

`tests/frontend/overlayMath.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { pixelToFraction, fractionToPixel, clampFraction } from "../../admin/frontend/src/lib/overlayMath";

describe("pixelToFraction", () => {
  it("converts a pixel offset to a 0-1 fraction of the container", () => {
    expect(pixelToFraction(50, 200)).toBe(0.25);
  });

  it("handles the container edges", () => {
    expect(pixelToFraction(0, 200)).toBe(0);
    expect(pixelToFraction(200, 200)).toBe(1);
  });
});

describe("fractionToPixel", () => {
  it("is the inverse of pixelToFraction", () => {
    expect(fractionToPixel(0.25, 200)).toBe(50);
  });
});

describe("clampFraction", () => {
  it("clamps values below 0 to 0", () => {
    expect(clampFraction(-0.5)).toBe(0);
  });

  it("clamps values above 1 to 1", () => {
    expect(clampFraction(1.5)).toBe(1);
  });

  it("leaves in-range values unchanged", () => {
    expect(clampFraction(0.42)).toBe(0.42);
  });
});
```

`tests/frontend/wsMessage.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { parseLogPayload } from "../../admin/frontend/src/lib/wsMessage";

describe("parseLogPayload", () => {
  it("parses a valid log payload", () => {
    const payload = JSON.stringify({ ts: 123.0, level: "INFO", msg: "test" });
    const result = parseLogPayload(payload);
    expect(result).toEqual({ node: "", ts: 123.0, level: "INFO", msg: "test" });
  });

  it("returns null for malformed JSON instead of throwing", () => {
    expect(parseLogPayload("dit is geen JSON")).toBeNull();
  });

  it("returns null for valid JSON that isn't a log-shaped object", () => {
    expect(parseLogPayload(JSON.stringify([1, 2, 3]))).toBeNull();
  });
});
```

- [ ] **Step 3: Run de tests, verwacht FAIL**

Run: `cd admin/frontend && npx vitest run`
Expected: FAIL (modules bestaan nog niet)

- [ ] **Step 4: Implementeer `src/lib/overlayMath.ts`**

```typescript
export function pixelToFraction(px: number, containerSize: number): number {
  if (containerSize === 0) return 0;
  return px / containerSize;
}

export function fractionToPixel(fraction: number, containerSize: number): number {
  return fraction * containerSize;
}

export function clampFraction(fraction: number): number {
  return Math.min(1, Math.max(0, fraction));
}
```

- [ ] **Step 5: Implementeer `src/lib/wsMessage.ts`**

```typescript
import type { LogEntry } from "../types";

export function parseLogPayload(payload: string): LogEntry | null {
  try {
    const data = JSON.parse(payload);
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      return null;
    }
    return {
      node: "", // wordt door de aanroeper ingevuld vanuit het topic, zie useWebSocket
      ts: data.ts,
      level: data.level,
      msg: data.msg,
    };
  } catch {
    return null;
  }
}
```

- [ ] **Step 6: Run de tests, verwacht PASS**

Run: `cd admin/frontend && npx vitest run`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/vitest.config.ts admin/frontend/src/lib/overlayMath.ts admin/frontend/src/lib/wsMessage.ts tests/frontend/overlayMath.test.ts tests/frontend/wsMessage.test.ts
git commit -m "feat: pure overlay-coördinatenwiskunde en WS-log-parsing (Vitest)"
```

---

### Task 4: WebSocket-hook + Dashboard-pagina (node-status, noodstop, tijdvenster)

**Files:**
- Create: `admin/frontend/src/hooks/useWebSocket.ts`
- Create: `admin/frontend/src/api/nodes.ts`
- Create: `admin/frontend/src/api/schedule.ts`
- Create: `admin/frontend/src/components/NodeStatusCard.tsx`
- Create: `admin/frontend/src/pages/DashboardPage.tsx`

**Interfaces:**
- Consumes: `lib/wsMessage.ts`'s `parseLogPayload` (Task 3, alleen voor de log-tak — de status-tak van WS-berichten heeft geen JSON-payload nodig te parsen, die is al de kale string `"online"`/`"offline"`), `api/client.ts` (Task 1)
- Produces:
  - `hooks/useWebSocket.ts`: `useWebSocket(onMessage: (msg: WsMessage) => void) -> { connected: boolean }` — opent `new WebSocket(wsUrl)` naar `/api/ws` (relatief pad, protocol `ws:`/`wss:` afgeleid van `location.protocol`), reconnect met een simpele vaste vertraging bij een dichte verbinding (geen exponential backoff nodig op deze schaal).
  - `api/nodes.ts`: `getNodes() -> Promise<NodeStatusMap>`, `getLogs(node?: string, limit?: number) -> Promise<LogEntry[]>`
  - `api/schedule.ts`: `getSchedule() -> Promise<Schedule>`, `putSchedule(s: Schedule) -> Promise<void>`, `emergencyStop() -> Promise<void>`, `wake() -> Promise<void>`

- [ ] **Step 1: Implementeer `src/hooks/useWebSocket.ts`**

```typescript
import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "../types";

export function useWebSocket(onMessage: (msg: WsMessage) => void) {
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let stopped = false;

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${protocol}//${window.location.host}/api/ws`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WsMessage;
          onMessageRef.current(msg);
        } catch {
          // ongeldig bericht, negeren — nooit de verbinding laten crashen
        }
      };
    }

    connect();
    return () => {
      stopped = true;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  return { connected };
}
```

- [ ] **Step 2: Implementeer `src/api/nodes.ts` en `src/api/schedule.ts`**

```typescript
// src/api/nodes.ts
import { apiFetch } from "./client";
import type { NodeStatusMap, LogEntry } from "../types";

export function getNodes(): Promise<NodeStatusMap> {
  return apiFetch<NodeStatusMap>("/api/nodes");
}

export function getLogs(node?: string, limit = 100): Promise<LogEntry[]> {
  const params = new URLSearchParams();
  if (node) params.set("node", node);
  params.set("limit", String(limit));
  return apiFetch<LogEntry[]>(`/api/logs?${params.toString()}`);
}
```

```typescript
// src/api/schedule.ts
import { apiFetch } from "./client";
import type { Schedule } from "../types";

export function getSchedule(): Promise<Schedule> {
  return apiFetch<Schedule>("/api/schedule");
}

export function putSchedule(schedule: Schedule): Promise<void> {
  return apiFetch("/api/schedule", { method: "PUT", body: JSON.stringify(schedule) });
}

export function emergencyStop(): Promise<void> {
  return apiFetch("/api/system/emergency-stop", { method: "POST" });
}

export function wake(): Promise<void> {
  return apiFetch("/api/system/wake", { method: "POST" });
}
```

- [ ] **Step 3: Implementeer `src/components/NodeStatusCard.tsx`**

Gebruik de `frontend-design`-skill voor de visuele invulling (dit is een statuskaart die op één oogopslag "alles werkt" of "iets is offline" moet communiceren — kleur/iconografie doet hier veel werk).

```typescript
interface Props {
  name: string;
  status: "online" | "offline";
}

export default function NodeStatusCard({ name, status }: Props) {
  return (
    <div data-status={status}>
      <span>{name}</span>
      <span>{status === "online" ? "online" : "offline"}</span>
    </div>
  );
}
```

- [ ] **Step 4: Implementeer `src/pages/DashboardPage.tsx`**

Combineert: `getNodes()` bij het laden + live bijwerken via `useWebSocket` (status-berichten), een noodstop/wake-knoppenpaar, en een tijdvenster-editor (twee tijdvelden + een aan/uit-schakelaar, opslaan via `putSchedule`). Gebruik de `frontend-design`-skill voor de lay-out van deze pagina als geheel (dit is de eerste pagina na inloggen — moet in één oogopslag duidelijk maken wat de status van de installatie is).

```typescript
import { useEffect, useState, useCallback } from "react";
import { getNodes } from "../api/nodes";
import { getSchedule, putSchedule, emergencyStop, wake } from "../api/schedule";
import { useWebSocket } from "../hooks/useWebSocket";
import NodeStatusCard from "../components/NodeStatusCard";
import type { NodeStatusMap, Schedule } from "../types";

export default function DashboardPage() {
  const [nodes, setNodes] = useState<NodeStatusMap>({});
  const [schedule, setSchedule] = useState<Schedule | null>(null);

  useEffect(() => {
    getNodes().then(setNodes);
    getSchedule().then(setSchedule);
  }, []);

  const handleWsMessage = useCallback((msg: { type: string; topic: string; payload: string }) => {
    if (msg.type !== "status") return;
    const match = msg.topic.match(/^status\/(.+)$/);
    if (!match) return;
    const node = match[1];
    setNodes((prev) => ({ ...prev, [node]: { status: msg.payload as "online" | "offline" } }));
  }, []);

  useWebSocket(handleWsMessage);

  async function handleScheduleSave() {
    if (!schedule) return;
    await putSchedule(schedule);
  }

  return (
    <div>
      <h1>Dashboard</h1>
      <section>
        {Object.entries(nodes).map(([name, info]) => (
          <NodeStatusCard key={name} name={name} status={info.status} />
        ))}
      </section>
      <section>
        <button onClick={() => emergencyStop()}>Noodstop</button>
        <button onClick={() => wake()}>Wakker maken</button>
      </section>
      {schedule && (
        <section>
          <label>
            Aan
            <input
              type="time"
              value={schedule.on_time}
              onChange={(e) => setSchedule({ ...schedule, on_time: e.target.value })}
            />
          </label>
          <label>
            Uit
            <input
              type="time"
              value={schedule.off_time}
              onChange={(e) => setSchedule({ ...schedule, off_time: e.target.value })}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={schedule.enabled}
              onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
            />
            Ingeschakeld
          </label>
          <button onClick={handleScheduleSave}>Opslaan</button>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Bekabel de route in `App.tsx`**

Vervang de placeholder-`<div>` binnen `ProtectedRoute` door een geneste `Routes` met `<Route path="/" element={<DashboardPage />} />` (de overige paden volgen in latere taken).

- [ ] **Step 6: Build-controle + handmatige verificatie**

Run: `npm run build`. Handmatig: start de backend + `npm run dev`, log in, controleer dat node-statussen verschijnen en live bijwerken zodra een node online/offline gaat (`mosquitto_pub -t status/mirror -m online`), en dat noodstop/wake/tijdvenster-opslaan geen fouten geven.

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/hooks/useWebSocket.ts admin/frontend/src/api/nodes.ts admin/frontend/src/api/schedule.ts admin/frontend/src/components/NodeStatusCard.tsx admin/frontend/src/pages/DashboardPage.tsx admin/frontend/src/App.tsx
git commit -m "feat: WebSocket-hook en dashboard (node-status, noodstop, tijdvenster)"
```

---

### Task 5: Media-bibliotheek component (gedeeld door mirror-overlays en scare-audio)

**Files:**
- Create: `admin/frontend/src/api/media.ts`
- Create: `admin/frontend/src/components/MediaLibrary.tsx`

**Interfaces:**
- Consumes: `api/client.ts` (Task 1)
- Produces:
  - `api/media.ts`: `listMedia(category?: string) -> Promise<MediaItem[]>`, `uploadMedia(file: File, category: string) -> Promise<MediaItem>`, `deleteMedia(hash: string) -> Promise<void>`
  - `components/MediaLibrary.tsx`: `<MediaLibrary category="mirror_overlay"|"scare_audio" selected={string[]} onSelectionChange={(hashes: string[]) => void} selectionMode="single"|"multiple" />` — toont een grid/lijst van geüploade bestanden met upload-knop, verwijder-knop per item, en selectie (aanvinken voor scare-audio's meerdere, klikken voor mirror's ene overlay).

- [ ] **Step 1: Implementeer `src/api/media.ts`**

```typescript
import { apiFetch } from "./client";
import type { MediaItem } from "../types";

export function listMedia(category?: string): Promise<MediaItem[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiFetch<MediaItem[]>(`/api/media${query}`);
}

export async function uploadMedia(file: File, category: string): Promise<MediaItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("category", category);
  const response = await fetch("/api/media", {
    method: "POST",
    credentials: "include",
    body: formData, // geen Content-Type header zetten: de browser zet zelf de multipart-boundary
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Upload mislukt (${response.status})`);
  }
  return response.json();
}

export function deleteMedia(hash: string): Promise<void> {
  return apiFetch(`/api/media/${hash}`, { method: "DELETE" });
}
```

Let op: `uploadMedia` gebruikt bewust de kale `fetch` i.p.v. `apiFetch` — `apiFetch` zet standaard een `Content-Type: application/json`-header, wat een multipart-upload zou breken (de browser moet zelf de `multipart/form-data`-boundary in de Content-Type zetten).

- [ ] **Step 2: Implementeer `src/components/MediaLibrary.tsx`**

Gebruik de `frontend-design`-skill voor de visuele invulling (dit is een bestandsbibliotheek met upload/selectie/verwijderen — een grid met duidelijke selectie-staat en hover-acties is hier op zijn plaats, niet een kale lijst).

```typescript
import { useEffect, useState } from "react";
import { listMedia, uploadMedia, deleteMedia } from "../api/media";
import type { MediaItem } from "../types";

interface Props {
  category: "mirror_overlay" | "scare_audio";
  selected: string[];
  onSelectionChange: (hashes: string[]) => void;
  selectionMode: "single" | "multiple";
}

export default function MediaLibrary({ category, selected, onSelectionChange, selectionMode }: Props) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [uploading, setUploading] = useState(false);

  function refresh() {
    listMedia(category).then(setItems);
  }

  useEffect(refresh, [category]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadMedia(file, category);
      refresh();
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(hash: string) {
    await deleteMedia(hash);
    onSelectionChange(selected.filter((h) => h !== hash));
    refresh();
  }

  function toggleSelect(hash: string) {
    if (selectionMode === "single") {
      onSelectionChange([hash]);
    } else {
      onSelectionChange(
        selected.includes(hash) ? selected.filter((h) => h !== hash) : [...selected, hash],
      );
    }
  }

  return (
    <div>
      <input type="file" onChange={handleUpload} disabled={uploading} />
      <ul>
        {items.map((item) => (
          <li key={item.hash}>
            <label>
              <input
                type={selectionMode === "single" ? "radio" : "checkbox"}
                checked={selected.includes(item.hash)}
                onChange={() => toggleSelect(item.hash)}
              />
              {item.filename}
            </label>
            <button onClick={() => handleDelete(item.hash)}>Verwijderen</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Build-controle**

Run: `npm run build`

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/api/media.ts admin/frontend/src/components/MediaLibrary.tsx
git commit -m "feat: gedeelde media-bibliotheek (upload/lijst/selecteren/verwijderen)"
```

---

### Task 6: Mirror-pagina (effect, parameters, overlay met live preview en sleep/schaal)

**Files:**
- Create: `admin/frontend/src/api/mirror.ts`
- Create: `admin/frontend/src/components/OverlayCanvas.tsx`
- Create: `admin/frontend/src/pages/MirrorPage.tsx`

**Interfaces:**
- Consumes: `api/client.ts` (Task 1), `lib/overlayMath.ts` (Task 3), `components/MediaLibrary.tsx` (Task 5)
- Produces:
  - `api/mirror.ts`: `getMirrorConfig() -> Promise<MirrorConfig>`, `putMirrorConfig(c: MirrorConfig) -> Promise<void>`, `previewMirrorConfig(c: MirrorConfig) -> Promise<void>`, `testMirror() -> Promise<void>`
  - `components/OverlayCanvas.tsx`: `<OverlayCanvas streamUrl={string} overlayUrl={string|null} scale={number} position={[number,number]} onPositionChange={...} onScaleChange={...} />` — toont de live MJPEG-stream met de overlay-afbeelding erover­heen, versleepbaar en schaalbaar.

- [ ] **Step 1: Implementeer `src/api/mirror.ts`**

```typescript
import { apiFetch } from "./client";
import type { MirrorConfig } from "../types";

export function getMirrorConfig(): Promise<MirrorConfig> {
  return apiFetch<MirrorConfig>("/api/mirror/config");
}

export function putMirrorConfig(config: MirrorConfig): Promise<void> {
  return apiFetch("/api/mirror/config", { method: "PUT", body: JSON.stringify(config) });
}

export function previewMirrorConfig(config: MirrorConfig): Promise<void> {
  return apiFetch("/api/mirror/preview", { method: "POST", body: JSON.stringify(config) });
}

export function testMirror(): Promise<void> {
  return apiFetch("/api/mirror/test", { method: "POST" });
}
```

- [ ] **Step 2: Implementeer `src/components/OverlayCanvas.tsx`**

Sleep/schaal-interactie: bij `mousedown` op de overlay start het slepen; `mousemove` berekent via `pixelToFraction`/`clampFraction` (Task 3) de nieuwe `position`; `mouseup` stopt het slepen. Een los schaal-schuifje (`<input type="range">`) stuurt `scale` aan. Gebruik de `frontend-design`-skill voor de visuele afwerking van de sleep-handle/schaal-indicator — dit is het meest "indrukwekkende UX"-onderdeel van de hele beheerpagina, besteed er aandacht aan.

```typescript
import { useRef, useState } from "react";
import { pixelToFraction, clampFraction } from "../lib/overlayMath";

interface Props {
  streamUrl: string;
  overlayUrl: string | null;
  scale: number;
  position: [number, number];
  onPositionChange: (position: [number, number]) => void;
  onScaleChange: (scale: number) => void;
}

export default function OverlayCanvas({
  streamUrl,
  overlayUrl,
  scale,
  position,
  onPositionChange,
  onScaleChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleMouseMove(e: React.MouseEvent) {
    if (!dragging || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = clampFraction(pixelToFraction(e.clientX - rect.left, rect.width));
    const y = clampFraction(pixelToFraction(e.clientY - rect.top, rect.height));
    onPositionChange([x, y]);
  }

  return (
    <div>
      <div
        ref={containerRef}
        style={{ position: "relative" }}
        onMouseMove={handleMouseMove}
        onMouseUp={() => setDragging(false)}
        onMouseLeave={() => setDragging(false)}
      >
        <img src={streamUrl} alt="Live mirror-preview" style={{ width: "100%", display: "block" }} />
        {overlayUrl && (
          <img
            src={overlayUrl}
            alt="Overlay"
            onMouseDown={() => setDragging(true)}
            style={{
              position: "absolute",
              left: `${position[0] * 100}%`,
              top: `${position[1] * 100}%`,
              transform: `translate(-50%, -50%) scale(${scale})`,
              cursor: "grab",
            }}
          />
        )}
      </div>
      <input
        type="range"
        min="0.1"
        max="3"
        step="0.05"
        value={scale}
        onChange={(e) => onScaleChange(parseFloat(e.target.value))}
      />
    </div>
  );
}
```

- [ ] **Step 3: Implementeer `src/pages/MirrorPage.tsx`**

Combineert: effect-whitelist-dropdown (`xray`/`thermal`/`contour`/`posterize`), per-effect parameter-invoervelden (toon alleen de velden die bij het gekozen effect horen — `intensity` voor xray/thermal, `threshold1`/`threshold2` voor contour, `levels` voor posterize), een `MediaLibrary` in `single`-selectiemodus voor de overlay (`category="mirror_overlay"`), en de `OverlayCanvas` voor live preview. Elke wijziging in effect/params/overlay/scale/position stuurt (gethrottled, bijv. via een `setTimeout`-debounce van ~150ms) een `previewMirrorConfig`-aanroep; een expliciete "Toepassen"-knop roept `putMirrorConfig` aan. Een "Test"-knop roept `testMirror` aan.

```typescript
import { useEffect, useState } from "react";
import { getMirrorConfig, putMirrorConfig, previewMirrorConfig, testMirror } from "../api/mirror";
import MediaLibrary from "../components/MediaLibrary";
import OverlayCanvas from "../components/OverlayCanvas";
import type { MirrorConfig } from "../types";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const STREAM_URL = import.meta.env.VITE_MIRROR_STREAM_URL ?? "";

function paramFieldsFor(effect: MirrorConfig["effect"]): string[] {
  switch (effect) {
    case "xray":
    case "thermal":
      return ["intensity"];
    case "contour":
      return ["threshold1", "threshold2"];
    case "posterize":
      return ["levels"];
  }
}

export default function MirrorPage() {
  const [config, setConfig] = useState<MirrorConfig | null>(null);

  useEffect(() => {
    getMirrorConfig().then(setConfig);
  }, []);

  useEffect(() => {
    if (!config) return;
    const timer = setTimeout(() => previewMirrorConfig(config), 150);
    return () => clearTimeout(timer);
  }, [config]);

  if (!config) return <p>Laden…</p>;

  function update(patch: Partial<MirrorConfig>) {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  return (
    <div>
      <h1>Mirror-effect</h1>
      <select
        value={config.effect}
        onChange={(e) => update({ effect: e.target.value as MirrorConfig["effect"], params: {} })}
      >
        {EFFECTS.map((effect) => (
          <option key={effect} value={effect}>
            {effect}
          </option>
        ))}
      </select>
      {paramFieldsFor(config.effect).map((field) => (
        <label key={field}>
          {field}
          <input
            type="number"
            step="0.1"
            value={config.params[field] ?? ""}
            onChange={(e) =>
              update({ params: { ...config.params, [field]: parseFloat(e.target.value) } })
            }
          />
        </label>
      ))}
      <MediaLibrary
        category="mirror_overlay"
        selectionMode="single"
        selected={config.overlay_hash ? [config.overlay_hash] : []}
        onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
      />
      <OverlayCanvas
        streamUrl={STREAM_URL}
        overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
        scale={config.scale}
        position={config.position}
        onPositionChange={(position) => update({ position })}
        onScaleChange={(scale) => update({ scale })}
      />
      <button onClick={() => putMirrorConfig(config)}>Toepassen</button>
      <button onClick={() => testMirror()}>Test</button>
    </div>
  );
}
```

- [ ] **Step 4: Bekabel de route in `App.tsx`**

- [ ] **Step 5: Build-controle + handmatige verificatie**

Run: `npm run build`. Handmatig (vereist een draaiende mirror-node): controleer dat de live stream zichtbaar is, dat een effect-wissel binnen ~150ms in de preview te zien is, dat slepen/schalen van de overlay meteen (via preview) zichtbaar is, en dat "Toepassen" de config echt opslaat (herladen van de pagina toont dezelfde config terug).

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/api/mirror.ts admin/frontend/src/components/OverlayCanvas.tsx admin/frontend/src/pages/MirrorPage.tsx admin/frontend/src/App.tsx
git commit -m "feat: mirror-pagina met effect/parameters/overlay en live sleep/schaal-preview"
```

---

### Task 7: Scare-pagina (audio per zone)

**Files:**
- Create: `admin/frontend/src/api/scare.ts`
- Create: `admin/frontend/src/pages/ScarePage.tsx`

**Interfaces:**
- Consumes: `api/client.ts` (Task 1), `components/MediaLibrary.tsx` (Task 5)
- Produces: `api/scare.ts`: `getScareConfig(zone: string) -> Promise<ScareConfig>`, `putScareConfig(zone: string, c: ScareConfig) -> Promise<void>`, `testScare(zone: string) -> Promise<void>`

Er is geen backend-endpoint dat de lijst van bestaande zones teruggeeft (de backend kent geen zone-register — elke zone-string die ooit gebruikt is, bestaat impliciet). Gebruik voorlopig een kleine, hardgecodeerde lijst zones in de UI (bijv. `["zone-a", "zone-b"]`, matchend de voorbeeld-zones uit plan 1se scare-node-configuratie) met een simpel invoerveld om een andere zone-naam te typen — geen overbouw met een zone-CRUD-systeem, dat is buiten de scope van dit plan.

- [ ] **Step 1: Implementeer `src/api/scare.ts`**

```typescript
import { apiFetch } from "./client";
import type { ScareConfig } from "../types";

export function getScareConfig(zone: string): Promise<ScareConfig> {
  return apiFetch<ScareConfig>(`/api/scare/${encodeURIComponent(zone)}/config`);
}

export function putScareConfig(zone: string, config: ScareConfig): Promise<void> {
  return apiFetch(`/api/scare/${encodeURIComponent(zone)}/config`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export function testScare(zone: string): Promise<void> {
  return apiFetch(`/api/scare/${encodeURIComponent(zone)}/test`, { method: "POST" });
}
```

- [ ] **Step 2: Implementeer `src/pages/ScarePage.tsx`**

Gebruik de `frontend-design`-skill voor de visuele invulling.

```typescript
import { useEffect, useState } from "react";
import { getScareConfig, putScareConfig, testScare } from "../api/scare";
import MediaLibrary from "../components/MediaLibrary";

const KNOWN_ZONES = ["zone-a", "zone-b"];

export default function ScarePage() {
  const [zone, setZone] = useState(KNOWN_ZONES[0]);
  const [enabledHashes, setEnabledHashes] = useState<string[]>([]);

  useEffect(() => {
    getScareConfig(zone).then((c) => setEnabledHashes(c.enabled_hashes));
  }, [zone]);

  async function handleSave() {
    await putScareConfig(zone, { enabled_hashes: enabledHashes });
  }

  return (
    <div>
      <h1>Scare-audio</h1>
      <label>
        Zone
        <select value={zone} onChange={(e) => setZone(e.target.value)}>
          {KNOWN_ZONES.map((z) => (
            <option key={z} value={z}>
              {z}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="andere zone…"
          onBlur={(e) => e.target.value && setZone(e.target.value)}
        />
      </label>
      <MediaLibrary
        category="scare_audio"
        selectionMode="multiple"
        selected={enabledHashes}
        onSelectionChange={setEnabledHashes}
      />
      <button onClick={handleSave}>Opslaan</button>
      <button onClick={() => testScare(zone)}>Test</button>
    </div>
  );
}
```

- [ ] **Step 3: Bekabel de route in `App.tsx`**

- [ ] **Step 4: Build-controle + handmatige verificatie**

Run: `npm run build`. Handmatig: bestanden aan/uit vinken en opslaan, controleren dat een herlaad dezelfde selectie toont; "Test" speelt (met een draaiende scare-node) een geluid af.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/api/scare.ts admin/frontend/src/pages/ScarePage.tsx admin/frontend/src/App.tsx
git commit -m "feat: scare-pagina (audio per zone in-/uitschakelen, testen)"
```

---

### Task 8: HA-pagina (WLED-snelbediening) + Logs-pagina

**Files:**
- Create: `admin/frontend/src/api/ha.ts`
- Create: `admin/frontend/src/pages/HaPage.tsx`
- Create: `admin/frontend/src/pages/LogsPage.tsx`

**Interfaces:**
- Consumes: `api/client.ts` (Task 1), `hooks/useWebSocket.ts` + `lib/wsMessage.ts` (Tasks 3-4), `api/nodes.ts`'s `getLogs` (Task 4)
- Produces:
  - `api/ha.ts`: `getHaStates() -> Promise<HaState[]>`, `callHaService(domain: string, service: string, data: Record<string, unknown>) -> Promise<void>`
  - Twee pagina's

- [ ] **Step 1: Implementeer `src/api/ha.ts`**

```typescript
import { apiFetch } from "./client";
import type { HaState } from "../types";

export function getHaStates(): Promise<HaState[]> {
  return apiFetch<HaState[]>("/api/ha/states");
}

export function callHaService(
  domain: string,
  service: string,
  data: Record<string, unknown>,
): Promise<void> {
  return apiFetch("/api/ha/service", {
    method: "POST",
    body: JSON.stringify({ domain, service, data }),
  });
}
```

- [ ] **Step 2: Implementeer `src/pages/HaPage.tsx`**

Simpele lijst van HA-entiteiten (filter zelf op iets met `light.` in de `entity_id` als een goedkope manier om WLED-achtige entiteiten eruit te pikken, zonder een aparte backend-endpoint nodig te hebben) met een aan/uit-knop per entiteit die `callHaService("light", "turn_on"|"turn_off", {entity_id})` aanroept. Vermeld expliciet in de UI dat een lege lijst niet te onderscheiden is van "HA onbereikbaar" (bekende backend-beperking, zie plan 2's eindreview) — toon een neutrale tekst als de lijst leeg is, geen misleidende foutmelding.

```typescript
import { useEffect, useState } from "react";
import { getHaStates, callHaService } from "../api/ha";
import type { HaState } from "../types";

export default function HaPage() {
  const [states, setStates] = useState<HaState[]>([]);

  useEffect(() => {
    getHaStates().then(setStates);
  }, []);

  const lights = states.filter((s) => s.entity_id.startsWith("light."));

  return (
    <div>
      <h1>Home Assistant</h1>
      {lights.length === 0 && (
        <p>Geen licht-entiteiten gevonden (of Home Assistant is niet bereikbaar).</p>
      )}
      <ul>
        {lights.map((light) => (
          <li key={light.entity_id}>
            {light.entity_id} — {light.state}
            <button onClick={() => callHaService("light", "turn_on", { entity_id: light.entity_id })}>
              Aan
            </button>
            <button onClick={() => callHaService("light", "turn_off", { entity_id: light.entity_id })}>
              Uit
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Implementeer `src/pages/LogsPage.tsx`**

Laadt de laatste 100 regels via `getLogs()` bij het openen, en voegt daarna live regels toe via `useWebSocket` — voor `type: "log"`-berichten wordt `parseLogPayload` (Task 3) gebruikt en de nodenaam uit het topic gehaald (zelfde patroon als Task 4's status-parsing).

```typescript
import { useEffect, useState, useCallback } from "react";
import { getLogs } from "../api/nodes";
import { useWebSocket } from "../hooks/useWebSocket";
import { parseLogPayload } from "../lib/wsMessage";
import type { LogEntry, WsMessage } from "../types";

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    getLogs(undefined, 100).then(setLogs);
  }, []);

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type !== "log") return;
    const match = msg.topic.match(/^log\/(.+)$/);
    if (!match) return;
    const entry = parseLogPayload(msg.payload);
    if (!entry) return;
    setLogs((prev) => [...prev.slice(-199), { ...entry, node: match[1] }]);
  }, []);

  useWebSocket(handleWsMessage);

  return (
    <div>
      <h1>Logs</h1>
      <ul>
        {logs.map((log, i) => (
          <li key={i}>
            [{log.node}] {log.level}: {log.msg}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Bekabel beide routes in `App.tsx`**

- [ ] **Step 5: Build-controle + handmatige verificatie**

Run: `npm run build`. Handmatig: HA-lampen tonen en aan/uit klikken (met een draaiende HA-instantie); logregels verschijnen live zodra een node iets logt.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/api/ha.ts admin/frontend/src/pages/HaPage.tsx admin/frontend/src/pages/LogsPage.tsx admin/frontend/src/App.tsx
git commit -m "feat: HA-snelbediening en live logs-pagina"
```

---

### Task 9: Navigatie/layout, stijl-basis, .gitignore

**Files:**
- Create: `admin/frontend/src/components/Layout.tsx`
- Create: `admin/frontend/src/index.css` (of losse stylesheet per component — jouw voorkeur, zie brief)
- Modify: `admin/frontend/src/App.tsx` (routes onder `Layout` nesten)
- Modify: `.gitignore` (root, `admin/frontend/node_modules/`, `admin/frontend/dist/`)

**Interfaces:**
- Consumes: alle pagina's uit Tasks 4, 6, 7, 8 (routing-doel, geen directe code-afhankelijkheid)
- Produces: `components/Layout.tsx` — navigatiebalk (Dashboard/Mirror/Scare/HA/Logs + uitlog-knop) die om elke beschermde pagina heen staat.

Dit is de belangrijkste visuele-samenhang-taak van het hele plan — gebruik de `frontend-design`-skill hier zeker, dit bepaalt hoe de hele beheerpagina als één geheel oogt (consistente kleuren/typografie/spacing over alle pagina's heen), niet losse pagina's die toevallig naast elkaar bestaan.

- [ ] **Step 1: Implementeer `src/components/Layout.tsx`**

```typescript
import { NavLink, Outlet } from "react-router-dom";
import { logout } from "../api/auth";
import { useNavigate } from "react-router-dom";

export default function Layout() {
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div>
      <nav>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/mirror">Mirror</NavLink>
        <NavLink to="/scare">Scare</NavLink>
        <NavLink to="/ha">Home Assistant</NavLink>
        <NavLink to="/logs">Logs</NavLink>
        <button onClick={handleLogout}>Uitloggen</button>
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Nest de routes onder `Layout` in `App.tsx`**

```typescript
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import MirrorPage from "./pages/MirrorPage";
import ScarePage from "./pages/ScarePage";
import HaPage from "./pages/HaPage";
import LogsPage from "./pages/LogsPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, checking } = useAuth();
  if (checking) return <p>Laden…</p>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/mirror" element={<MirrorPage />} />
          <Route path="/scare" element={<ScarePage />} />
          <Route path="/ha" element={<HaPage />} />
          <Route path="/logs" element={<LogsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 3: Basisstijl**

Schrijf `src/index.css` met CSS custom properties voor kleuren/spacing (donker Halloween-thema past bij het project, maar dit is een smaakkeuze — volg de `frontend-design`-skill's richtlijnen voor de concrete invulling in plaats van hier een kant-en-klaar kleurenschema voor te schrijven) en importeer het in `main.tsx` (`import "./index.css";`).

- [ ] **Step 4: `.gitignore`-regels**

Voeg toe aan de root `.gitignore`:
```
admin/frontend/node_modules/
admin/frontend/dist/
```

- [ ] **Step 5: Build-controle + volledige handmatige doorloop**

Run: `npm run build`. Handmatig: loop alle 5 pagina's via de navigatiebalk langs, controleer dat de actieve pagina gemarkeerd is, dat uitloggen terugstuurt naar `/login`, en dat de algehele visuele indruk consistent is (niet: vijf losse, onsamenhangende paginastijlen).

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/components/Layout.tsx admin/frontend/src/index.css admin/frontend/src/App.tsx admin/frontend/src/main.tsx .gitignore
git commit -m "feat: navigatie, samenhangende basisstijl, .gitignore voor de frontend"
```

---

### Task 10: Deployment (build + backend serveert de frontend, of losse nginx — README)

**Files:**
- Modify: `admin/app/main.py` (serveer `admin/frontend/dist/` als static files, zodat één service zowel de API als de UI aanbiedt — simpeler dan een aparte webserver voor een hobbyproject)
- Modify: `README.md` (frontend-build-stap in de deployment-paragraaf)

**Interfaces:**
- Consumes: FastAPI's ingebouwde `StaticFiles`-ondersteuning (al een dependency van `fastapi[standard]`/`uvicorn[standard]`, geen nieuwe dependency)

Dit is glue-code (static-file-serving), geen geautomatiseerde test — handmatige verificatie hieronder.

- [ ] **Step 1: Voeg static-file-serving toe aan `admin/app/main.py`**

Lees het huidige bestand eerst (na alle 12 taken van plan 2 is het al vrij groot) en voeg **aan het einde van `create_app`, na alle `include_router`-aanroepen** het volgende toe (API-routes moeten eerst gematcht worden, anders vangt de static-file-mount alles af):

```python
from fastapi.staticfiles import StaticFiles

# ... (bij de overige imports bovenaan het bestand)

# Onderaan create_app(), na alle app.include_router(...)-regels:
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
```

De `if os.path.isdir(...)`-check is bewust: in de testomgeving (waar de tests draaien) bestaat `admin/frontend/dist/` niet (niemand runt `npm run build` voor een pytest-run), dus de mount wordt daar overgeslagen en de bestaande router-tests blijven ongewijzigd werken.

- [ ] **Step 2: Syntax-/importcontrole + volledige pytest-suite**

Run: `python3 -c "import ast; ast.parse(open('admin/app/main.py').read())"`
Run: `.venv/bin/python3 -m pytest tests/ -v` — verwacht nog steeds alle bestaande tests groen (deze taak voegt er geen toe; de nieuwe mount wordt in de testomgeving overgeslagen, zie Step 1).

- [ ] **Step 3: Update `README.md`**

Voeg een stap toe aan de deployment-paragraaf (die plan 2's fix-golf al aanmaakte): `cd admin/frontend && npm install && npm run build` vóórdat de backend gestart wordt, zodat `admin/frontend/dist/` bestaat en de backend de UI meeserveert. Vermeld dat de beheerpagina dan bereikbaar is op `http://<backend-host>:<ADMIN_PORT>/`.

- [ ] **Step 4: Handmatige verificatie (vereist een lopende broker + minstens één node om zinvol te zijn)**

```bash
cd admin/frontend && npm install && npm run build
cd ../.. && ADMIN_PASSWORD=test python3 -m admin.run
```

Verwacht: `http://localhost:8000/` toont de beheerpagina (niet een 404), API-routes onder `/api/...` blijven werken.

- [ ] **Step 5: Commit**

```bash
git add admin/app/main.py README.md
git commit -m "feat: backend serveert de gebouwde frontend, deployment-instructies bijgewerkt"
```

---

## Na dit plan

Alle drie plannen van de beheerpagina-feature zijn nu compleet: plan 1 (nodes live-configureerbaar), plan 2 (backend met auth/media/MQTT-brug/scheduler/HA-proxy), plan 3 (deze frontend). Pure logica (overlay-wiskunde, WS-log-parsing) heeft Vitest-dekking; de rest van de frontend is UI/glue-code met handmatige verificatie, conform de conventie die dit hele project al hanteert voor fysieke/IO-code. Een end-to-end-avondsimulatie op locatie (uit plan 0's spec) is de laatste stap die nog niemand geautomatiseerd kán doen — dat blijft met opzet een menselijke taak.
