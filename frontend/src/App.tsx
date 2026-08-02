import { useEffect, useRef, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  BarChart3,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  FileSearch,
  Landmark,
  LoaderCircle,
  Menu,
  Monitor,
  Moon,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { api, ApiError, type Result } from "./api/client";
import KoreanDashboard from "./KoreanDashboard";
import {
  createAnalysisRequest,
  createWhatIfRequest,
  sampleForm,
  sampleHistory,
  type AnalysisForm,
  type HistoryRow,
} from "./features/analysis/request";
import { OfficialDataImpactView } from "./features/analysis/OfficialDataImpact";
import { OverviewRedesign } from "./features/analysis/OverviewRedesign";
import { ResearchFunnel } from "./features/analysis/ResearchFunnel";
import {
  analysisCodeLabel,
  analysisStatusLabel,
  failureMessage,
  policyReasonLabel,
  signalEligibilityLabel,
} from "./features/analysis/localization";
import { formatDate, formatWon, UNKNOWN_VALUE } from "./lib/formatters";
import {
  canOpenJobResult,
  isTerminalJobState,
  jobPollingInterval,
  jobStateLabel,
  normalizeJobState,
} from "./lib/jobs";
import { useThemePreference, type ThemePreference } from "./theme";

type UnknownRecord = Record<string, unknown>;
const asRecord = (value: unknown): UnknownRecord | undefined =>
  value && typeof value === "object" ? (value as UnknownRecord) : undefined;
const asRecords = (value: unknown): UnknownRecord[] =>
  Array.isArray(value)
    ? value.filter((item): item is UnknownRecord => Boolean(asRecord(item)))
    : [];
const valueOf = (result: Result | undefined, key: string): unknown =>
  asRecord(result)?.[key];
const scenarioOf = (result: Result | undefined, name = "BASELINE") =>
  asRecord(asRecord(valueOf(result, "scenarios"))?.[name]);
function StatusPill({ status }: { status: unknown }) {
  const normalized = normalizeJobState(status);
  return (
    <span
      className={`status status-${normalized.toLowerCase()}`}
      aria-label={`상태: ${analysisStatusLabel(normalized)}`}
    >
      <span aria-hidden="true" />
      {analysisStatusLabel(normalized)}
    </span>
  );
}
function BackendStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: false,
  });
  return (
    <span
      className={`backend ${health.isSuccess ? "online" : "offline"}`}
      role="status"
      title={health.isSuccess ? "API 연결됨" : "API 연결을 확인하세요"}
    >
      <i aria-hidden="true" />
      {health.isSuccess ? "데이터 연결됨" : "연결 확인 필요"}
    </span>
  );
}
const workspace = [
  ["overview", "종합 요약", BarChart3],
  ["forecast", "예측 및 현금흐름", Activity],
  ["events", "주요 이슈", AlertTriangle],
  ["policies", "지원 정책", Landmark],
  ["evidence", "데이터 상세", FileSearch],
  ["what-if", "가정 변경", Sparkles],
  ["official-data", "공식 데이터", Landmark],
] as const;
function Shell({
  children,
  theme,
  setTheme,
}: {
  children: React.ReactNode;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const routeRun = location.pathname.match(/^\/analyses\/([^/]+)/)?.[1];
  const run = routeRun ?? localStorage.getItem("kb-last-run");
  useEffect(() => {
    if (open) closeButton.current?.focus();
  }, [open]);
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);
  const close = () => {
    setOpen(false);
    requestAnimationFrame(() => menuButton.current?.focus());
  };
  return (
    <>
      <a className="skip" href="#main">
        본문으로 건너뛰기
      </a>
      {open && (
        <button
          className="nav-backdrop"
          aria-label="메뉴 닫기"
          onClick={close}
        />
      )}
      <aside
        className={`sidebar ${open ? "open" : ""}`}
        aria-label="주요 탐색"
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
        }}
      >
        <div className="brand">
          <span className="brand-mark">K</span>
          <span>
            KB AI <small>BUSINESS INSIGHT</small>
          </span>
          <button
            ref={closeButton}
            className="icon mobile-only"
            onClick={close}
            aria-label="메뉴 닫기"
          >
            <X />
          </button>
        </div>
        <nav>
          <NavLink to="/dashboard">
            <BarChart3 /> 대시보드
          </NavLink>
          <NavLink to="/analyses/new">
            <Plus /> 새 분석
          </NavLink>
          <NavLink to="/analyses/open">
            <FileSearch /> 이전 분석 열기
          </NavLink>
          <p className="nav-label">분석 워크스페이스</p>
          {workspace.map(([path, label, Icon]) => (
            <NavLink
              key={path}
              className={!run ? "disabled" : ""}
              to={run ? `/analyses/${run}/${path}` : "/analyses/open"}
              aria-disabled={!run}
            >
              <Icon />
              {label}
            </NavLink>
          ))}
          <p className="nav-label">도움말</p>
          <NavLink to="/settings">
            <CircleHelp /> 설정 및 안내
          </NavLink>
        </nav>
        <footer>
          <span>KB AI Business Insight</span>
          <small>사업의 흐름을 더 선명하게</small>
        </footer>
      </aside>
      <div className="shell">
        <header className="topbar">
          <button
            ref={menuButton}
            className="icon mobile-only"
            onClick={() => setOpen(true)}
            aria-label="메뉴 열기"
          >
            <Menu />
          </button>
          <div className="crumb">
            KB AI <ChevronRight /> <span>소상공인 분석</span>
          </div>
          <div className="top-actions">
            <BackendStatus />
            <ThemeButtons value={theme} onChange={setTheme} compact />
            <NavLink className="new-button" to="/analyses/new">
              <Plus /> 새 분석
            </NavLink>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </>
  );
}
function ThemeButtons({
  value,
  onChange,
  compact = false,
}: {
  value: ThemePreference;
  onChange: (theme: ThemePreference) => void;
  compact?: boolean;
}) {
  const options: [ThemePreference, string, React.ReactNode][] = [
    ["light", "라이트", <Sun />],
    ["dark", "다크", <Moon />],
    ["system", "시스템 설정", <Monitor />],
  ];
  return (
    <div
      className={compact ? "theme" : "theme-options"}
      role="group"
      aria-label="테마 선택"
    >
      {options.map(([key, label, icon]) => (
        <button
          key={key}
          className={value === key ? (compact ? "selected" : "active") : ""}
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          aria-label={`${label} 테마`}
        >
          {compact ? icon : label}
        </button>
      ))}
    </div>
  );
}
function Notice({
  children,
  kind = "info",
  role,
}: {
  children: React.ReactNode;
  kind?: "info" | "warning" | "danger";
  role?: "alert" | "status";
}) {
  return (
    <div className={`notice ${kind}`} role={role}>
      <AlertTriangle aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
function Dashboard() {
  const run = localStorage.getItem("kb-last-run");
  return run ? (
    <Navigate to={`/analyses/${run}/overview`} replace />
  ) : (
    <KoreanDashboard />
  );
}
function Field({
  id,
  label,
  value,
  change,
  type = "text",
  hint,
  readOnly,
  error,
  min,
  step,
}: {
  id: string;
  label: string;
  value: string;
  change: (value: string) => void;
  type?: string;
  hint?: string;
  readOnly?: boolean;
  error?: string;
  min?: string;
  step?: string;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        onChange={(event) => change(event.target.value)}
        readOnly={readOnly}
        min={min}
        step={step}
        aria-invalid={Boolean(error)}
        aria-describedby={
          [hintId, errorId].filter(Boolean).join(" ") || undefined
        }
      />
      {hint && <small id={hintId}>{hint}</small>}
      {error && (
        <small id={errorId} className="field-error">
          {error}
        </small>
      )}
    </div>
  );
}
function Wizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<AnalysisForm>({ ...sampleForm });
  const [history, setHistory] = useState<HistoryRow[]>(
    sampleHistory.map((row) => ({ ...row })),
  );
  const [coordinates, setCoordinates] = useState<{
    latitude: string | number;
    longitude: string | number;
  }>();
  const [csv, setCsv] = useState(
    '[{"schema_version":"store_history.v1","month":"2026-06","revenue_krw":"30000000","variable_costs_krw":"9000000","fixed_costs_krw":"10100000"}]',
  );
  const [csvMessage, setCsvMessage] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [idempotencyKey] = useState(() => `web-${crypto.randomUUID()}`);
  const update = (key: keyof AnalysisForm, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const geocode = useMutation({
    mutationFn: () => api.geocode(form.address),
    onSuccess: (response) => {
      if (
        response.geocode_status === "SUCCESS" &&
        response.latitude != null &&
        response.longitude != null
      ) {
        setCoordinates({
          latitude: response.latitude,
          longitude: response.longitude,
        });
        setErrors((current) => ({ ...current, address: "" }));
      } else {
        setCoordinates(undefined);
        setErrors((current) => ({
          ...current,
          address: `주소를 확인하지 못했습니다: ${response.reason ?? response.geocode_status}`,
        }));
      }
    },
    onError: (error) =>
      setErrors((current) => ({
        ...current,
        address:
          error instanceof Error ? error.message : "주소 확인에 실패했습니다.",
      })),
  });
  const csvCheck = useMutation({
    mutationFn: () => api.validateCsv(JSON.parse(csv) as unknown[]),
    onSuccess: (response) =>
      setCsvMessage(
        (response.errors ?? []).length
          ? `검증 오류 ${(response.errors ?? []).length}건: ${(response.errors ?? []).map((item) => item.message).join(", ")}`
          : "데이터 확인을 통과했습니다.",
      ),
    onError: (error) =>
      setCsvMessage(
        error instanceof Error
          ? error.message
          : "JSON 배열과 필수 열을 확인해 주세요.",
      ),
  });
  const validateStep = () => {
    const next: Record<string, string> = {};
    if (step === 1) {
      if (!form.name.trim()) next.name = "점포 이름을 입력해 주세요.";
      if (!form.storeId.trim()) next.storeId = "점포 ID를 입력해 주세요.";
      if (!form.address.trim()) next.address = "주소를 입력해 주세요.";
      else if (!coordinates)
        next.address = "다음 단계로 이동하기 전에 주소를 확인해 주세요.";
    }
    if (
      step === 2 &&
      history.some((row) => !row.month || Number(row.revenue) < 0)
    )
      next.history = "월과 0원 이상의 매출을 확인해 주세요.";
    if (step === 3) {
      if (Number(form.cash) < 0)
        next.cash = "현재 현금은 0원 이상이어야 합니다.";
      if (Number(form.minimumCash) < 0)
        next.minimumCash = "최소 운영 현금은 0원 이상이어야 합니다.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };
  const submit = useMutation({
    mutationFn: async () => {
      const runId = `RUN-${crypto.randomUUID().slice(0, 12).toUpperCase()}`;
      return api.submit(
        createAnalysisRequest(form, history, runId, coordinates),
        idempotencyKey,
      );
    },
    onSuccess: (response) => {
      localStorage.setItem("kb-last-run", response.run_id);
      navigate(`/analyses/${response.run_id}/progress`);
    },
    onError: (error) => {
      if (error instanceof ApiError && Object.keys(error.fieldErrors).length)
        setErrors(error.fieldErrors);
    },
  });
  return (
    <section className="page wizard-page">
      <div className="page-heading">
        <span className="eyebrow">새 분석</span>
        <h1>새 분석 만들기</h1>
        <p>점포 정보부터 검토까지 다섯 단계로 입력합니다.</p>
      </div>
      {Object.values(errors).some(Boolean) && (
        <div className="error-summary" role="alert" tabIndex={-1}>
          <strong>입력 내용을 확인해 주세요.</strong>
          <ul>
            {Object.entries(errors)
              .filter(([, message]) => message)
              .map(([field, message]) => (
                <li key={field}>
                  <a href={`#${field}`}>{message}</a>
                </li>
              ))}
          </ul>
        </div>
      )}
      <ol className="stepper" aria-label="분석 입력 단계">
        {[
          "점포 정보",
          "매출·비용 이력",
          "현금·대출",
          "분석 설정",
          "검토·제출",
        ].map((label, index) => (
          <li
            key={label}
            className={
              step === index + 1 ? "active" : step > index + 1 ? "done" : ""
            }
            aria-current={step === index + 1 ? "step" : undefined}
          >
            <b>{index + 1}</b>
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <div className="wizard-card">
        {step === 1 && (
          <>
            <h2>점포 정보</h2>
            <div className="form-grid">
              <Field
                id="name"
                label="점포 이름"
                value={form.name}
                change={(value) => update("name", value)}
                error={errors.name}
              />
              <Field
                id="storeId"
                label="점포 ID"
                value={form.storeId}
                change={(value) => update("storeId", value)}
                hint="분석을 다시 확인할 때 사용하는 점포 식별 정보입니다."
                error={errors.storeId}
              />
              <Field
                id="industry"
                label="업종 분류"
                value="FNB_CAFE · 카페"
                change={() => undefined}
                readOnly
              />
              <div className="field span-2">
                <label htmlFor="address">사업장 주소</label>
                <div className="inline">
                  <input
                    id="address"
                    value={form.address}
                    onChange={(event) => {
                      update("address", event.target.value);
                      setCoordinates(undefined);
                    }}
                    aria-invalid={Boolean(errors.address)}
                    aria-describedby="address-help address-status"
                  />
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => geocode.mutate()}
                    disabled={geocode.isPending}
                  >
                    {geocode.isPending ? "주소 확인 중" : "주소 확인"}
                  </button>
                </div>
                <small id="address-help">
                  정확한 지역 지표와 지원 정책을 연결하기 위해 주소를 확인
                  합니다.
                </small>
                <div id="address-status" aria-live="polite">
                  {coordinates && (
                    <p className="field-ok">
                      <BadgeCheck /> 확인됨 · {coordinates.latitude},{" "}
                      {coordinates.longitude}
                    </p>
                  )}
                  {errors.address && (
                    <p className="field-error">{errors.address}</p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <h2>월별 매출 및 비용 이력</h2>
            <p className="muted">
              최근 6개월의 매출과 주요 비용을 원 단위로 입력해 주세요.
            </p>
            {errors.history && (
              <p className="field-error" id="history">
                {errors.history}
              </p>
            )}
            <div className="table-wrap">
              <table>
                <caption className="visually-hidden">
                  월별 점포 이력 입력
                </caption>
                <thead>
                  <tr>
                    <th>월</th>
                    <th>매출</th>
                    <th>재료비</th>
                    <th>임차료</th>
                    <th>인건비</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row, rowIndex) => (
                    <tr key={row.month}>
                      {(
                        [
                          "month",
                          "revenue",
                          "ingredients",
                          "rent",
                          "labor",
                        ] as (keyof HistoryRow)[]
                      ).map((key) => (
                        <td key={key}>
                          <input
                            aria-label={`${row.month} ${key}`}
                            value={row[key]}
                            onChange={(event) =>
                              setHistory((current) =>
                                current.map((item, index) =>
                                  index === rowIndex
                                    ? { ...item, [key]: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details>
              <summary>CSV 데이터 가져오기</summary>
              <p>CSV에서 변환한 행 데이터를 JSON 형식으로 붙여 넣어 주세요.</p>
              <textarea
                aria-label="CSV 행 JSON"
                value={csv}
                onChange={(event) => setCsv(event.target.value)}
              />
              <button
                className="secondary"
                onClick={() => csvCheck.mutate()}
                disabled={csvCheck.isPending}
              >
                데이터 확인
              </button>
              <p className="muted" role="status">
                {csvMessage}
              </p>
            </details>
          </>
        )}
        {step === 3 && (
          <>
            <h2>현금·대출 및 비용 노출</h2>
            <div className="form-grid">
              <Field
                id="cash"
                label="현재 보유 현금 (원)"
                type="number"
                min="0"
                value={form.cash}
                change={(value) => update("cash", value)}
                error={errors.cash}
              />
              <Field
                id="minimumCash"
                label="최소 운영 현금 (원)"
                type="number"
                min="0"
                value={form.minimumCash}
                change={(value) => update("minimumCash", value)}
                error={errors.minimumCash}
              />
              <Field
                id="loan"
                label="대출 잔액 (원)"
                type="number"
                min="0"
                value={form.loan}
                change={(value) => update("loan", value)}
              />
              <Field
                id="rate"
                label="연 이자율 (%)"
                type="number"
                min="0"
                step="0.1"
                value={form.rate}
                change={(value) => update("rate", value)}
              />
            </div>
            <Notice>
              입력한 현금과 비용 구조를 기준으로 손익분기점과 현금흐름을 함께
              계산합니다.
            </Notice>
          </>
        )}
        {step === 4 && (
          <>
            <h2>분석 설정</h2>
            <div className="form-grid">
              <Field
                id="asOf"
                label="기준일"
                type="date"
                value={form.asOf}
                change={(value) => update("asOf", value)}
              />
              <Field
                id="horizon"
                label="예측 기간 (개월)"
                type="number"
                min="1"
                value={form.horizon}
                change={(value) => update("horizon", value)}
              />
              <Field
                id="area"
                label="행정구역"
                value="서울특별시 강남구 · 11680"
                change={() => undefined}
                readOnly
              />
              <Field
                id="radius"
                label="검색 반경"
                value="1,500m"
                change={() => undefined}
                readOnly
              />
            </div>
            <div className="preset">
              <b>한국 F&B 기본 설정</b>
              <span>커피 원두 · 강남구 · 기준금리 및 물가 신호</span>
              <small>분석에 사용할 기본 시장 지표가 자동으로 연결됩니다.</small>
            </div>
          </>
        )}
        {step === 5 && (
          <>
            <h2>입력 내용 확인</h2>
            <div className="review">
              <div>
                <span>점포</span>
                <b>{form.name}</b>
                <small>{form.address}</small>
              </div>
              <div>
                <span>이력</span>
                <b>{history.length}개월</b>
                <small>
                  {history[0]?.month} ~ {history.at(-1)?.month}
                </small>
              </div>
              <div>
                <span>현금</span>
                <b>{formatWon(form.cash)}</b>
                <small>최소 운영 현금 {formatWon(form.minimumCash)}</small>
              </div>
              <div>
                <span>예측 범위</span>
                <b>{form.horizon}개월</b>
                <small>한국 F&B 기본 설정</small>
              </div>
            </div>
            <Notice kind="warning">
              입력 내용을 확인한 뒤 분석을 시작해 주세요. 결과 화면에서 가정을
              바꾸어 시나리오별 차이도 비교할 수 있습니다.
            </Notice>
            {submit.error && (
              <Notice kind="danger" role="alert">
                {submit.error instanceof Error
                  ? submit.error.message
                  : "분석 제출에 실패했습니다."}
              </Notice>
            )}
          </>
        )}
        <div className="wizard-actions">
          <button
            className="secondary"
            onClick={() => setStep((current) => Math.max(1, current - 1))}
            disabled={step === 1}
          >
            이전
          </button>
          {step < 5 ? (
            <button
              className="primary"
              onClick={() => {
                if (validateStep()) setStep((current) => current + 1);
              }}
            >
              다음 <ArrowRight />
            </button>
          ) : (
            <button
              className="primary"
              onClick={() => submit.mutate()}
              disabled={submit.isPending}
            >
              {submit.isPending ? (
                <>
                  <LoaderCircle className="spin" /> 제출 중
                </>
              ) : (
                "분석 시작"
              )}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
function OpenAnalysis() {
  const [runId, setRunId] = useState(localStorage.getItem("kb-last-run") ?? "");
  const navigate = useNavigate();
  return (
    <section className="page">
      <span className="eyebrow">분석 열기</span>
      <h1>이전 분석 열기</h1>
      <article className="card settings">
        <Field
          id="open-run-id"
          label="분석 ID"
          value={runId}
          change={setRunId}
          hint="분석을 시작할 때 발급된 ID를 입력해 주세요."
        />
        <button
          className="primary"
          disabled={!runId.trim()}
          onClick={() => {
            localStorage.setItem("kb-last-run", runId.trim());
            navigate(`/analyses/${encodeURIComponent(runId.trim())}/progress`);
          }}
        >
          분석 상태 확인
        </button>
      </article>
    </section>
  );
}
function Progress() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const job = useQuery({
    queryKey: ["job", runId],
    queryFn: () => api.job(runId),
    refetchInterval: (query) => jobPollingInterval(query.state.data?.status),
    retry: false,
  });
  const state = normalizeJobState(job.data?.status);
  const result = useQuery({
    queryKey: ["result", runId, job.data?.result_version],
    queryFn: () => api.result(runId, job.data?.result_version ?? undefined),
    enabled: Boolean(job.data?.result_id && canOpenJobResult(state)),
    retry: false,
  });
  useEffect(() => {
    if (result.data) navigate(`/analyses/${runId}/overview`);
  }, [navigate, result.data, runId]);
  if (job.isError) return <ErrorCard error={job.error} />;
  return (
    <section className="page progress-page">
      <span className="eyebrow">분석 작업</span>
      <h1>분석을 준비하고 있습니다</h1>
      <p>입력 데이터와 시장 정보를 연결해 결과를 구성하고 있습니다.</p>
      <div className="job-id">
        <code>{runId}</code>
        <button
          className="icon"
          onClick={() => navigator.clipboard.writeText(runId)}
          aria-label="분석 ID 복사"
        >
          <ClipboardCheck />
        </button>
      </div>
      <div className="progress-status" role="status" aria-live="polite">
        <StatusPill status={state} />
        <span>
          {job.data?.updated_at
            ? `마지막 갱신 ${formatDate(job.data.updated_at)}`
            : "작업 상태 확인 중"}
        </span>
      </div>
      <div className="section-status">
        <div className={state === "QUEUED" ? "working" : "complete"}>
          <i />
          <b>제출 접수</b>
          <small>
            {state === "QUEUED" ? "작업 실행기 대기 중" : "접수 완료"}
          </small>
        </div>
        <div
          className={
            state === "RUNNING"
              ? "working"
              : canOpenJobResult(state)
                ? "complete"
                : ""
          }
        >
          <i />
          <b>데이터 분석</b>
          <small>
            {state === "RUNNING"
              ? "현금흐름과 외부 지표 분석 중"
              : canOpenJobResult(state)
                ? "분석 완료"
                : "대기"}
          </small>
        </div>
        <div
          className={
            result.isFetching ? "working" : result.data ? "complete" : ""
          }
        >
          <i />
          <b>결과 확인</b>
          <small>
            {result.isFetching
              ? "결과 정리 중"
              : result.data
                ? "결과 확인 완료"
                : "대기"}
          </small>
        </div>
      </div>
      {state === "FAILED" && (
        <Notice kind="danger" role="alert">
          분석 작업이 실패했습니다. 입력과 단계별 상태를 확인한 뒤 다시 시도해
          주세요.
        </Notice>
      )}
      {isTerminalJobState(state) &&
        canOpenJobResult(state) &&
        result.isError && (
          <Notice kind="danger" role="alert">
            작업은 끝났지만 결과를 불러오지 못했습니다. 분석 ID를 보존하고 다시
            시도해 주세요.
          </Notice>
        )}
      <p className="progress-help">
        페이지를 닫아도 분석 ID로 언제든 다시 확인할 수 있습니다.
      </p>
    </section>
  );
}
function useResult() {
  const { runId = "" } = useParams();
  const [search] = useSearchParams();
  const version = Number(search.get("version")) || undefined;
  return {
    runId,
    version,
    ...useQuery({
      queryKey: ["result", runId, version],
      queryFn: () => api.result(runId, version),
      enabled: Boolean(runId),
      retry: false,
    }),
  };
}
function Kpi({
  label,
  value,
  caption,
  money = true,
}: {
  label: string;
  value: unknown;
  caption: string;
  money?: boolean;
}) {
  return (
    <article className="kpi">
      <span>{label}</span>
      <b>
        {value === null || value === undefined
          ? UNKNOWN_VALUE
          : money
            ? formatWon(value)
            : String(value)}
      </b>
      <small>{caption}</small>
    </article>
  );
}
function Overview() {
  const { runId, data, isLoading, isError, error } = useResult();
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  if (!data)
    return <ErrorCard error={new Error("분석 결과를 사용할 수 없습니다.")} />;
  return <OverviewRedesign result={data} runId={runId ?? data.run_id} />;
}

function OfficialDataImpact() {
  const { data, isLoading, isError, error } = useResult();
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  if (!data)
    return <ErrorCard error={new Error("분석 결과를 사용할 수 없습니다.")} />;
  return <OfficialDataImpactView result={data} />;
}

const cashColumns: [string, string][] = [
  ["beginning_cash_krw", "기초 현금"],
  ["revenue_cash_krw", "매출"],
  ["variable_costs_cash_krw", "변동비"],
  ["fixed_costs_cash_krw", "고정비"],
  ["interest_payment_krw", "이자"],
  ["principal_payment_krw", "원금"],
  ["tax_cash_outflow_krw", "세금"],
  ["net_cash_flow_krw", "순현금흐름"],
  ["ending_cash_krw", "기말 현금"],
];
function Forecast() {
  const { data, isLoading, isError, error } = useResult();
  const [layer, setLayer] = useState("OFFICIAL");
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  const scenarios = asRecord(valueOf(data, "scenarios")) ?? {};
  const officialFeatures = asRecord(valueOf(data, "official_features"));
  const officialData = asRecord(valueOf(data, "official_data"));
  const research = asRecord(valueOf(data, "research"));
  const signals = asRecords(valueOf(data, "signals"));
  const acceptedEvents = asRecords(research?.accepted_events);
  const indicatorIds = Array.isArray(officialFeatures?.indicator_ids)
    ? officialFeatures.indicator_ids.map(String)
    : [];
  const layerOptions = [
    {
      key: "TREND",
      label: "① 추세 기준선",
      data: asRecord(valueOf(data, "trend_scenario")),
      description: "과거 매출 추세와 점포 비용·대출 입력만 반영",
      evidence: `${String(asRecord(valueOf(data, "trend_baseline"))?.selected_model ?? "예측 기준 없음")} · 외부 데이터 0건`,
    },
    {
      key: "OFFICIAL",
      label: "② 공식 데이터",
      data: asRecord(scenarios.BASELINE),
      description: "공식 경제지표를 비용과 금리 노출에 추가 반영",
      evidence: `${indicatorIds.length}개 지표 · ${asRecords(officialData?.observations).length}개 관측값`,
    },
    {
      key: "LOW_IMPACT",
      label: "③ AI 저영향",
      data: asRecord(scenarios.LOW_IMPACT),
      description: "공식 데이터에 AI 조사 이벤트의 낮은 영향 강도 적용",
      evidence: `${acceptedEvents.length}개 주요 이슈 · ${signals.length}개 전망 반영`,
    },
    {
      key: "HIGH_IMPACT",
      label: "④ AI 고영향",
      data: asRecord(scenarios.HIGH_IMPACT),
      description: "공식 데이터에 AI 조사 이벤트의 높은 영향 강도 적용",
      evidence: `${acceptedEvents.length}개 주요 이슈 · ${signals.length}개 전망 반영`,
    },
  ].filter((item) => item.data);
  const selected =
    layerOptions.find((item) => item.key === layer) ?? layerOptions[0];
  const current = selected?.data;
  const rows = asRecords(current?.monthly_cash_flows);
  const burn = asRecord(current?.cash_burn_result);
  const bep = asRecords(current?.bep_results)[0];
  return (
    <section className="page">
      <span className="eyebrow">예측 단계 및 현금흐름</span>
      <h1>예측 근거별 비교</h1>
      <p className="muted forecast-intro">
        같은 점포 입력에서 외부 정보를 한 단계씩 더해 결과가 어떻게 달라지는지
        비교합니다.
      </p>
      <div
        className="scenario-tabs layer-tabs"
        role="tablist"
        aria-label="예측 계층 선택"
      >
        {layerOptions.map((item) => (
          <button
            key={item.key}
            className={selected?.key === item.key ? "active" : ""}
            role="tab"
            aria-selected={selected?.key === item.key}
            onClick={() => setLayer(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {selected && (
        <div className="forecast-layer-summary" role="status">
          <div>
            <strong>{selected.label}</strong>
            <span>{selected.description}</span>
          </div>
          <small>{selected.evidence}</small>
        </div>
      )}
      <div className="kpis">
        <Kpi
          label="현금 BEP"
          value={bep?.cash_bep_krw}
          caption={bep ? jobStateLabel(bep.bep_status) : "상태 미상"}
        />
        <Kpi
          label="회계 BEP"
          value={bep?.operating_bep_krw}
          caption={bep ? jobStateLabel(bep.bep_status) : "상태 미상"}
        />
        <Kpi
          label="유동성 위험일"
          value={burn?.liquidity_risk_date}
          caption="최소 현금 미달"
          money={false}
        />
        <Kpi
          label="현금 소진일"
          value={burn?.cash_burn_date}
          caption={analysisStatusLabel(
            burn?.horizon_status ?? "예측 기간 내 미발생",
          )}
          money={false}
        />
      </div>
      <div className="table-wrap financial">
        <table>
          <caption className="visually-hidden">
            {selected?.label ?? layer} 월별 현금흐름
          </caption>
          <thead>
            <tr>
              <th>월</th>
              {cashColumns.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={String(row.month_str ?? index)}>
                <td>{String(row.month_str ?? UNKNOWN_VALUE)}</td>
                {cashColumns.map(([key]) => (
                  <td key={key}>{formatWon(row[key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mobile-cash">
        {rows.map((row, index) => (
          <details key={String(row.month_str ?? index)}>
            <summary>
              {String(row.month_str ?? UNKNOWN_VALUE)}{" "}
              <b>{formatWon(row.ending_cash_krw)}</b>
            </summary>
            {cashColumns.map(([key, label]) => (
              <p key={key}>
                <span>{label}</span>
                {formatWon(row[key])}
              </p>
            ))}
          </details>
        ))}
      </div>
      <Notice>
        공식 지표와 AI 이벤트가 없거나 적용 조건을 충족하지 않으면 단계 간
        결과가 동일할 수 있습니다. 각 단계의 관측값과 주요 이슈 반영 수를 함께
        확인하세요.
      </Notice>
    </section>
  );
}
function FocusDialog({
  title,
  children,
  onClose,
  returnFocus,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  returnFocus?: HTMLElement | null;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    dialog.current?.focus();
    return () => returnFocus?.focus();
  }, [returnFocus]);
  const keyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") onClose();
    if (event.key === "Tab" && dialog.current) {
      const focusable = Array.from(
        dialog.current.querySelectorAll<HTMLElement>(
          'button, a[href], input, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0],
        last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };
  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div
        ref={dialog}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={keyDown}
      >
        <div className="drawer-header">
          <h2 id="dialog-title">{title}</h2>
          <button className="icon" onClick={onClose} aria-label="상세 창 닫기">
            <X />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
function Events() {
  const { data, isLoading, isError, error } = useResult();
  const [selected, setSelected] = useState<{
    id: string;
    kind: "event" | "candidate";
    trigger: HTMLElement;
  }>();
  const eventEvidence = useQuery({
    queryKey: ["event-evidence", selected?.id],
    queryFn: () => api.evidence(selected!.id),
    enabled: selected?.kind === "event",
    retry: false,
  });
  const candidateEvidence = useQuery({
    queryKey: ["candidate-evidence", selected?.id],
    queryFn: () => api.candidateEvidence(selected!.id),
    enabled: selected?.kind === "candidate",
    retry: false,
  });
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  if (!data)
    return <ErrorCard error={new Error("분석 결과를 사용할 수 없습니다.")} />;
  const accepted = data.research.accepted_events ?? [];
  const rejected = data.research.rejected_events ?? [];
  const pipelineOutcomes = data.research.event_pipeline_outcomes ?? [];
  const pipelineByEvent = new Map(
    pipelineOutcomes.flatMap((item) => [
      ...(item.event_id ? [[item.event_id, item] as const] : []),
      ...(item.candidate_id ? [[item.candidate_id, item] as const] : []),
    ]),
  );
  return (
    <section className="page research-page">
      <span className="eyebrow">AI 시장 조사</span>
      <h1>시장 이슈 분석</h1>
      <p className="muted">
        시장 이슈를 수집하고 점포와의 관련성을 확인해 현금흐름에 미치는 영향을
        정리합니다.
      </p>
      <ResearchFunnel result={data} />
      {pipelineOutcomes.length > 0 && (
        <section className="event-group" aria-labelledby="event-pipeline-title">
          <h2 id="event-pipeline-title">
            이벤트 처리 상태 <small>{pipelineOutcomes.length}</small>
          </h2>
          <div className="agent-grid">
            {pipelineOutcomes.map((item) => (
              <article
                className="agent-card event-pipeline-card"
                key={item.event_id ?? item.candidate_id ?? item.title}
              >
                <header>
                  <h3>{item.title}</h3>
                  <StatusPill status={item.terminal_status} />
                </header>
                <p>{(item.lifecycle_stages ?? []).join(" → ")}</p>
                <dl>
                  <div>
                    <dt>주요 제외 사유</dt>
                    <dd>
                      {analysisCodeLabel(
                        item.primary_exclusion_reason ?? "NONE",
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>전망 반영</dt>
                    <dd>{item.signal_eligible ? "적격" : "참고 전용"}</dd>
                  </div>
                  <div>
                    <dt>점포 거리 / 반경</dt>
                    <dd>
                      {item.store_distance_meters == null
                        ? UNKNOWN_VALUE
                        : `${Math.round(item.store_distance_meters).toLocaleString("ko-KR")}m`}
                      {item.configured_radius_meters == null
                        ? ""
                        : ` / ${Math.round(item.configured_radius_meters).toLocaleString("ko-KR")}m`}
                    </dd>
                  </div>
                  <div>
                    <dt>재무 노출</dt>
                    <dd>
                      {analysisCodeLabel(item.financial_exposure_relevance)}
                    </dd>
                  </div>
                </dl>
                <p className="rule-explanation">
                  {item.expected_impact_if_unblocked}
                </p>
              </article>
            ))}
          </div>
        </section>
      )}
      <section className="event-group">
        <h2>
          선별된 주요 이슈 <small>{accepted.length}</small>
        </h2>
        {accepted.length ? (
          accepted.map((item) => (
            <article
              className="event-card event-card--accepted"
              key={item.event_id}
            >
              <div>
                <div className="event-title-row">
                  <StatusPill
                    status={
                      pipelineByEvent.get(item.event_id)?.terminal_status ??
                      item.validation_status
                    }
                  />
                  <span
                    className={`eligibility ${item.signal_enabled ? "eligible" : "disabled"}`}
                  >
                    {item.signal_enabled ? "전망 반영" : "참고 정보"}
                  </span>
                </div>
                <h3>{item.title}</h3>
                <p>
                  {analysisCodeLabel(item.domain)} ·{" "}
                  {analysisCodeLabel(item.event_family)} ·{" "}
                  {analysisCodeLabel(item.event_type)}
                </p>
                <small>
                  {item.start_date} → {item.end_date ?? "진행 중"}
                </small>
                <div className="impact-list">
                  {(item.impacts ?? []).map((impact, index) => (
                    <span key={`${impact.axis}-${index}`}>
                      {analysisCodeLabel(impact.axis)} ·{" "}
                      {analysisCodeLabel(impact.direction)} ·{" "}
                      {analysisCodeLabel(impact.mechanism)}
                    </span>
                  ))}
                </div>
                <p className="rule-explanation">
                  {signalEligibilityLabel(item.signal_enabled)}
                </p>
              </div>
              <button
                aria-label={`${item.title} 이벤트 근거 열기`}
                className="text-button"
                onClick={(event) =>
                  setSelected({
                    id: item.event_id,
                    kind: "event",
                    trigger: event.currentTarget,
                  })
                }
              >
                이벤트 근거 열기
              </button>
            </article>
          ))
        ) : (
          <div className="empty-small">
            검증된 주요 이슈를 찾지 못했습니다.
            {(data.research?.funnel?.provider_failure_count ?? 0) > 0 ||
            (data.research?.funnel?.access_failure_count ?? 0) > 0
              ? " 제공자 시간 초과 또는 문서 검증 실패로 일부 조사 경로가 완료되지 않았습니다."
              : ""}
          </div>
        )}
      </section>
      <section className="event-group">
        <h2>
          미승인 이벤트 후보 <small>{rejected.length}</small>
        </h2>
        {rejected.length ? (
          rejected.map((item) => (
            <article
              className="event-card event-card--candidate"
              key={item.candidate_id}
            >
              <div>
                <div className="event-title-row">
                  <StatusPill
                    status={
                      pipelineByEvent.get(item.candidate_id)?.terminal_status ??
                      item.status
                    }
                  />
                  <span
                    className={`eligibility ${item.signal_enabled ? "eligible" : "disabled"}`}
                  >
                    {item.signal_enabled ? "전망 반영" : "참고 정보"}
                  </span>
                </div>
                <h3>
                  {item.title ?? item.event_type ?? "후보 상세 정보 없음"}
                </h3>
                <p>
                  {analysisCodeLabel(item.domain ?? "미확인 도메인")} ·{" "}
                  {analysisCodeLabel(item.event_family ?? "미확인 이벤트군")} ·{" "}
                  {analysisCodeLabel(item.event_type ?? "미확인 유형")}
                </p>
                <small>
                  원문 날짜: {item.temporal?.start_raw ?? UNKNOWN_VALUE} →{" "}
                  {item.temporal?.end_raw ?? "진행 중"}
                </small>
                <p>대상: {item.target_subject_raw ?? UNKNOWN_VALUE}</p>
                <div className="impact-list">
                  {(item.impacts ?? []).map((impact, index) => (
                    <span key={`${impact.axis}-${index}`}>
                      {analysisCodeLabel(impact.axis)} ·{" "}
                      {analysisCodeLabel(impact.direction)} ·{" "}
                      {analysisCodeLabel(impact.mechanism)}
                    </span>
                  ))}
                </div>
                <div className="validation-failures">
                  {(item.failure_details ?? []).map((failure) => (
                    <div key={failure.code}>
                      <strong>{analysisCodeLabel(failure.code)}</strong>
                      <span>
                        {failureMessage(failure.code, failure.message)}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="rule-explanation">
                  {signalEligibilityLabel(Boolean(item.signal_enabled))}
                </p>
                <p className="retry-line">
                  재시도:{" "}
                  {item.retry?.attempted
                    ? `${analysisStatusLabel(item.retry?.outcome ?? "시도됨")}${item.retry?.candidate_id ? ` · ${item.retry?.candidate_id}` : ""}`
                    : "시도하지 않음"}
                </p>
                {item.evidence?.[0] && (
                  <blockquote>{item.evidence?.[0].quote}</blockquote>
                )}
              </div>
              <button
                aria-label={`${item.title ?? item.candidate_id} 후보 근거 열기`}
                className="text-button"
                onClick={(event) =>
                  setSelected({
                    id: item.candidate_id,
                    kind: "candidate",
                    trigger: event.currentTarget,
                  })
                }
              >
                후보 근거 열기
              </button>
            </article>
          ))
        ) : (
          <div className="empty-small">기록된 미승인 후보가 없습니다.</div>
        )}
      </section>
      {selected && (
        <FocusDialog
          title={selected.kind === "candidate" ? "후보 근거" : "이벤트 근거"}
          onClose={() => setSelected(undefined)}
          returnFocus={selected.trigger}
        >
          {selected.kind === "event" && (
            <>
              {eventEvidence.isLoading && <Loading compact />}
              {eventEvidence.isError && (
                <ErrorCard error={eventEvidence.error} compact />
              )}
              {eventEvidence.data && (
                <>
                  <dl>
                    <div>
                      <dt>이벤트 ID</dt>
                      <dd>{eventEvidence.data.event_id}</dd>
                    </div>
                    <div>
                      <dt>출처</dt>
                      <dd>
                        {eventEvidence.data.source_ids.join(", ") ||
                          UNKNOWN_VALUE}
                      </dd>
                    </div>
                    <div>
                      <dt>개정본</dt>
                      <dd>
                        {eventEvidence.data.source_revision_ids.join(", ") ||
                          UNKNOWN_VALUE}
                      </dd>
                    </div>
                  </dl>
                  {eventEvidence.data.evidence.map((item, index) => (
                    <blockquote key={index}>{item.quote}</blockquote>
                  ))}
                </>
              )}
            </>
          )}
          {selected.kind === "candidate" && (
            <>
              {candidateEvidence.isLoading && <Loading compact />}
              {candidateEvidence.isError && (
                <ErrorCard error={candidateEvidence.error} compact />
              )}
              {candidateEvidence.data && (
                <>
                  <dl>
                    <div>
                      <dt>후보 ID</dt>
                      <dd>{candidateEvidence.data.candidate_id}</dd>
                    </div>
                    <div>
                      <dt>확인 상태</dt>
                      <dd>
                        {analysisStatusLabel(
                          candidateEvidence.data.validation_status,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>재시도</dt>
                      <dd>
                        {candidateEvidence.data.retry?.attempted
                          ? analysisStatusLabel(
                              candidateEvidence.data.retry?.outcome ?? "시도됨",
                            )
                          : "시도하지 않음"}
                      </dd>
                    </div>
                  </dl>
                  <div className="validation-failures">
                    {(candidateEvidence.data.failure_details ?? []).map(
                      (failure) => (
                        <div key={failure.code}>
                          <strong>{analysisCodeLabel(failure.code)}</strong>
                          <span>
                            {failureMessage(failure.code, failure.message)}
                          </span>
                        </div>
                      ),
                    )}
                  </div>
                  {(candidateEvidence.data.evidence ?? []).map(
                    (item, index) => (
                      <blockquote key={index}>{item.quote}</blockquote>
                    ),
                  )}
                  {(candidateEvidence.data.sources ?? []).map((source) => (
                    <article
                      className="source-card"
                      key={source.source_revision_id}
                    >
                      <strong>{source.title || source.source_id}</strong>
                      <span>
                        {source.publisher ?? "발행기관 미확인"} ·{" "}
                        {analysisStatusLabel(source.access_status)} · HTTP{" "}
                        {source.http_status ?? UNKNOWN_VALUE}
                      </span>
                      <a
                        href={source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        원문 출처 열기
                      </a>
                      <code>
                        {source.source_id} · {source.source_revision_id}
                      </code>
                    </article>
                  ))}
                </>
              )}
            </>
          )}
        </FocusDialog>
      )}
    </section>
  );
}
function Policies() {
  const { data, isLoading, isError, error } = useResult();
  const [selected, setSelected] = useState<{
    id: string;
    trigger: HTMLElement;
  }>();
  const detail = useQuery({
    queryKey: ["policy", selected?.id],
    queryFn: () => api.policy(selected!.id),
    enabled: Boolean(selected),
    retry: false,
  });
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  const policies = asRecord(valueOf(data, "policies"));
  const candidates = asRecords(
    policies?.extracted_candidates ?? policies?.candidates,
  );
  const recommendations = asRecords(
    policies?.eligible_recommendations ?? policies?.ranked_options,
  );
  const references = asRecords(policies?.reference_only_materials);
  const stageCounts = asRecord(policies?.stage_counts) ?? {};
  const eligibility = new Map(
    asRecords(policies?.eligibility_results).map((item) => [
      String(item.policy_id),
      item,
    ]),
  );
  return (
    <section className="page">
      <span className="eyebrow">지원 정책</span>
      <h1>지원 정책</h1>
      <p className="muted page-intro">
        점포 정보와 분석 기준일을 바탕으로 이용 가능한 지원 정책을 모았습니다.
      </p>
      <div className="kpis policy-stage-grid" aria-label="정책 처리 단계 요약">
        {[
          ["참고 자료", stageCounts.reference_only_materials],
          ["확인 자료", stageCounts.extracted_candidates],
          ["조건 확인", stageCounts.validated_policies],
          ["접수 종료", stageCounts.closed_policies],
          ["신청 가능", stageCounts.eligible_policies],
          ["우선 추천", stageCounts.ranked_recommendations],
        ].map(([label, value]) => (
          <article className="kpi" key={String(label)}>
            <span>{String(label)}</span>
            <b>{Number(value ?? 0).toLocaleString("ko-KR")}</b>
          </article>
        ))}
      </div>
      <section className="policy-summary" aria-label="정책 추천 결과">
        <h2>추천 정책</h2>
        {recommendations.length ? (
          <ul>
            {recommendations.map((item) => (
              <li key={String(item.policy_id)}>
                {String(item.policy_id)} · {String(item.score ?? "")}
              </li>
            ))}
          </ul>
        ) : (
          <p>현재 조건에서 우선 추천할 정책이 없습니다.</p>
        )}
        {references.length > 0 && (
          <>
            <h2>함께 살펴볼 정책 자료</h2>
            <ul>
              {references.map((item) => (
                <li key={String(item.finding_id)}>
                  {String(item.title)} — {String(item.reason_code)}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <div className="section-heading compact-heading">
        <div>
          <span className="eyebrow">탐색 결과</span>
          <h2>확인한 지원 정책</h2>
        </div>
        <p>관심 있는 정책을 열어 대상 조건과 신청 기간을 확인할 수 있습니다.</p>
      </div>
      <div className="policy-grid">
        {candidates.map((item, index) => {
          const id = String(
            item.policy_candidate_id ?? item.policy_id ?? `policy-${index}`,
          );
          const eligibilityItem = eligibility.get(id);
          return (
            <article className="policy-card" key={`${id}-${index}`}>
              <div>
                <span className="eyebrow">
                  {analysisCodeLabel(item.policy_type ?? "POLICY")}
                </span>
                <h2>{String(item.name ?? "정책명 없음")}</h2>
                <p>{String(item.provider_raw ?? "제공기관 미상")}</p>
              </div>
              <StatusPill
                status={
                  eligibilityItem?.status ??
                  item.validation_status ??
                  "NEEDS_INFORMATION"
                }
              />
              <p>{policyReasonLabel(eligibilityItem?.reason)}</p>
              <dl>
                <div>
                  <dt>한도</dt>
                  <dd>{formatWon(item.limit_krw)}</dd>
                </div>
                <div>
                  <dt>예산 상태</dt>
                  <dd>
                    {analysisStatusLabel(item.budget_status ?? "UNKNOWN")}
                  </dd>
                </div>
                <div>
                  <dt>신청 기간</dt>
                  <dd>
                    {formatDate(item.application_start)} ~{" "}
                    {formatDate(item.application_end)}
                  </dd>
                </div>
              </dl>
              <span className="official">
                <ShieldCheck /> 제공기관 안내 보기
              </span>
              <button
                className="text-button"
                onClick={(event) =>
                  setSelected({ id, trigger: event.currentTarget })
                }
              >
                정책 상세 열기
              </button>
            </article>
          );
        })}
      </div>
      {!candidates.length && (
        <div className="empty-small">조회된 정책 후보가 없습니다.</div>
      )}
      {selected && (
        <FocusDialog
          title="정책 상세"
          onClose={() => setSelected(undefined)}
          returnFocus={selected.trigger}
        >
          {detail.isLoading && <Loading compact />}
          {detail.isError && <ErrorCard error={detail.error} compact />}
          {detail.data && (
            <pre className="json-detail">
              {JSON.stringify(detail.data.policy, null, 2)}
            </pre>
          )}
        </FocusDialog>
      )}
    </section>
  );
}
function Evidence() {
  const { data, isLoading, isError, error } = useResult();
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  const trace = asRecord(valueOf(data, "traceability")) ?? {};
  const versions = asRecord(valueOf(data, "versions")) ?? {};
  const traceLabels: Record<string, string> = {
    source_ids: "사용 출처",
    source_revision_ids: "출처 개정본",
    official_snapshot_ids: "공식 데이터 묶음",
    official_observation_ids: "공식 관측값",
    event_ids: "주요 이슈",
    signal_ids: "전망 반영 신호",
    policy_ids: "지원 정책",
    model_run_ids: "예측 모델 실행",
    scenario_ids: "재무 시나리오",
    calculation_result_ids: "계산 결과",
  };
  const versionLabels: Record<string, string> = {
    input_schema_version: "입력 형식",
    analysis_result_schema_version: "결과 형식",
    official_observation_schema_version: "공식 관측값 형식",
    event_registry_version: "이슈 분류 체계",
    normalization_rules_version: "데이터 정규화 규칙",
    source_policy_version: "출처 정책",
    coefficient_version: "계수 버전",
    official_feature_version: "공식 데이터 변환",
    forecast_model_versions: "예측 모델",
    policy_rule_version: "정책 판정 규칙",
    financial_calculation_version: "재무 계산",
    prompt_versions: "AI 분석 설정",
    provider_models: "AI 모델",
    git_commit: "서비스 빌드",
  };
  const auditValue = (value: unknown) => {
    if (!Array.isArray(value)) {
      return <b>{String(value ?? UNKNOWN_VALUE)}</b>;
    }
    if (!value.length) return <b>{UNKNOWN_VALUE}</b>;
    return (
      <details className="trace-details">
        <summary>{value.length.toLocaleString("ko-KR")}건 · 목록 보기</summary>
        <div className="trace-token-list">
          {value.map((item, index) => (
            <code key={`${String(item)}-${index}`}>{String(item)}</code>
          ))}
        </div>
      </details>
    );
  };
  return (
    <section className="page">
      <span className="eyebrow">데이터 상세</span>
      <h1>데이터 상세</h1>
      <p className="muted">
        이번 분석에 사용한 데이터와 결과 정보를 확인합니다.
      </p>
      <div className="audit-grid">
        <article className="card">
          <h2>결과 식별자</h2>
          <dl>
            <div>
              <dt>결과 ID</dt>
              <dd>{String(valueOf(data, "result_id") ?? UNKNOWN_VALUE)}</dd>
            </div>
            <div>
              <dt>결과 확인 코드</dt>
              <dd className="mono">
                {String(valueOf(data, "deterministic_hash") ?? UNKNOWN_VALUE)}
              </dd>
            </div>
            <div>
              <dt>완료 시각</dt>
              <dd>{formatDate(valueOf(data, "completed_at"))}</dd>
            </div>
          </dl>
        </article>
        <article className="card">
          <h2>사용 데이터</h2>
          {Object.entries(trace).map(([key, value]) => (
            <div className="trace" key={key}>
              <span>{traceLabels[key] ?? key.replaceAll("_", " ")}</span>
              {auditValue(value)}
            </div>
          ))}
        </article>
        <article className="card">
          <h2>분석 버전</h2>
          {Object.entries(versions).map(([key, value]) => (
            <div className="trace" key={key}>
              <span>{versionLabels[key] ?? key.replaceAll("_", " ")}</span>
              <b>
                {typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value ?? UNKNOWN_VALUE)}
              </b>
            </div>
          ))}
        </article>
      </div>
    </section>
  );
}
function WhatIf() {
  const { runId, data, isLoading, isError, error } = useResult();
  const [form, setForm] = useState({
    scenarioName: "매출 감소 가정",
    revenuePercent: "-10",
    variablePercent: "0",
    fixedPercent: "0",
    interestPercentagePoints: "0",
  });
  const mutation = useMutation({
    mutationFn: () => api.whatIf(runId, createWhatIfRequest(form)),
  });
  if (isLoading) return <Loading />;
  if (isError) return <ErrorCard error={error} />;
  const baseRows = asRecords(scenarioOf(data)?.monthly_cash_flows);
  const derivedRows = asRecords(
    asRecord(mutation.data?.scenario)?.monthly_cash_flows,
  );
  return (
    <section className="page">
      <span className="eyebrow">사용자 정의 가정</span>
      <h1>가정 변경 비교</h1>
      <p className="muted page-intro">
        매출과 비용 가정을 바꾸어 기준 결과와 비교해 보세요. 기존 분석은 그대로
        유지됩니다.
      </p>
      <div className="whatif">
        <article className="card">
          <h2>사용자 가정</h2>
          <Field
            id="scenarioName"
            label="시나리오 이름"
            value={form.scenarioName}
            change={(value) => setForm({ ...form, scenarioName: value })}
          />
          <div className="form-grid">
            <Field
              id="revenuePercent"
              label="매출 변화율 (%)"
              type="number"
              value={form.revenuePercent}
              change={(value) => setForm({ ...form, revenuePercent: value })}
            />
            <Field
              id="variablePercent"
              label="변동비 변화율 (%)"
              type="number"
              value={form.variablePercent}
              change={(value) => setForm({ ...form, variablePercent: value })}
            />
            <Field
              id="fixedPercent"
              label="고정비 변화율 (%)"
              type="number"
              value={form.fixedPercent}
              change={(value) => setForm({ ...form, fixedPercent: value })}
            />
            <Field
              id="interestPercentagePoints"
              label="이자율 변화 (%p)"
              type="number"
              step="0.1"
              value={form.interestPercentagePoints}
              change={(value) =>
                setForm({ ...form, interestPercentagePoints: value })
              }
            />
          </div>
          <button
            className="primary"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "계산 중" : "변경 결과 계산"}
          </button>
          {mutation.error && (
            <Notice kind="danger" role="alert">
              {mutation.error instanceof Error
                ? mutation.error.message
                : "가정 변경 계산에 실패했습니다."}
            </Notice>
          )}
        </article>
        <article className="card">
          <h2>버전 비교</h2>
          <p>
            기준 버전 {String(valueOf(data, "result_version") ?? UNKNOWN_VALUE)}{" "}
            → 파생 버전 {mutation.data?.result_version ?? UNKNOWN_VALUE}
          </p>
          <p className="muted">
            모든 비교값은 가정 변경 응답의 파생 시나리오에서 가져옵니다.
          </p>
        </article>
      </div>
      {mutation.data && (
        <div className="table-wrap">
          <table>
            <caption>기준 결과와 파생 결과 기말 현금 비교</caption>
            <thead>
              <tr>
                <th>월</th>
                <th>기준 기말 현금</th>
                <th>파생 기말 현금</th>
                <th>차이</th>
              </tr>
            </thead>
            <tbody>
              {derivedRows.map((row, index) => {
                const base = Number(baseRows[index]?.ending_cash_krw ?? 0);
                const derived = Number(row.ending_cash_krw ?? 0);
                return (
                  <tr key={String(row.month_str ?? index)}>
                    <td>{String(row.month_str ?? index + 1)}</td>
                    <td>{formatWon(baseRows[index]?.ending_cash_krw)}</td>
                    <td>{formatWon(row.ending_cash_krw)}</td>
                    <td>{formatWon(derived - base)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
function Settings({
  theme,
  setTheme,
}: {
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
}) {
  const navigate = useNavigate();
  return (
    <section className="page">
      <span className="eyebrow">설정</span>
      <h1>설정 및 안내</h1>
      <article className="card settings">
        <h2>화면 테마</h2>
        <ThemeButtons value={theme} onChange={setTheme} />
        <p>
          테마 선택만 이 기기에 저장합니다. 시스템 설정은 운영체제 색상 변경을
          반영합니다.
        </p>
      </article>
      <article className="card settings">
        <h2>데이터 연결</h2>
        <p>경제 지표와 분석 결과의 연결 상태를 확인합니다.</p>
        <BackendStatus />
      </article>
      <article className="card settings">
        <h2>최근 분석</h2>
        <p>이 기기에는 최근 분석 ID만 저장되어 빠르게 이어볼 수 있습니다.</p>
        <button
          className="secondary"
          onClick={() => {
            localStorage.removeItem("kb-last-run");
            navigate("/dashboard");
          }}
        >
          최근 분석 기록 지우기
        </button>
      </article>
      <article className="card settings">
        <h2>오픈소스 고지</h2>
        <p>
          서비스에 사용된 오픈소스 라이브러리와 라이선스 정보를 확인할 수
          있습니다.
        </p>
        <a className="text-link" href="/THIRD_PARTY_NOTICES.md" target="_blank">
          오픈소스 고지 보기
        </a>
      </article>
    </section>
  );
}
function Loading({ compact = false }: { compact?: boolean }) {
  const content = (
    <div className="loading" role="status" aria-live="polite">
      <LoaderCircle className="spin" /> 분석 데이터를 불러오는 중
    </div>
  );
  return compact ? content : <section className="page">{content}</section>;
}
function ErrorCard({
  error,
  compact = false,
}: {
  error: unknown;
  compact?: boolean;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const content = (
    <div className="error-card" role="alert">
      <AlertTriangle />
      <h1>데이터를 불러오지 못했습니다</h1>
      <p>{apiError?.message ?? "요청 처리에 실패했습니다."}</p>
      {apiError?.correlationId && (
        <code>상관관계 ID: {apiError.correlationId}</code>
      )}
      <button className="secondary" onClick={() => window.location.reload()}>
        <RefreshCw /> 다시 시도
      </button>
    </div>
  );
  return compact ? content : <section className="page">{content}</section>;
}
function NotFound() {
  return (
    <section className="page">
      <div className="error-card">
        <AlertTriangle />
        <h1>페이지를 찾을 수 없습니다</h1>
        <p>주소를 확인하거나 대시보드로 돌아가 주세요.</p>
        <NavLink className="primary" to="/dashboard">
          대시보드로 이동
        </NavLink>
      </div>
    </section>
  );
}
export default function App() {
  const { preference, setPreference } = useThemePreference();
  return (
    <Shell theme={preference} setTheme={setPreference}>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/analyses/new" element={<Wizard />} />
        <Route path="/analyses/open" element={<OpenAnalysis />} />
        <Route path="/analyses/:runId/progress" element={<Progress />} />
        <Route path="/analyses/:runId/overview" element={<Overview />} />
        <Route path="/analyses/:runId/forecast" element={<Forecast />} />
        <Route
          path="/analyses/:runId/official-data"
          element={<OfficialDataImpact />}
        />
        <Route path="/analyses/:runId/events" element={<Events />} />
        <Route path="/analyses/:runId/policies" element={<Policies />} />
        <Route path="/analyses/:runId/evidence" element={<Evidence />} />
        <Route path="/analyses/:runId/what-if" element={<WhatIf />} />
        <Route
          path="/settings"
          element={<Settings theme={preference} setTheme={setPreference} />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Shell>
  );
}
