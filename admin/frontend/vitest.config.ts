import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// ponytail: vitest.config.ts wint van vite.config.ts's `test`-veld (geen
// merge), dus de setup/includes staan hier, niet (alleen) in vite.config.ts.
// environment blijft globaal op het (impliciete) "node" default -- de
// bestaande tests/frontend-tests zijn pure functies zonder DOM en breken op
// jsdom-omgeving (Vite's loader kan dan de buiten-root ../../tests-bestanden
// niet meer laden); component-tests die een DOM nodig hebben zetten zelf
// `// @vitest-environment jsdom` bovenaan het bestand.
export default defineConfig({
  plugins: [react()],
  test: {
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    include: ["../../tests/frontend/**/*.test.ts", "src/**/*.test.{ts,tsx}"],
  },
});
