import { expect, test } from "@playwright/test";

test.setTimeout(90_000);
const backendPort = process.env.KB_AI_E2E_BACKEND_PORT ?? "8010";
const backendUrl = `http://127.0.0.1:${backendPort}`;

test("sample cafe completes through the actual FastAPI HTTP boundary", async ({
  page,
}) => {
  const apiResponses: Array<{ url: string; status: number }> = [];
  page.on("response", (response) => {
    if (response.url().startsWith(backendUrl)) {
      apiResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await page.goto("/dashboard");
  await page.getByRole("button", { name: /샘플 카페 불러오기/ }).click();
  await page.getByRole("button", { name: "주소 확인" }).click();
  await expect(page.getByText(/확인됨.*37\.500\d+/)).toBeVisible();
  for (let step = 0; step < 4; step += 1) {
    await page.getByRole("button", { name: /^다음/ }).click();
  }
  await page.getByRole("button", { name: "분석 시작" }).click();
  await expect(
    page.getByRole("heading", { name: "분석을 준비하고 있습니다" }),
  ).toBeVisible();
  await page.waitForURL(/\/analyses\/RUN-[A-Z0-9-]+\/overview$/, {
    timeout: 80_000,
  });
  await expect(
    page.getByRole("heading", { name: "DEMO-CAFE-2026" }),
  ).toBeVisible();
  await expect(page.getByText("DETERMINISTIC_FIXTURE")).toHaveCount(0);

  const paths = apiResponses.map(({ url }) => new URL(url).pathname);
  expect(paths).toEqual(
    expect.arrayContaining([
      "/health",
      "/v1/locations/geocode",
      "/v1/analyses",
    ]),
  );
  expect(
    paths.some((path) => /^\/v1\/analyses\/RUN-[A-Z0-9-]+$/.test(path)),
  ).toBe(true);
  expect(
    paths.some((path) => /^\/v1\/analyses\/RUN-[A-Z0-9-]+\/result$/.test(path)),
  ).toBe(true);
  expect(
    apiResponses.every(({ status }) => status >= 200 && status < 300),
  ).toBe(true);
});
