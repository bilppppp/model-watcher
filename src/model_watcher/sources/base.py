"""Base class and common helpers for benchmark data sources."""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import urllib.request
import json
import logging

from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

logger = logging.getLogger(__name__)


def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> bytes:
    req_headers = {
        "User-Agent": "ModelWatcher/1.0 (Mozilla/5.0 compatible)",
        "Accept": "*/*",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> dict:
    raw = http_get(url, headers=headers, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


class DataSource(ABC):
    name: str = "base"
    priority: int = 0  # 0 = P0, 1 = P1, etc.

    @abstractmethod
    def discover_models(self) -> List[ModelMetadata]:
        """Discovers available models and their metadata."""
        pass

    @abstractmethod
    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        """Collects comparative benchmark evidence between challenger and incumbent for a given role."""
        pass
