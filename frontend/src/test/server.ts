import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { API_BASE } from "../api/client";

export const server = setupServer(
  http.get(`${API_BASE}/health`, () => HttpResponse.json({ status: "ok" })),
  http.get(`${API_BASE}/ready`, () =>
    HttpResponse.json({ status: "ready", database: "ok", queue: "ok" }),
  ),
);
