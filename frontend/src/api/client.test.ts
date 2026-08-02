import { afterEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { API_BASE, ApiError, api, normalizeHttpError, request } from "./client";
import { server } from "../test/server";

describe("API client normalization", () => {
  afterEach(() => server.resetHandlers());
  it.each([404, 409, 422, 429, 503])(
    "normalizes HTTP %s with correlation context",
    async (status) => {
      server.use(
        http.get(`${API_BASE}/error-${status}`, () =>
          HttpResponse.json(
            {
              detail:
                status === 422
                  ? [
                      {
                        loc: ["body", "store_profile", "address"],
                        msg: "필수 값",
                      },
                    ]
                  : undefined,
            },
            { status, headers: { "X-Correlation-ID": `COR-${status}` } },
          ),
        ),
      );
      await expect(request(`/error-${status}`)).rejects.toMatchObject({
        status,
        correlationId: `COR-${status}`,
      });
    },
  );
  it("maps 422 details to fields", () => {
    const error = normalizeHttpError(422, {
      detail: [{ loc: ["body", "store_profile", "address"], msg: "필수 값" }],
    });
    expect(error.fieldErrors["store_profile.address"]).toBe("필수 값");
  });
  it("normalizes network failures", async () => {
    server.use(http.get(`${API_BASE}/network`, () => HttpResponse.error()));
    await expect(request("/network")).rejects.toEqual(
      expect.objectContaining({ status: 0 }),
    );
  });
  it("sends stable idempotency and correlation headers", async () => {
    let headers: Headers | undefined;
    server.use(
      http.post(`${API_BASE}/v1/analyses`, ({ request }) => {
        headers = request.headers;
        return HttpResponse.json(
          {
            run_id: "RUN-1",
            status: "QUEUED",
            status_url: "/status",
            result_url: "/result",
          },
          { status: 202 },
        );
      }),
    );
    await api.submit({} as never, "stable-key");
    expect(headers?.get("Idempotency-Key")).toBe("stable-key");
    expect(headers?.get("X-Correlation-ID")).toBeTruthy();
  });
  it("never exposes stack-like detail text", () =>
    expect(
      normalizeHttpError(503, { detail: "Traceback API_KEY=secret" }),
    ).toBeInstanceOf(ApiError));
});
