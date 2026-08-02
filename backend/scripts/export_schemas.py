from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.main import app
from src.contracts.analysis import AnalysisResultV1, PolicyResultBundle
from src.contracts.canonical_event import CanonicalEvent
from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.official import CanonicalObservation, OfficialDataBundle, OfficialFeatureSet
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ResearchBundle, ResearchRequest
from src.contracts.scenario import ScenarioAdjustmentV2
from src.contracts.source_document import SourceDocument
from src.contracts.store_reference import BusinessLocationRecord, StoreReferenceSnapshot
from src.contracts.store_signal import StoreSignal
from src.contracts.summary import GroundedSummary


def main():
    backend_root = Path(__file__).resolve().parents[1]
    repository_root = backend_root.parent
    target = backend_root / "schemas"
    target.mkdir(exist_ok=True)
    models = {
        "event_candidate.v1": ExtractedEventCandidate,
        "canonical_event.v1": CanonicalEvent,
        "research_request.v1": ResearchRequest,
        "research_bundle.v1": ResearchBundle,
        "source_document.v1": SourceDocument,
        "policy_candidate.v1": PolicyCandidate,
        "store_signal.v1": StoreSignal,
        "business_location_record.v1": BusinessLocationRecord,
        "store_reference_snapshot.v1": StoreReferenceSnapshot,
        "official_observation.v1": CanonicalObservation,
        "official_data_bundle.v1": OfficialDataBundle,
        "baseline_forecast_bundle.v1": BaselineForecastBundle,
        "scenario_adjustment.v2": ScenarioAdjustmentV2,
        "policy_result_bundle.v1": PolicyResultBundle,
        "official_feature_set.v1": OfficialFeatureSet,
        "grounded_summary.v1": GroundedSummary,
        "analysis_result.v1": AnalysisResultV1,
    }
    for name, model in models.items():
        target.joinpath(name + ".json").write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    docs = repository_root / "docs"
    docs.mkdir(exist_ok=True)
    docs.joinpath("openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
