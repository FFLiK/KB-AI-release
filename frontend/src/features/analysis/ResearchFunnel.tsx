import type { Result } from "../../api/client";
import { analysisCodeLabel, analysisStatusLabel } from "./localization";

const researchStages = [
  {
    title: "검색 · 수집",
    metrics: [
      ["검색어", "query_count"],
      ["검색 결과", "discovery_hit_count"],
    ],
  },
  {
    title: "출처 검증",
    metrics: [
      ["최종 출처", "resolved_source_count"],
      ["사용 가능 문서", "usable_document_count"],
    ],
  },
  {
    title: "이슈 선별",
    metrics: [
      ["참고 발견", "reference_finding_count"],
      ["관련 이슈", "candidate_count"],
    ],
  },
  {
    title: "전망 반영",
    metrics: [
      ["선별 완료", "accepted_event_count"],
      ["전망 반영", "applied_signal_count"],
    ],
  },
] as const;

const noSignalTitle = (result: Result) => {
  const funnel = result.research.funnel;
  const riskProviderFailures = (result.research.agent_summaries ?? [])
    .filter((agent) => agent.category === "RISK_RESEARCH")
    .reduce((total, agent) => total + (agent.provider_failure_count ?? 0), 0);
  const collectionTimedOut = (result.research.agent_summaries ?? []).some(
    (agent) =>
      (agent.discovered_hit_count ?? 0) > 0 &&
      (agent.fetched_document_count ?? 0) === 0 &&
      Boolean(agent.timeout_stage),
  );
  const usableDocuments =
    funnel?.usable_document_count ?? funnel?.document_count ?? 0;
  const referenceFindings =
    funnel?.reference_finding_count ??
    result.research.reference_findings?.length ??
    0;
  const rejectedCandidates =
    funnel?.rejected_candidate_count ??
    result.research.rejected_events?.length ??
    0;
  const incomplete =
    riskProviderFailures > 0 || (funnel?.access_failure_count ?? 0) > 0;
  if (collectionTimedOut)
    return "검색 결과는 발견했지만 조사 실행 제한이 소진되어 문서 수집을 완료하지 못했습니다.";
  if (incomplete)
    return "검증된 주요 이슈를 찾지 못했습니다. 제공자 시간 초과 또는 문서 검증 실패로 일부 조사 경로가 완료되지 않았습니다.";

  void usableDocuments;
  void referenceFindings;
  void rejectedCandidates;
  return "검증된 주요 이슈를 찾지 못했습니다.";
};

export function ResearchFunnel({ result }: { result: Result }) {
  const research = result.research;
  const policyCounts = result.policies?.stage_counts;
  const incompleteStageCount = (research.agent_summaries ?? []).filter(
    (agent) =>
      ["PARTIAL", "FAILED"].includes(agent.status) ||
      agent.provider_failure_count > 0,
  ).length;
  const sourceAccessFailures = research.funnel?.access_failure_count ?? 0;
  const attentionItems = [
    ["검증된 주요 이슈", research.funnel?.accepted_event_count ?? 0],
    ["참고 전용 발견", research.funnel?.reference_finding_count ?? 0],
    ["정책 후보", policyCounts?.extracted_candidates ?? 0],
    ["신청 가능 정책", policyCounts?.eligible_policies ?? 0],
    ["미완료 조사 단계", incompleteStageCount],
    ["출처 접근 실패", sourceAccessFailures],
  ].filter(([, value]) => Number(value) > 0);
  return (
    <>
      <div className="research-funnel" aria-label="AI 위험 조사 단계">
        {researchStages.map((stage, index) => (
          <article className="funnel-stage" key={stage.title}>
            <span className="funnel-stage-title">
              <em>{String(index + 1).padStart(2, "0")}</em>
              {stage.title}
            </span>
            <dl>
              {stage.metrics.map(([label, key]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>
                    {(research.funnel?.[key] ?? 0).toLocaleString("ko-KR")}
                  </dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>

      <section
        className="research-status-summary"
        aria-label="조사 결과 상태 요약"
      >
        <div>
          <span className="eyebrow">조사 현황</span>
          <strong>
            {attentionItems.length > 0
              ? "확인이 필요한 항목이 있습니다"
              : "현재 반영할 시장 이슈가 없습니다"}
          </strong>
        </div>
        {attentionItems.length > 0 && (
          <div className="research-status-items">
            {attentionItems.map(([label, value]) => (
              <span key={String(label)}>
                {String(label)} <b>{Number(value).toLocaleString("ko-KR")}</b>
              </span>
            ))}
          </div>
        )}
      </section>
      {research.no_signal_explanation && (
        <article className="card no-signal-explanation">
          <strong>{noSignalTitle(result)}</strong>
          <ul>
            <li>
              검색 {research.funnel?.query_count ?? 0}건, 최종 출처{" "}
              {research.funnel?.resolved_source_count ?? 0}건, 사용 가능 문서{" "}
              {research.funnel?.usable_document_count ?? 0}건을 처리했습니다.
            </li>
            <li>
              참고 자료 {research.funnel?.reference_finding_count ?? 0}건, 관련
              후보 {research.funnel?.candidate_count ?? 0}건, 선별 완료 이벤트{" "}
              {research.funnel?.accepted_event_count ?? 0}건입니다.
            </li>
            {(research.funnel?.access_failure_count ?? 0) > 0 && (
              <li>
                출처 접근 실패가 {research.funnel?.access_failure_count ?? 0}건
                있습니다.
              </li>
            )}
            {(research.funnel?.provider_failure_count ?? 0) > 0 && (
              <li>
                외부 데이터 처리 실패가{" "}
                {research.funnel?.provider_failure_count ?? 0}건 있습니다. 다른
                문서의 사용 가능한 결과는 유지했습니다.
              </li>
            )}
          </ul>
          <p>
            이번 분석에서는 현금흐름 전망을 조정할 만큼 관련성이 높은 이슈가
            확인되지 않았다는 의미입니다.
          </p>
          <div className="badges">
            {(research.no_signal_explanation.reason_codes ?? []).map((code) => (
              <span key={code}>{analysisCodeLabel(code)}</span>
            ))}
          </div>
        </article>
      )}

      {(research.reference_findings ?? []).length > 0 && (
        <section aria-labelledby="reference-findings-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">재무 미적용 참고 근거</span>
              <h2 id="reference-findings-title">참고 발견</h2>
            </div>
            <p>
              점포와 관련된 참고 자료지만 이번 현금흐름 전망에는 반영하지
              않았습니다.
            </p>
          </div>
          <div className="agent-grid">
            {(research.reference_findings ?? []).map((finding) => (
              <article
                className="agent-card reference-finding-card"
                key={finding.finding_id}
              >
                <header>
                  <h3>{finding.title}</h3>
                  <span className="status status-skipped">참고 전용</span>
                </header>
                <p>{finding.relevance_summary}</p>
                <dl>
                  <div>
                    <dt>조사 영역</dt>
                    <dd>{analysisCodeLabel(finding.agent_type)}</dd>
                  </div>
                  <div>
                    <dt>전망 반영</dt>
                    <dd>적용하지 않음</dd>
                  </div>
                  <div>
                    <dt>후속 확인</dt>
                    <dd>{analysisCodeLabel(finding.recommended_follow_up)}</dd>
                  </div>
                </dl>
                <div className="badges">
                  <span>{analysisCodeLabel(finding.reason_code)}</span>
                  {(finding.missing_requirements ?? []).map((code) => (
                    <span key={code}>{analysisCodeLabel(code)}</span>
                  ))}
                </div>
                {(finding.evidence ?? []).map((evidence) => (
                  <blockquote key={evidence.evidence_id}>
                    {evidence.quote}
                  </blockquote>
                ))}
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="section-heading">
        <div>
          <span className="eyebrow">시장 이슈 탐색</span>
          <h2>분야별 조사 결과</h2>
        </div>
        <p>
          분야별로 확인한 자료와 점포 전망에 반영한 이슈를 정리했습니다.
          않습니다.
        </p>
      </div>
      <div className="agent-grid">
        {(research.agent_summaries ?? [])
          .filter((agent) => agent.category === "RISK_RESEARCH")
          .map((agent) => (
            <article className="agent-card" key={agent.agent_type}>
              <header>
                <h3>{analysisCodeLabel(agent.agent_type)}</h3>
                <span className={`status status-${agent.status.toLowerCase()}`}>
                  <span aria-hidden="true" />
                  {analysisStatusLabel(agent.status)}
                </span>
              </header>
              <dl>
                <div>
                  <dt>검색어</dt>
                  <dd>{agent.query_count}</dd>
                </div>
                <div>
                  <dt>수집 문서</dt>
                  <dd>{agent.document_count}</dd>
                </div>
                <div>
                  <dt>발견 결과</dt>
                  <dd>{agent.discovered_hit_count ?? 0}</dd>
                </div>
                <div>
                  <dt>수집 완료</dt>
                  <dd>{agent.fetched_document_count ?? 0}</dd>
                </div>
                <div>
                  <dt>사용 가능</dt>
                  <dd>{agent.usable_document_count}</dd>
                </div>
                <div>
                  <dt>참고 발견</dt>
                  <dd>{agent.finding_count}</dd>
                </div>
                <div>
                  <dt>관련 이슈</dt>
                  <dd>{agent.candidate_count}</dd>
                </div>
              </dl>
              <details className="technical-details">
                <summary>처리 세부 정보</summary>
                <dl>
                  <div>
                    <dt>접근 실패</dt>
                    <dd>{agent.access_failure_count}</dd>
                  </div>
                  <div>
                    <dt>외부 처리 실패</dt>
                    <dd>{agent.provider_failure_count}</dd>
                  </div>
                  <div>
                    <dt>중복 제외</dt>
                    <dd>{agent.deduplicated_document_count}</dd>
                  </div>
                  <div>
                    <dt>처리 시간</dt>
                    <dd>{agent.total_latency_ms}ms</dd>
                  </div>
                  <div>
                    <dt>타임아웃 단계</dt>
                    <dd>
                      {agent.timeout_stage
                        ? analysisCodeLabel(agent.timeout_stage)
                        : "없음"}
                    </dd>
                  </div>
                  <div>
                    <dt>작업별 타임아웃</dt>
                    <dd>
                      {Object.entries(agent.operation_timeout_counts ?? {})
                        .map(
                          ([code, count]) =>
                            `${analysisCodeLabel(code)} ${count}`,
                        )
                        .join(" · ") || "없음"}
                    </dd>
                  </div>
                  <div>
                    <dt>단계별 처리 시간</dt>
                    <dd>
                      {Object.entries(agent.elapsed_time_ms_by_stage ?? {})
                        .map(
                          ([stage, elapsed]) =>
                            `${analysisCodeLabel(stage)} ${elapsed}ms`,
                        )
                        .join(" · ") || "기록 없음"}
                    </dd>
                  </div>
                  <div>
                    <dt>부분 산출물</dt>
                    <dd>
                      {Object.entries(agent.partial_output_counts ?? {})
                        .map(
                          ([kind, count]) =>
                            `${analysisCodeLabel(kind)} ${count}`,
                        )
                        .join(" · ") || "없음"}
                    </dd>
                  </div>
                  <div>
                    <dt>데이터 제공</dt>
                    <dd>
                      {[
                        ...(agent.providers ?? []),
                        ...(agent.models ?? []),
                      ].join(" · ") || "기록 없음"}
                    </dd>
                  </div>
                </dl>
              </details>
              {(agent.no_result_reasons ?? []).length > 0 && (
                <div className="badges">
                  {(agent.no_result_reasons ?? []).map((reason) => (
                    <span key={reason}>{analysisCodeLabel(reason)}</span>
                  ))}
                </div>
              )}
            </article>
          ))}
      </div>

      <div className="section-heading policy-separation">
        <div>
          <span className="eyebrow">지원 정책</span>
          <h2>정책 탐색 결과</h2>
        </div>
        <span
          className={`status status-${String(research.policy_status ?? "UNKNOWN").toLowerCase()}`}
        >
          <span aria-hidden="true" />
          {analysisStatusLabel(research.policy_status ?? "UNKNOWN")}
        </span>
      </div>
      {(research.agent_summaries ?? [])
        .filter((agent) => agent.category === "POLICY")
        .map((agent) => (
          <article className="agent-card" key={agent.agent_type}>
            <header>
              <h3>{analysisCodeLabel(agent.agent_type)}</h3>
              <span>{analysisStatusLabel(agent.status)}</span>
            </header>
            <p>
              검색 {agent.query_count}건 · 문서 {agent.document_count}건 · 사용
              가능 {agent.usable_document_count}건 · 정책 후보{" "}
              {agent.candidate_count}건
            </p>
            {agent.provider_failure_count > 0 && (
              <p className="warning-copy">
                관련 출처를 찾았지만 일부 문서의 구조화 추출이 실패했습니다.
                다른 조사와 재무 결과는 계속 사용할 수 있습니다.
              </p>
            )}
            <div className="badges">
              {(agent.no_result_reasons ?? []).map((reason) => (
                <span key={reason}>{analysisCodeLabel(reason)}</span>
              ))}
            </div>
          </article>
        ))}
    </>
  );
}
