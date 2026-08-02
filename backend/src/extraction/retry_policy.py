from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_search_retries: int = 1
    max_extraction_retries: int = 1
    max_model_promotions: int = 1

    def can_retry_search(self, attempts: int) -> bool: return attempts <= self.max_search_retries
    def can_retry_extraction(self, attempts: int) -> bool: return attempts <= self.max_extraction_retries
    def fingerprint(self, input_hash: str, prompt_version: str, reasoning: str) -> str: return f"{input_hash}:{prompt_version}:{reasoning}"
