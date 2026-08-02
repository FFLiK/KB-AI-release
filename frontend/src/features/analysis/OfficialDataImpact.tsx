import { useState } from "react";
import { Landmark } from "lucide-react";
import type { Result } from "../../api/client";
import { formatDate, formatWon, UNKNOWN_VALUE } from "../../lib/formatters";
import {
  analysisCodeLabel,
  analysisStatusLabel,
  assumptionLabel,
  failureMessage,
  indicatorLabel,
} from "./localization";

const decimal = (value: unknown, digits = 2) => {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits }).format(
        number,
      )
    : String(value);
};

const signed = (value: unknown, formatter = decimal) => {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const number = Number(value);
  if (!Number.isFinite(number)) return UNKNOWN_VALUE;
  return `${number > 0 ? "+" : ""}${formatter(number)}`;
};

const percentage = (value: unknown) => {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  return `${signed(Number(value) * 100)}%`;
};

export function OfficialDataImpactView({ result }: { result: Result }) {
  const [indicatorFilter, setIndicatorFilter] = useState("ALL");
  const [qualityFilter, setQualityFilter] = useState("ALL");
  const official = result.official_data;
  const collections = official.collection_results ?? [];
  const observations = official.observations ?? [];
  const months = result.official_features?.months ?? [];
  const eventOverrides = result.official_features?.event_overrides ?? [];
  const comparison = (result.forecast_layer_comparisons ?? []).find(
    (item) =>
      item.base_layer === "TREND" && item.comparison_layer === "OFFICIAL",
  );
  const successful = collections.filter((item) => item.status === "COMPLETED");
  const latestPeriod = successful
    .map((item) => item.latest_observed_at)
    .filter(Boolean)
    .sort()
    .at(-1);
  const filteredObservations = observations.filter(
    (item) =>
      (indicatorFilter === "ALL" || item.indicator_id === indicatorFilter) &&
      (qualityFilter === "ALL" || item.quality_status === qualityFilter),
  );

  return (
    <section className="page official-impact-page">
      <div className="result-header">
        <div>
          <span className="eyebrow">공식 데이터 및 영향</span>
          <h1>공식 데이터 및 재무 영향</h1>
          <p>공식 경제지표가 월별 전망과 현금흐름에 미친 영향을 확인합니다.</p>
        </div>
        <span
          className={`status status-${String(official.status).toLowerCase()}`}
        >
          <span aria-hidden="true" />
          {analysisStatusLabel(official.status)}
        </span>
      </div>

      <div className="kpis official-summary" aria-label="공식 데이터 수집 요약">
        <article className="kpi">
          <span>요청 지표</span>
          <b>
            {successful.length} / {collections.length}
          </b>
          <small>수집 성공 / 전체 요청</small>
        </article>
        <article className="kpi">
          <span>관측값</span>
          <b>{observations.length}</b>
          <small>{formatDate(result.as_of_date)} 기준 사용 가능</small>
        </article>
        <article className="kpi">
          <span>최신 관측 기간</span>
          <b>{latestPeriod ?? UNKNOWN_VALUE}</b>
          <small>분석에 사용 가능한 최신 값</small>
        </article>
        <article className="kpi">
          <span>기말 현금 영향</span>
          <b>{signed(comparison?.ending_cash_delta_krw, formatWon)}</b>
          <small>공식 데이터 반영값 - 내부 추세값</small>
        </article>
      </div>

      <article className="card trace-banner">
        <Landmark aria-hidden="true" />
        <div>
          <strong>공식 관측값을 월별 전망에 반영했습니다.</strong>
          <p>
            제공기관의 최신 관측값과 발표 시점을 기준으로 분석용 월별 값을
            구성했습니다.
          </p>
        </div>
        <code>{official.snapshot_id}</code>
      </article>

      {eventOverrides.length > 0 && (
        <section aria-labelledby="official-event-bridge-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">공식 이벤트 브리지</span>
              <h2 id="official-event-bridge-title">관측 시차 보정</h2>
            </div>
            <p>
              최신 공식 결정이 월별 관측 시리즈보다 새로울 때만 임시로 적용하며,
              관측값이 따라오면 자동으로 만료합니다.
            </p>
          </div>
          <div className="indicator-grid">
            {eventOverrides.map((item) => (
              <article
                className="indicator-card"
                key={`${item.event_id}-${item.indicator_id}`}
              >
                <header>
                  <div>
                    <small>
                      {indicatorLabel(item.indicator_id)} ·{" "}
                      {item.effective_date}
                    </small>
                    <h3>
                      {decimal(item.event_value)} {analysisCodeLabel(item.unit)}
                    </h3>
                  </div>
                  <span
                    className={`status status-${String(item.status).toLowerCase()}`}
                  >
                    <span aria-hidden="true" />
                    {analysisStatusLabel(item.status)}
                  </span>
                </header>
                <dl className="compact-dl">
                  <div>
                    <dt>최신 기존 관측</dt>
                    <dd>
                      {decimal(item.latest_official_value)} ·{" "}
                      {item.latest_official_observed_at ?? UNKNOWN_VALUE}
                    </dd>
                  </div>
                  <div>
                    <dt>판정 사유</dt>
                    <dd>{analysisCodeLabel(item.reason_code)}</dd>
                  </div>
                  <div>
                    <dt>임시 관측 ID</dt>
                    <dd>{item.synthetic_observation_id ?? "적용 없음"}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="section-heading">
        <div>
          <span className="eyebrow">수집 결과</span>
          <h2>요청한 공식 지표</h2>
        </div>
        <p>분석에 사용한 지표와 최신 수집 상태를 함께 보여드립니다.</p>
      </div>
      <div className="indicator-grid">
        {collections.map((item) => (
          <article
            className={`indicator-card indicator-card--${String(item.status).toLowerCase()}`}
            key={item.indicator_id}
          >
            <header>
              <div>
                <small>
                  {item.provider} ·{" "}
                  {item.metadata.provider_series_code ?? "시리즈 코드 없음"}
                </small>
                <h3>
                  {indicatorLabel(
                    item.indicator_id,
                    item.metadata.display_name,
                  )}
                </h3>
              </div>
              <span
                className={`status status-${String(item.status).toLowerCase()}`}
              >
                <span aria-hidden="true" />
                {analysisStatusLabel(item.status)}
              </span>
            </header>
            <div className="indicator-value-row">
              <div>
                <span>최신 관측값</span>
                <b>
                  {decimal(item.latest_value)}{" "}
                  {analysisCodeLabel(item.unit ?? item.metadata.unit ?? "")}
                </b>
                <small>{item.latest_observed_at ?? UNKNOWN_VALUE}</small>
              </div>
              <div>
                <span>이전 관측값</span>
                <b>
                  {decimal(item.previous_value)}{" "}
                  {analysisCodeLabel(item.unit ?? item.metadata.unit ?? "")}
                </b>
                <small>
                  관측 ID {item.previous_observation_id ?? UNKNOWN_VALUE}
                </small>
              </div>
              <div>
                <span>증감</span>
                <b>
                  {signed(item.absolute_change)} ·{" "}
                  {percentage(item.percentage_change)}
                </b>
                <small>절대 변화 · 변화율</small>
              </div>
            </div>
            <dl className="compact-dl">
              <div>
                <dt>분석 반영</dt>
                <dd>{analysisCodeLabel(item.metadata.feature_role)}</dd>
              </div>
              <div>
                <dt>영향 항목</dt>
                <dd>
                  {analysisCodeLabel(item.metadata.affected_model_dimension)}
                </dd>
              </div>
              <div>
                <dt>공표 시각</dt>
                <dd>{formatDate(item.latest_released_at)}</dd>
              </div>
              <div>
                <dt>사용 가능 시각</dt>
                <dd>{formatDate(item.latest_available_at)}</dd>
              </div>
              <div>
                <dt>최신성</dt>
                <dd>
                  {analysisStatusLabel(item.freshness_status)} ·{" "}
                  {item.freshness_age_days ?? UNKNOWN_VALUE} /{" "}
                  {item.freshness_max_age_days ??
                    item.metadata.max_age_days ??
                    UNKNOWN_VALUE}{" "}
                  일
                </dd>
              </div>
              <div>
                <dt>필수 여부</dt>
                <dd>{item.required ? "필수" : "선택"}</dd>
              </div>
            </dl>
            {item.failure_code && (
              <div className="limitation-callout">
                <strong>{analysisCodeLabel(item.failure_code)}</strong>
                <span>
                  {failureMessage(item.failure_code, item.failure_detail)}
                </span>
                <small>
                  {item.required
                    ? "필수 지표를 사용할 수 없어 해당 단계가 정상 완료되지 않았습니다."
                    : "선택 지표를 제외하고 나머지 데이터로 계산을 계속했습니다."}
                </small>
              </div>
            )}
            <details>
              <summary>추적 ID 및 변환 방식</summary>
              <code>{item.latest_observation_id ?? "관측 ID 없음"}</code>
              <p>{item.metadata.transformation_method}</p>
            </details>
          </article>
        ))}
      </div>

      <div className="section-heading">
        <div>
          <span className="eyebrow">변환 과정</span>
          <h2>월별 지표 예측 입력</h2>
        </div>
        <p>
          공식 지표가 매출·재료비·금리 가정에 반영된 흐름을 월별로 확인합니다.
        </p>
      </div>
      <div className="table-wrap attribution-table">
        <table>
          <caption>분석에 반영한 월별 지표와 재무 가정</caption>
          <thead>
            <tr>
              <th>월</th>
              <th>지표 예측값</th>
              <th>매출</th>
              <th>국내 재료비</th>
              <th>수입 재료비</th>
              <th>통합 재료비</th>
              <th>금리 변화</th>
              <th>추적 정보</th>
            </tr>
          </thead>
          <tbody>
            {months.map((month) => (
              <tr key={month.month}>
                <td>
                  <strong>{month.month}</strong>
                  <small className="data-kind data-kind--projected">
                    예측 입력
                  </small>
                </td>
                <td>
                  {Object.entries(month.indicator_values ?? {}).map(
                    ([id, value]) => (
                      <span className="projected-value" key={id}>
                        <b>{indicatorLabel(id)}</b> {decimal(value)}
                      </span>
                    ),
                  )}
                </td>
                <td>{decimal(month.revenue_index_multiplier, 6)}</td>
                <td>{decimal(month.domestic_ingredient_cost_multiplier, 6)}</td>
                <td>{decimal(month.imported_ingredient_cost_multiplier, 6)}</td>
                <td>{decimal(month.ingredient_cost_multiplier, 6)}</td>
                <td>{decimal(month.interest_rate_delta, 6)}</td>
                <td>
                  <details>
                    <summary>
                      기여도 {month.contributions?.length ?? 0}건
                    </summary>
                    {(month.contributions ?? []).map((item) => (
                      <div
                        className="contribution"
                        key={`${item.month}-${item.indicator_id}`}
                      >
                        <strong>{indicatorLabel(item.indicator_id)}</strong>
                        <span>
                          {item.latest_value} → {item.projected_value}
                        </span>
                        <small>
                          원 변화율{" "}
                          {decimal(Number(item.relative_change) * 100, 3)}% ·
                          상한 적용{" "}
                          {decimal(
                            Number(item.capped_relative_change) * 100,
                            3,
                          )}
                          % · 감쇠 {decimal(item.decay_factor, 2)} · 누적 변화{" "}
                          {decimal(
                            Number(item.cumulative_relative_change) * 100,
                            3,
                          )}
                          % (상한 ±
                          {decimal(
                            Number(item.cumulative_horizon_cap) * 100,
                            1,
                          )}
                          %) · 특성 기여도 Δ{" "}
                          {signed(item.contributed_multiplier_delta)}
                        </small>
                        <code>{item.latest_observation_id}</code>
                      </div>
                    ))}
                    <p>
                      {(month.assumptions ?? [])
                        .map(assumptionLabel)
                        .join(" · ")}
                    </p>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-heading">
        <div>
          <span className="eyebrow">재무 영향 분해</span>
          <h2>내부 추세 → 공식 데이터 반영</h2>
        </div>
        <p>
          기능 그룹 단위로 금액 영향을 분해하며 개별 지표의 정확한 금액 효과를
          의미하지는 않습니다.
        </p>
      </div>
      {comparison ? (
        <>
          <div className="waterfall" aria-label="공식 데이터 재무 영향 분해">
            {(comparison.attribution ?? []).map((item) => (
              <div className="waterfall-row" key={item.component}>
                <span>{analysisCodeLabel(item.component)}</span>
                <div>
                  <i
                    style={{
                      width: `${Math.max(3, Math.min(100, (Math.abs(Number(item.signed_cash_effect_krw)) / Math.max(1, Math.abs(Number(comparison.ending_cash_delta_krw)))) * 100))}%`,
                    }}
                    className={
                      Number(item.signed_cash_effect_krw) >= 0
                        ? "positive"
                        : "negative"
                    }
                  />
                </div>
                <b>{signed(item.signed_cash_effect_krw, formatWon)}</b>
              </div>
            ))}
            <div className="waterfall-total">
              <span>공식 데이터 반영 기말 현금 차이</span>
              <b>{signed(comparison.ending_cash_delta_krw, formatWon)}</b>
            </div>
          </div>
          <div className="table-wrap financial-delta-table">
            <table>
              <caption>내부 추세 대비 공식 데이터 반영 월별 차이</caption>
              <thead>
                <tr>
                  <th>월</th>
                  <th>내부 추세 매출</th>
                  <th>공식 데이터 반영 매출</th>
                  <th>매출 차이</th>
                  <th>내부 추세 재료비</th>
                  <th>공식 데이터 반영 재료비</th>
                  <th>재료비 절감</th>
                  <th>이자 차이</th>
                  <th>순현금흐름 차이</th>
                  <th>누적 기말 현금 차이</th>
                </tr>
              </thead>
              <tbody>
                {(comparison.monthly_deltas ?? []).map((row) => (
                  <tr key={row.month}>
                    <td>{row.month}</td>
                    <td>{formatWon(row.base_revenue_cash_krw)}</td>
                    <td>{formatWon(row.comparison_revenue_cash_krw)}</td>
                    <td>{signed(row.revenue_cash_delta_krw, formatWon)}</td>
                    <td>{formatWon(row.base_ingredient_cost_krw)}</td>
                    <td>{formatWon(row.comparison_ingredient_cost_krw)}</td>
                    <td>
                      {signed(row.ingredient_cost_savings_krw, formatWon)}
                    </td>
                    <td>{signed(row.interest_payment_delta_krw, formatWon)}</td>
                    <td>{signed(row.net_cash_flow_delta_krw, formatWon)}</td>
                    <td>{signed(row.ending_cash_delta_krw, formatWon)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <article className="empty">비교 결과를 불러오지 못했습니다.</article>
      )}

      <div className="section-heading">
        <div>
          <span className="eyebrow">데이터 상세</span>
          <h2>관측값과 출처 정보</h2>
        </div>
        <div className="audit-filters">
          <label>
            지표
            <select
              value={indicatorFilter}
              onChange={(event) => setIndicatorFilter(event.target.value)}
            >
              <option value="ALL">전체</option>
              {collections.map((item) => (
                <option key={item.indicator_id}>{item.indicator_id}</option>
              ))}
            </select>
          </label>
          <label>
            품질
            <select
              value={qualityFilter}
              onChange={(event) => setQualityFilter(event.target.value)}
            >
              <option value="ALL">전체</option>
              <option value="VALID">유효</option>
              <option value="STALE">오래됨</option>
              <option value="REVISED">수정됨</option>
              <option value="REJECTED">거절됨</option>
            </select>
          </label>
        </div>
      </div>
      <div className="table-wrap audit-table">
        <table>
          <caption>분석 기준일에 이용 가능한 공식 관측값</caption>
          <thead>
            <tr>
              <th>지표</th>
              <th>제공기관</th>
              <th>관측일</th>
              <th>값</th>
              <th>공표일</th>
              <th>사용 가능일</th>
              <th>품질</th>
              <th>출처</th>
              <th>개정본</th>
              <th>빈티지</th>
              <th>정규화 규칙</th>
            </tr>
          </thead>
          <tbody>
            {filteredObservations.map((item) => {
              const collection = collections.find(
                (entry) => entry.indicator_id === item.indicator_id,
              );
              return (
                <tr key={item.observation_id}>
                  <td>
                    <strong>{indicatorLabel(item.indicator_id)}</strong>
                    <small className="data-kind data-kind--observed">
                      관측값
                    </small>
                  </td>
                  <td>{collection?.provider ?? UNKNOWN_VALUE}</td>
                  <td>{item.observed_at}</td>
                  <td>
                    {decimal(item.value)} {analysisCodeLabel(item.unit)}
                  </td>
                  <td>{formatDate(item.released_at)}</td>
                  <td>{formatDate(item.available_at)}</td>
                  <td>{analysisStatusLabel(item.quality_status)}</td>
                  <td>
                    <code>{item.source_id}</code>
                  </td>
                  <td>
                    <code>{item.source_revision_id}</code>
                  </td>
                  <td>
                    <code>{item.vintage_id}</code>
                  </td>
                  <td>{item.normalization_rule_id}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
