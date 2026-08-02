import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import App from "./App";
import { API_BASE, api } from "./api/client";
import { isTerminalJobState } from "./lib/jobs";
import {
  completedResult,
  evidenceReplayResult,
  noEventResult,
  partialResult,
} from "./test/fixtures";
import { server } from "./test/server";

function renderRoute(route: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function resultHandler(result = completedResult) {
  return http.get(`${API_BASE}/v1/analyses/:runId/result`, () =>
    HttpResponse.json(result),
  );
}

describe("MSW integration coverage", () => {
  beforeEach(() => localStorage.clear());
  it("covers queued, running, completed, partial and failed jobs", async () => {
    const states = ["QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED"];
    let call = 0;
    server.use(
      http.get(`${API_BASE}/v1/analyses/RUN-LIFE`, () => {
        const status = states[call++];
        return HttpResponse.json({
          run_id: "RUN-LIFE",
          status,
          result_id: ["COMPLETED", "PARTIAL"].includes(status) ? "AR-1" : null,
          result_version: 1,
          created_at: "2026-07-29T00:00:00Z",
          updated_at: "2026-07-29T00:00:01Z",
          error: status === "FAILED" ? { message: "합성 실패" } : null,
        });
      }),
    );
    const observed = [];
    for (const expectedState of states) {
      const currentState = (await api.job("RUN-LIFE")).status;
      expect(currentState).toBe(expectedState);
      observed.push(currentState);
    }
    expect(observed).toEqual(states);
    expect(observed.filter(isTerminalJobState)).toEqual([
      "COMPLETED",
      "PARTIAL",
      "FAILED",
    ]);
  });
  it("renders a structured failed job", async () => {
    server.use(
      http.get(`${API_BASE}/v1/analyses/RUN-FAIL`, () =>
        HttpResponse.json({
          run_id: "RUN-FAIL",
          status: "FAILED",
          result_id: null,
          result_version: null,
          created_at: "2026-07-29T00:00:00Z",
          updated_at: "2026-07-29T00:00:01Z",
          error: { message: "합성 제공자 실패" },
        }),
      ),
    );
    renderRoute("/analyses/RUN-FAIL/progress");
    expect(
      await screen.findByText(/분석 작업이 실패했습니다/),
    ).toBeInTheDocument();
    expect(screen.getByText("실패")).toBeInTheDocument();
  });
  it("renders partial status without hiding usable result layers", async () => {
    server.use(resultHandler(partialResult));
    renderRoute("/analyses/RUN-E2E/overview");
    expect(
      await screen.findByRole("heading", {
        name: "항목별 분석 현황",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/정책 후보의 조사 상태/)).toBeInTheDocument();
  });
  it("shows trend, official-data and AI research forecast layers", async () => {
    server.use(resultHandler());
    const overview = renderRoute("/analyses/RUN-E2E/overview");
    expect(await screen.findByText("내부 추세 예측")).toBeInTheDocument();
    expect(screen.getByText("공식 데이터 반영 예측")).toBeInTheDocument();
    expect(screen.getByText("AI 조사 이벤트 반영 예측")).toBeInTheDocument();
    overview.unmount();
  });
  it("labels recorded replay evidence and keeps reference findings financially inactive", async () => {
    server.use(resultHandler(evidenceReplayResult));
    renderRoute("/analyses/ABC-C-REPLAY/overview");
    expect(await screen.findByText("저장된 데이터로 분석")).toBeInTheDocument();
    expect(
      screen.getByText(/동일한 데이터 기준으로 결과를 다시 확인할 수 있습니다/),
    ).toBeInTheDocument();
  });

  it("labels synthetic replay data as non-live evidence", async () => {
    const syntheticReplay = structuredClone(evidenceReplayResult);
    if (!syntheticReplay.evidence_replay) {
      throw new Error("Synthetic replay fixture is required.");
    }
    syntheticReplay.evidence_replay.mode = "SYNTHETIC_DEMO_REPLAY";
    syntheticReplay.evidence_replay.notice = "Controlled synthetic fixture.";
    server.use(resultHandler(syntheticReplay));
    renderRoute("/analyses/ABC-C-REPLAY/overview");
    expect(
      await screen.findByText(/Synthetic demo data only - not live evidence/),
    ).toBeInTheDocument();
  });
  it("distinguishes a genuine no-event run from source or provider failure", async () => {
    server.use(resultHandler(noEventResult));
    renderRoute("/analyses/RUN-NO-EVENT/events");
    expect(
      (await screen.findAllByText("검증된 주요 이슈를 찾지 못했습니다."))[0],
    ).toBeInTheDocument();
    expect(screen.getByText(/사용 가능 문서 7건/)).toBeInTheDocument();
  });
  it("discloses incomplete research separately from a genuine zero result", async () => {
    const incomplete = structuredClone(noEventResult);
    if (!incomplete.research.funnel) {
      throw new Error("조사 퍼널 픽스처가 필요합니다.");
    }
    incomplete.research.funnel.provider_failure_count = 1;
    incomplete.research.funnel.access_failure_count = 1;
    if (!incomplete.research.agent_summaries?.[0]) {
      throw new Error("에이전트 요약 픽스처가 필요합니다.");
    }
    incomplete.research.agent_summaries[0].provider_failure_count = 1;
    incomplete.research.agent_summaries[0].status = "PARTIAL";
    server.use(resultHandler(incomplete));

    renderRoute("/analyses/RUN-INCOMPLETE/events");

    expect(
      (
        await screen.findAllByText(
          "검증된 주요 이슈를 찾지 못했습니다. 제공자 시간 초과 또는 문서 검증 실패로 일부 조사 경로가 완료되지 않았습니다.",
        )
      )[0],
    ).toBeInTheDocument();
    expect(screen.getByText("미완료 조사 단계")).toBeInTheDocument();
    expect(screen.getByText("출처 접근 실패")).toBeInTheDocument();
  });

  it("explains discovery hits that could not reach document collection", async () => {
    const timedOut = structuredClone(noEventResult);
    if (!timedOut.research.funnel || !timedOut.research.agent_summaries?.[0]) {
      throw new Error("조사 진단 픽스처가 필요합니다.");
    }
    timedOut.research.funnel.discovery_hit_count = 125;
    timedOut.research.funnel.fetched_document_count = 0;
    timedOut.research.funnel.provider_failure_count = 1;
    const agent = timedOut.research.agent_summaries[0];
    agent.status = "PARTIAL";
    agent.discovered_hit_count = 125;
    agent.fetched_document_count = 0;
    agent.provider_failure_count = 1;
    agent.timeout_stage = "DOCUMENT_FETCH";
    agent.operation_timeout_counts = { DOCUMENT_FETCH_TIMEOUT: 1 };
    agent.partial_output_counts = { documents: 0, candidates: 0, findings: 0 };
    agent.elapsed_time_ms_by_stage = { search_discovery: 61000 };
    server.use(resultHandler(timedOut));

    renderRoute("/analyses/RUN-DISCOVERY-NO-FETCH/events");

    expect(
      (
        await screen.findAllByText(
          "검색 결과는 발견했지만 조사 실행 제한이 소진되어 문서 수집을 완료하지 못했습니다.",
        )
      )[0],
    ).toBeInTheDocument();
  });

  it("does not render missing official-data changes as zero", async () => {
    const result = structuredClone(completedResult);
    const first = result.official_data.collection_results?.[0];
    if (!first) throw new Error("공식 지표 픽스처가 필요합니다.");
    first.absolute_change = null;
    first.percentage_change = null;
    server.use(resultHandler(result));
    renderRoute("/analyses/RUN-E2E/official-data");
    const heading = await screen.findByRole("heading", {
      name: "한국은행 기준금리",
    });
    const card = heading.closest("article");
    expect(within(card!).getByText("— · —")).toBeInTheDocument();
  });
  it("validates CSV and loads evidence, policy and What-if responses", async () => {
    server.use(
      http.post(`${API_BASE}/v1/inputs/csv/validate`, () =>
        HttpResponse.json({
          valid_rows: [],
          errors: [{ step: "row", column: "month", message: "월 형식 오류" }],
        }),
      ),
      http.get(`${API_BASE}/v1/events/EVT-1/evidence`, () =>
        HttpResponse.json({
          event_id: "EVT-1",
          source_ids: ["SRC-1"],
          source_revision_ids: ["REV-1"],
          evidence: [{ quote: "합성 근거 인용" }],
        }),
      ),
      http.get(`${API_BASE}/v1/policies/POL-1`, () =>
        HttpResponse.json({
          policy: { policy_candidate_id: "POL-1", name: "소상공인 운영자금" },
        }),
      ),
      http.post(`${API_BASE}/v1/analyses/RUN-E2E/what-if`, () =>
        HttpResponse.json({
          base_result_id: "AR-RUN-E2E-V1",
          base_result_version: 1,
          result_id: "AR-RUN-E2E-V2",
          result_version: 2,
          scenario: completedResult.scenarios?.BASELINE,
        }),
      ),
    );
    expect((await api.validateCsv([{}])).errors?.[0]?.message).toBe(
      "월 형식 오류",
    );
    expect((await api.evidence("EVT-1")).source_ids).toEqual(["SRC-1"]);
    expect((await api.policy("POL-1")).policy.name).toBe("소상공인 운영자금");
    expect(
      (
        await api.whatIf("RUN-E2E", {
          scenario_name: "test",
          revenue_multiplier: 0.9,
          variable_cost_multiplier: 1,
          fixed_cost_multiplier: 1,
          interest_rate_delta: 0,
        })
      ).result_version,
    ).toBe(2);
  });
  it("opens rejected-candidate evidence in a focus-managed dialog", async () => {
    server.use(
      resultHandler(),
      http.get(`${API_BASE}/v1/event-candidates/EC-001/evidence`, () =>
        HttpResponse.json({
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
              access_status: "ACCESSIBLE",
              http_status: 200,
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderRoute("/analyses/RUN-E2E/events");
    await user.click(
      await screen.findByRole("button", {
        name: "Cocoa international price increase 후보 근거 열기",
      }),
    );
    expect(
      await screen.findByRole("dialog", { name: "후보 근거" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Cocoa market bulletin"),
    ).toBeInTheDocument();
  });
  it("shows policy needs-information status and What-if comparison", async () => {
    server.use(
      resultHandler(),
      http.post(`${API_BASE}/v1/analyses/RUN-E2E/what-if`, () =>
        HttpResponse.json({
          base_result_id: "AR-RUN-E2E-V1",
          base_result_version: 1,
          result_id: "AR-RUN-E2E-V2",
          result_version: 2,
          scenario: completedResult.scenarios?.BASELINE,
        }),
      ),
    );
    const policyView = renderRoute("/analyses/RUN-E2E/policies");
    expect(await screen.findByText("정보 필요")).toBeInTheDocument();
    policyView.unmount();
    const user = userEvent.setup();
    renderRoute("/analyses/RUN-E2E/what-if");
    await user.click(
      await screen.findByRole("button", { name: "변경 결과 계산" }),
    );
    expect(await screen.findByText(/파생 버전 2/)).toBeInTheDocument();
    expect(
      screen.getByRole("table", {
        name: "기준 결과와 파생 결과 기말 현금 비교",
      }),
    ).toBeInTheDocument();
  });
});
