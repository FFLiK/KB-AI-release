import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

mkdirSync(resolve("..", ".test-tmp"), { recursive: true });
const python =
  process.env.KB_AI_PYTHON ??
  (process.platform === "win32"
    ? "..\\backend\\.venv\\Scripts\\python.exe"
    : "../backend/.venv/bin/python");
const backendPort = process.env.KB_AI_E2E_BACKEND_PORT ?? "8010";
const frontendPort = process.env.KB_AI_E2E_FRONTEND_PORT ?? "5174";
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-real" }],
  ],
  outputDir: "test-results/playwright-real",
  timeout: 45_000,
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn src.api.main:app --app-dir ../backend --host 127.0.0.1 --port ${backendPort}`,
      url: `${backendUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        KB_AI_SKIP_DOTENV: "1",
        RESEARCH_PROVIDER_MODE: "fake",
        API_AUTH_MODE: "none",
        DB_SCHEMA_MODE: "auto",
        RESEARCH_DATABASE_URL: "sqlite:///../.test-tmp/frontend-smoke.db",
        CORS_ALLOWED_ORIGINS: frontendUrl,
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      url: frontendUrl,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        VITE_API_BASE_URL: backendUrl,
      },
    },
  ],
  projects: [
    { name: "chromium-real-http", use: { ...devices["Desktop Chrome"] } },
  ],
});
