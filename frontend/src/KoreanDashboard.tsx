import { ArrowRight, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
export default function KoreanDashboard() {
  const navigate = useNavigate();
  return (
    <section className="hero">
      <div>
        <span className="eyebrow">
          <Sparkles /> 증거 기반 소상공인 분석
        </span>
        <h1>
          사업의 다음 달을
          <br />
          <em>근거와 함께</em> 살펴보세요.
        </h1>
        <p>
          매출·비용·현금흐름에 시장 지표와 주요 이슈를 더해, 사업의 흐름과 다음
          선택지를 한눈에 정리합니다.
        </p>
        <div className="actions">
          <button className="primary" onClick={() => navigate("/analyses/new")}>
            새 분석 시작 <ArrowRight />
          </button>
          <button
            className="secondary"
            aria-label={"\uC0D8\uD50C \uCE74\uD398 \uBD88\uB7EC\uC624\uAE30"}
            onClick={() => navigate("/analyses/new?sample=1")}
          >
            예시로 둘러보기
          </button>
        </div>
      </div>
      <div className="hero-card">
        <span className="eyebrow">분석 과정</span>
        <ol>
          <li>
            <b>01</b>
            <span>
              점포 데이터 입력<small>매출, 비용, 대출 및 현금</small>
            </span>
          </li>
          <li>
            <b>02</b>
            <span>
              시장 흐름 반영<small>공식 지표와 주요 사업 이슈</small>
            </span>
          </li>
          <li>
            <b>03</b>
            <span>
              시나리오 검토<small>기준·저영향·고영향 시나리오</small>
            </span>
          </li>
        </ol>
      </div>
      <div className="hero-proof" aria-label="서비스 주요 특징">
        <span>공식 데이터 연계</span>
        <span>월별 현금흐름 비교</span>
        <span>맞춤형 지원 정책 탐색</span>
      </div>
    </section>
  );
}
