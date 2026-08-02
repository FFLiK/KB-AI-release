import { ArrowRight, BarChart3, Landmark, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import type { Result } from "../../api/client";
import { formatWon, UNKNOWN_VALUE } from "../../lib/formatters";
import {
  analysisCodeLabel,
  analysisStatusLabel,
  sectionEffect,
  sectionLabel,
  uiMessageLabel,
} from "./localization";

const endingCash = (
  scenario: NonNullable<Result["scenarios"]>[string] | null | undefined,
) => scenario?.monthly_cash_flows.at(-1)?.ending_cash_krw;
const signedWon = (value: unknown) => {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const number = Number(value);
  if (!Number.isFinite(number)) return UNKNOWN_VALUE;
  return `${number > 0 ? "+" : ""}${formatWon(number)}`;
};
const statusClass = (status: unknown) =>
  `status status-${String(status ?? "UNKNOWN").toLowerCase()}`;

function LayerCard({
  icon,
  step,
  title,
  description,
  status,
  ending,
  delta,
  primary,
  evidence,
  href,
  tone,
}: {
  icon: React.ReactNode;
  step: string;
  title: string;
  description: string;
  status: string;
  ending: unknown;
  delta: string;
  primary: string;
  evidence: string;
  href: string;
  tone: string;
}) {
  return (
    <article className={`analysis-layer analysis-layer--${tone}`}>
      <header className="layer-heading">
        <span className="layer-icon" aria-hidden="true">
          {icon}
        </span>
        <div>
          <small>{step}</small>
          <h2>{title}</h2>
        </div>
        <span className={statusClass(status)}>
          <span aria-hidden="true" />
          {analysisStatusLabel(status)}
        </span>
      </header>
      <p>{description}</p>
      <div className="layer-metric">
        <span>기말 현금</span>
        <b>{formatWon(ending)}</b>
      </div>
      <dl className="layer-facts">
        <div>
          <dt>이전 단계 대비 차이</dt>
          <dd>{delta}</dd>
        </div>
        <div>
          <dt>주요 변화</dt>
          <dd>{primary}</dd>
        </div>
      </dl>
      <footer className="layer-footer">
        <small className="layer-evidence">{evidence}</small>
        <Link className="layer-link" to={href}>
          상세 보기 <ArrowRight aria-hidden="true" />
        </Link>
      </footer>
    </article>
  );
}

export function OverviewRedesign({
  result,
  runId,
}: {
  result: Result;
  runId: string;
}) {
  const collections = result.official_data.collection_results ?? [];
  const completed = collections.filter((item) => item.status === "COMPLETED");
  const funnel = result.research.funnel;
  const trendOfficial = (result.forecast_layer_comparisons ?? []).find(
    (item) =>
      item.base_layer === "TREND" && item.comparison_layer === "OFFICIAL",
  );
  const officialHighImpact = (result.forecast_layer_comparisons ?? []).find(
    (item) => item.comparison_layer === "AI_HIGH_IMPACT",
  );
  const officialPrimary = [...(trendOfficial?.attribution ?? [])]
    .filter((item) => Number(item.signed_cash_effect_krw) !== 0)
    .sort(
      (a, b) =>
        Math.abs(Number(b.signed_cash_effect_krw)) -
        Math.abs(Number(a.signed_cash_effect_krw)),
    )[0];
  const highImpactPrimary = [...(officialHighImpact?.attribution ?? [])]
    .filter((item) => Number(item.signed_cash_effect_krw) !== 0)
    .sort(
      (a, b) =>
        Math.abs(Number(b.signed_cash_effect_krw)) -
        Math.abs(Number(a.signed_cash_effect_krw)),
    )[0];
  const sections = Object.fromEntries(Object.entries(result.sections));
  const scenarios = result.scenarios ?? {};
  const baselineScenario = scenarios.BASELINE;
  const burn = baselineScenario?.cash_burn_result;
  const store = result.input_snapshot.store_profile as Record<string, unknown>;
  return (
    <section className="page">
      <div className="result-header">
        <div>
          <span className="eyebrow">분석 결과 요약</span>
          <h1>{String(store.store_id ?? "점포")}</h1>
          <p>
            {String(store.address ?? "주소 정보 없음")} · 분석 기준일{" "}
            {result.as_of_date}
          </p>
        </div>
        <div>
          <span className={statusClass(result.status)}>
            <span aria-hidden="true" />
            {analysisStatusLabel(result.status)}
          </span>
          <small>결과 버전 {result.result_version}</small>
        </div>
      </div>
      {result.evidence_replay && (
        <aside className="card replay-banner" role="note">
          <strong>저장된 데이터로 분석</strong>
          <span>동일한 데이터 기준으로 결과를 다시 확인할 수 있습니다.</span>
          {result.evidence_replay.mode === "SYNTHETIC_DEMO_REPLAY" && (
            <span className="replay-notice">
              Synthetic demo data only - not live evidence.{" "}
              {result.evidence_replay.notice}
            </span>
          )}

          <small>
            데이터 세트 {result.evidence_replay.fixture_id} · 출처{" "}
            {(result.evidence_replay.source_urls ?? []).length}건
          </small>
        </aside>
      )}
      <div className="analysis-flow" aria-label="세 단계 예측 결과">
        <LayerCard
          icon={<BarChart3 />}
          step="1단계 · 내부 데이터"
          title="내부 추세 예측"
          description="과거 매출과 현재 비용 구조를 바탕으로 점포의 기본 흐름을 살펴봅니다."
          status={String(sections.BASELINE?.status ?? "COMPLETED")}
          ending={endingCash(result.trend_scenario)}
          delta="비교 기준 단계"
          primary="내부 매출 추세"
          evidence={`${result.trend_baseline?.monthly_forecasts?.length ?? 0}개월 전망 · 점포 데이터 기준`}
          href={`/analyses/${runId}/forecast`}
          tone="trend"
        />
        <ArrowRight className="layer-arrow" aria-hidden="true" />
        <LayerCard
          icon={<Landmark />}
          step="2단계 · 공식 데이터"
          title="공식 데이터 반영 예측"
          description="분석 기준일에 확인된 공식 경제지표를 월별 전망에 반영합니다."
          status={String(
            sections.OFFICIAL_DATA?.status ?? result.official_data.status,
          )}
          ending={endingCash(scenarios.BASELINE)}
          delta={signedWon(trendOfficial?.ending_cash_delta_krw)}
          primary={
            officialPrimary
              ? `${analysisCodeLabel(officialPrimary.component)}: ${signedWon(officialPrimary.signed_cash_effect_krw)}`
              : "재무 변화 없음"
          }
          evidence={`${collections.length}개 중 ${completed.length}개 지표 수집 성공 · 관측값 ${(result.official_data.observations ?? []).length}건`}
          href={`/analyses/${runId}/official-data`}
          tone="official"
        />
        <ArrowRight className="layer-arrow" aria-hidden="true" />
        <LayerCard
          icon={<Sparkles />}
          step="3단계 · AI 조사"
          title="AI 조사 이벤트 반영 예측"
          description="점포와 관련성이 높은 시장 이슈를 선별해 시나리오에 반영합니다."
          status={
            result.research.risk_status ??
            String(sections.RESEARCH?.status ?? "UNKNOWN")
          }
          ending={endingCash(scenarios.HIGH_IMPACT ?? scenarios.LOW_IMPACT)}
          delta={signedWon(officialHighImpact?.ending_cash_delta_krw)}
          primary={
            highImpactPrimary
              ? `${analysisCodeLabel(highImpactPrimary.component)}: ${signedWon(highImpactPrimary.signed_cash_effect_krw)}`
              : result.research.no_signal_explanation
                ? "전망에 반영한 주요 이슈 없음"
                : "재무 변화 없음"
          }
          evidence={`검색 ${funnel?.query_count ?? 0}건 · 문서 ${funnel?.document_count ?? 0}건 · 후보 ${funnel?.candidate_count ?? 0}건 · 전망 반영 ${funnel?.applied_signal_count ?? 0}건`}
          href={`/analyses/${runId}/events`}
          tone="ai"
        />
      </div>
      <div className="kpis">
        <article className="kpi">
          <span>현재 보유 현금</span>
          <b>{formatWon(store.current_cash_krw)}</b>
          <small>점포 입력값</small>
        </article>
        <article className="kpi">
          <span>공식 데이터 반영 기말 현금</span>
          <b>{formatWon(endingCash(scenarios.BASELINE))}</b>
          <small>공식 지표 반영 결과</small>
        </article>
        <article className="kpi">
          <span>유동성 위험일</span>
          <b>{burn?.liquidity_risk_date ?? UNKNOWN_VALUE}</b>
          <small>최소 운영 현금 미달 시점</small>
        </article>
        <article className="kpi">
          <span>현금 소진일</span>
          <b>{burn?.cash_burn_date ?? UNKNOWN_VALUE}</b>
          <small>
            {analysisStatusLabel(burn?.horizon_status ?? "UNKNOWN")}
          </small>
        </article>
      </div>
      <div className="section-heading">
        <div>
          <span className="eyebrow">분석 상태</span>
          <h2>항목별 분석 현황</h2>
        </div>
        <p>항목별 데이터 반영 상태와 주요 참고 사항을 확인할 수 있습니다.</p>
      </div>
      <div className="section-status-grid">
        {(result.section_status_summary ?? []).map((item) => (
          <article className="section-status-card" key={item.section}>
            <header>
              <h3>{sectionLabel(item.section, item.label)}</h3>
              <span className={statusClass(item.status)}>
                <span aria-hidden="true" />
                {analysisStatusLabel(item.status)}
              </span>
            </header>
            <b>처리 기록 {item.record_count}건</b>
            <p>{sectionEffect(item.section, item.effect)}</p>
            {[...(item.failure_codes ?? []), ...(item.warnings ?? [])].map(
              (warning) => (
                <small key={warning}>{analysisCodeLabel(warning)}</small>
              ),
            )}
          </article>
        ))}
      </div>
      {((result.warnings ?? []).length > 0 ||
        (result.limitations ?? []).length > 0) && (
        <article className="card">
          <span className="eyebrow">참고 사항</span>
          <ul>
            {[...(result.warnings ?? []), ...(result.limitations ?? [])].map(
              (item) => (
                <li key={item}>{uiMessageLabel(item)}</li>
              ),
            )}
          </ul>
        </article>
      )}
    </section>
  );
}
