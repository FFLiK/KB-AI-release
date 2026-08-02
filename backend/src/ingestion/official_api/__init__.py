# official_api package initialization
from src.ingestion.official_api.base_adapter import BaseOfficialApiAdapter, CanonicalObservation
from src.ingestion.official_api.ecos import ECOSAdapter
from src.ingestion.official_api.kosis import KOSISAdapter
from src.ingestion.official_api.customs import CustomsAdapter
from src.ingestion.official_api.public_data import PublicDataStoreAdapter
from src.ingestion.official_api.map_api import MapApiAdapter

__all__ = [
    "BaseOfficialApiAdapter",
    "CanonicalObservation",
    "ECOSAdapter",
    "KOSISAdapter",
    "CustomsAdapter",
    "PublicDataStoreAdapter",
    "MapApiAdapter",
]
