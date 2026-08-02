import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { evidenceReplayResult, partialResult } from "../src/test/fixtures";

const apiPath = (url: string) =>
  new URL(url).pathname.replace(/^\/api(?=\/)/, "");
const asRecord = (value: unknown) => value as Record<string, unknown>;

async function installDeterministicApi(
  page: Page,
  result: unknown = evidenceReplayResult,
) {
  let jobCall = 0;
  const requests: string[] = [];
  page.on("request", (request) => {
    const pathname = apiPath(request.url());
    if (pathname.startsWith("/v1/")) {
      requests.push(`${request.method()} ${pathname}`);
    }
  });
  await page.route(/\/(?:api\/)?(?:v1\/|health$|ready$)/, async (route) => {
    const request = route.request();
    const pathname = apiPath(request.url());
    const headers = {
      "access-control-allow-origin": "http://127.0.0.1:5173",
      "access-control-allow-headers":
        "content-type,idempotency-key,x-correlation-id",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-expose-headers": "x-correlation-id",
      "x-correlation-id": "E2E-CORRELATION",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers, json: body });
    if (pathname === "/health") return json({ status: "ok" });
    if (pathname === "/ready")
      return json({ status: "ready", database: "ok", queue: "ok" });
    if (pathname === "/v1/locations/geocode") {
      return json({
        normalized_address: "서울특별시 강남구 테헤란로 152",
        latitude: 37.50095,
        longitude: 127.03651,
        geocode_status: "SUCCESS",
        provider: "DETERMINISTIC_FIXTURE",
        reason: null,
      });
    }
    if (pathname === "/v1/inputs/csv/validate")
      return json({ valid_rows: [{}], errors: [] });
    if (pathname === "/v1/analyses" && request.method() === "POST") {
      const payload = asRecord(request.postDataJSON());
      const research = asRecord(payload.research_request);
      return json(
        {
          run_id: research.run_id,
          job_id: "JOB-E2E",
          status: "QUEUED",
          status_url: "/v1/analyses/RUN-E2E",
        },
        202,
      );
    }
    if (/^\/v1\/analyses\/[^/]+$/.test(pathname)) {
      const states = ["QUEUED", "RUNNING", "COMPLETED"];
      const status = states[Math.min(jobCall++, states.length - 1)];
      return json({
        run_id: "RUN-E2E",
        status,
        result_id: status === "COMPLETED" ? "AR-RUN-E2E-V1" : null,
        result_version: status === "COMPLETED" ? 1 : null,
        created_at: "2026-07-29T00:00:00Z",
        updated_at: "2026-07-29T00:00:01Z",
        error: null,
      });
    }
    if (/^\/v1\/analyses\/[^/]+\/result$/.test(pathname)) return json(result);
    if (/^\/v1\/analyses\/[^/]+\/what-if$/.test(pathname)) {
      const scenario = asRecord(asRecord(result).scenarios).BASELINE;
      return json({
        base_result_id: "AR-RUN-E2E-V1",
        base_result_version: 1,
        result_id: "AR-RUN-E2E-V2",
        result_version: 2,
        scenario,
      });
    }
    if (pathname === "/v1/event-candidates/EC-001/evidence") {
      return json({
        candidate_id: "EC-001",
        validation_status: "RETRYABLE",
        failure_codes: ["DATE_PARSE_FAILED"],
        failure_details: [
          {
            code: "DATE_PARSE_FAILED",
            message:
              "The candidate date could not be normalized deterministically.",
            retryable: true,
          },
        ],
        retry: {
          attempted: true,
          outcome: "RETRYABLE",
          candidate_id: "EC-001",
        },
        evidence: [
          {
            quote:
              "Cocoa international prices increased as of January 16, 2025.",
            source_id: "SRC-1",
            source_revision_id: "REV-1",
          },
        ],
        sources: [
          {
            source_id: "SRC-1",
            source_revision_id: "REV-1",
            title: "Cocoa market bulletin",
            publisher: "Synthetic ministry",
            canonical_url: "https://example.com/cocoa",
            retrieved_at: "2026-07-29T09:00:00Z",
            access_status: "ACCESSIBLE",
            http_status: 200,
          },
        ],
      });
    }
    if (pathname === "/v1/events/EVT-1/evidence") {
      return json({
        event_id: "EVT-1",
        source_ids: ["SRC-1"],
        source_revision_ids: ["REV-1"],
        evidence: [
          {
            quote:
              "Cocoa international prices increased as of January 16, 2025.",
            source_revision_id: "REV-1",
          },
        ],
      });
    }
    if (pathname === "/v1/policies/POL-GANGNAM-INTEREST-2026") {
      return json({
        policy: {
          policy_candidate_id: "POL-GANGNAM-INTEREST-2026",
          name: "2026년 강남구 중소기업·소상공인 대출이자 지원사업",
          provider_raw: "강남구청",
        },
      });
    }
    return json({ detail: "테스트 라우트가 없습니다." }, 404);
  });
  return requests;
}

async function advanceWizard(page: Page) {
  await page.getByRole("button", { name: /샘플 카페 불러오기/ }).click();
  await expect(
    page.getByRole("heading", { name: "새 분석 만들기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^다음/ }).click();
  await expect(page.getByRole("alert")).toContainText("주소를 확인");
  await page.getByRole("button", { name: "주소 확인" }).click();
  await expect(page.getByText(/확인됨/)).toContainText("37.50095");
  await page.getByRole("button", { name: /^다음/ }).click();
  const firstRevenue = page.getByLabel("2026-01 revenue");
  await firstRevenue.fill("24900000");
  await page.getByText("CSV 데이터 가져오기").click();
  await page.getByRole("button", { name: "데이터 확인" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "데이터 확인" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^다음/ }).click();
  await page.getByRole("button", { name: /^다음/ }).click();
  await page.getByRole("button", { name: /^다음/ }).click();
  await expect(
    page.getByRole("heading", { name: "입력 내용 확인" }),
  ).toBeVisible();
}

test("critical desktop workflow covers the full analysis lifecycle", async ({
  page,
}) => {
  const requests = await installDeterministicApi(page);
  await page.goto("/dashboard");
  await advanceWizard(page);
  await page.getByRole("button", { name: "분석 시작" }).click();
  await page.waitForURL(/\/analyses\/RUN-[A-Z0-9-]+\/overview$/, {
    timeout: 10_000,
  });
  await expect(
    page.getByRole("heading", { name: "DEMO-CAFE-2026" }),
  ).toBeVisible();
  await expect(page.getByText("저장된 데이터로 분석")).toBeVisible();

  await page.getByRole("link", { name: "예측 및 현금흐름" }).click();
  await expect(
    page.getByRole("heading", { name: "예측 근거별 비교" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "공식 데이터 월별 현금흐름" }),
  ).toBeVisible();
  await expect(page.getByText("현금 BEP")).toBeVisible();
  await expect(page.getByText("₩21,000,000")).toBeVisible();

  await page.getByRole("link", { name: "주요 이슈" }).click();
  await expect(
    page.getByRole("heading", { name: "선별된 주요 이슈" }),
  ).toBeVisible();
  await expect(page.getByText("강남 카페 인근 보행로 일부 통제")).toBeVisible();
  await expect(page.getByRole("heading", { name: "참고 발견" })).toBeVisible();
  await expect(page.getByText("적용하지 않음")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "미승인 이벤트 후보" }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Cocoa international price increase 후보 근거 열기",
    })
    .click();
  await expect(page.getByRole("dialog", { name: "후보 근거" })).toBeFocused();
  await expect(page.getByRole("dialog", { name: "후보 근거" })).toContainText(
    "Cocoa international prices increased as of January 16, 2025.",
  );
  await page.getByRole("button", { name: "상세 창 닫기" }).click();
  await expect(
    page.getByRole("button", {
      name: "Cocoa international price increase 후보 근거 열기",
    }),
  ).toBeFocused();

  await page.getByRole("link", { name: "지원 정책" }).click();
  await expect(page.getByText("정보 필요")).toBeVisible();
  await page.getByRole("button", { name: "정책 상세 열기" }).click();
  await expect(page.getByRole("dialog", { name: "정책 상세" })).toContainText(
    "2026년 강남구 중소기업·소상공인 대출이자 지원사업",
  );
  await page.getByRole("button", { name: "상세 창 닫기" }).click();

  await page.getByRole("link", { name: "가정 변경" }).click();
  await page.getByRole("button", { name: "변경 결과 계산" }).click();
  await expect(page.getByText(/기준 버전 1 → 파생 버전 2/)).toBeVisible();
  await expect(
    page.getByRole("table", { name: "기준 결과와 파생 결과 기말 현금 비교" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "다크 테마" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "라이트 테마" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByRole("button", { name: "시스템 설정 테마" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  expect(requests).toEqual(
    expect.arrayContaining([
      "POST /v1/locations/geocode",
      "POST /v1/analyses",
      "GET /v1/event-candidates/EC-001/evidence",
      "GET /v1/policies/POL-GANGNAM-INTEREST-2026",
    ]),
  );
  expect(
    requests.some((item) => /^GET \/v1\/analyses\/RUN-[A-Z0-9-]+$/.test(item)),
  ).toBe(true);
  expect(
    requests.some((item) =>
      /^GET \/v1\/analyses\/RUN-[A-Z0-9-]+\/result$/.test(item),
    ),
  ).toBe(true);
  expect(
    requests.some((item) =>
      /^POST \/v1\/analyses\/RUN-[A-Z0-9-]+\/what-if$/.test(item),
    ),
  ).toBe(true);
});

test("mobile navigation, focus handling and automated accessibility", async ({
  page,
}) => {
  await installDeterministicApi(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dashboard");
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "본문으로 건너뛰기" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(page.getByRole("link", { name: "새 분석" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "메뉴 열기" })).toBeFocused();
  const lightResults = await new AxeBuilder({ page }).analyze();
  expect(lightResults.violations).toEqual([]);
  await page.getByRole("button", { name: "다크 테마" }).first().click();
  const darkResults = await new AxeBuilder({ page }).analyze();
  expect(darkResults.violations).toEqual([]);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const transitionDuration = await page
    .getByRole("button", { name: /샘플 카페 불러오기/ })
    .evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(Number.parseFloat(transitionDuration)).toBeLessThanOrEqual(0.00001);
});

test("responsive light and dark visual QA has no horizontal viewport overflow", async ({
  page,
}, testInfo) => {
  await installDeterministicApi(page);
  await page.addInitScript(() =>
    localStorage.setItem("kb-last-run", "RUN-E2E"),
  );
  const sizes = [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1280, height: 800 },
    { width: 1440, height: 900 },
  ];
  for (const theme of ["light", "dark"] as const) {
    for (const size of sizes) {
      await page.setViewportSize(size);
      await page.goto("/analyses/RUN-E2E/overview");
      await page.evaluate(
        (value) => localStorage.setItem("kb-theme", value),
        theme,
      );
      await page.reload();
      await expect(
        page.getByRole("heading", { name: "DEMO-CAFE-2026" }),
      ).toBeVisible();
      const layerGeometry = await page
        .locator(".analysis-layer")
        .evaluateAll((cards) =>
          cards.map((card) => ({
            display: getComputedStyle(card).display,
            width: card.getBoundingClientRect().width,
            headingWidth:
              card.querySelector("h2")?.getBoundingClientRect().width ?? 0,
          })),
        );
      expect(layerGeometry).toHaveLength(3);
      expect(
        layerGeometry.every(
          (item) =>
            item.display !== "flex" && item.width > 0 && item.headingWidth > 0,
        ),
      ).toBe(true);
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(
        overflow,
        `${theme} ${size.width}x${size.height} overflow`,
      ).toBeLessThanOrEqual(1);
      await page.screenshot({
        path: testInfo.outputPath(
          `overview-${theme}-${size.width}x${size.height}.png`,
        ),
        fullPage: true,
      });
    }
  }
});

test("partial, loading, empty and service failure states remain explicit", async ({
  page,
}, testInfo) => {
  await installDeterministicApi(page, partialResult);
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: /사업의 다음 달을/ }),
  ).toBeVisible();
  await page.evaluate(() => localStorage.setItem("kb-last-run", "RUN-E2E"));
  await page.goto("/analyses/RUN-E2E/overview");
  await expect(
    page.getByRole("heading", { name: "항목별 분석 현황" }),
  ).toBeVisible();
  await expect(page.getByText(/정책 후보의 조사 상태/)).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("partial-result.png"),
    fullPage: true,
  });

  await page.route(
    /\/(?:api\/)?v1\/analyses\/RUN-ERROR\/result$/,
    async (route) => {
      await route.fulfill({
        status: 503,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-expose-headers": "x-correlation-id",
          "x-correlation-id": "E2E-503",
        },
        json: { detail: "합성 서비스 중단" },
      });
    },
  );
  await page.goto("/analyses/RUN-ERROR/overview");
  await expect(page.getByRole("alert")).toContainText("합성 서비스 중단");
  await expect(page.getByText("상관관계 ID: E2E-503")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("service-failure.png"),
    fullPage: true,
  });
});
