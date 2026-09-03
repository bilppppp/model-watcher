"""Harbor Hub official CLI / JSON data reader for Terminal-Bench and Agent evals."""
import json
import logging
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from model_watcher.sources.base import DataSource
from model_watcher.types import BenchmarkEvidence, ModelMetadata, Role

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


class HarborSource(DataSource):
    name: str = "Harbor Hub"
    priority: int = 0  # P0

    # Known curated official leaderboards discovered via Harbor Hub
    DEFAULT_LEADERBOARD_IDS = [
        "f58e955f-4db5-48a0-87ec-1c324a4a9414",  # Terminal-Bench 2.0
        "9f966760-00f1-424e-90f5-c964fb6f6091",  # Terminal-Bench 4.0
        "60330f75-0dd8-47ea-bd1d-e2ea28945731",  # Terminal-Bench 2.1
    ]

    def __init__(self):
        self._cached_boards: Dict[str, Dict[str, Any]] = {}
        self._available: Optional[bool] = None

    def _is_available(self) -> bool:
        if self._available is not None:
            return self._available
        # Check if uv or harbor is in PATH
        self._available = bool(shutil.which("uv") or shutil.which("harbor"))
        return self._available

    def _fetch_board_json(self, board_id: str) -> Optional[Dict[str, Any]]:
        if board_id in self._cached_boards:
            return self._cached_boards[board_id]

        if not self._is_available():
            return None

        cmd = ["uv", "run", "--with", "harbor", "harbor", "hub", "leaderboard", "show", board_id, "--json"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if res.returncode == 0 and res.stdout.strip().startswith("{"):
                data = json.loads(res.stdout)
                self._cached_boards[board_id] = data
                return data
        except Exception as e:
            logger.warning(f"Failed to fetch Harbor board {board_id}: {e}")

        return None

    def discover_models(self) -> List[ModelMetadata]:
        discovered = {}
        for board_id in self.DEFAULT_LEADERBOARD_IDS:
            data = self._fetch_board_json(board_id)
            if not data:
                continue
            rows = data.get("rows", [])
            for r in rows:
                meta = r.get("metadata", {})
                names = meta.get("model_names", [])
                display = meta.get("model_display") or (names[0] if names else "unknown")
                org = meta.get("model_org", "Unknown")
                date = meta.get("date")
                acc = (r.get("metrics") or {}).get("accuracy")

                for n in names:
                    canon = _normalize_name(n)
                    if canon and canon not in discovered:
                        discovered[canon] = ModelMetadata(
                            canonical_id=n,
                            display_name=display,
                            provider=org,
                            release_date=date,
                            headline_indices={"terminal_bench_accuracy": round(acc, 2) if acc else None},
                            first_seen=date or "",
                            raw_source=self.name,
                        )
        return list(discovered.values())

    def _find_row_for_model(self, model_name: str, board_id: str) -> Optional[Dict[str, Any]]:
        data = self._fetch_board_json(board_id)
        if not data:
            return None

        norm_target = _normalize_name(model_name)
        rows = data.get("rows", [])
        best_row = None
        best_acc = -1.0

        for r in rows:
            meta = r.get("metadata", {})
            names = meta.get("model_names", [])
            disp = meta.get("model_display", "")
            combined = f"{' '.join(names)} {disp}"
            norm_combined = _normalize_name(combined)

            if norm_target in norm_combined or any(norm_target in _normalize_name(n) for n in names):
                acc = float((r.get("metrics") or {}).get("accuracy") or 0.0)
                if acc > best_acc:
                    best_acc = acc
                    best_row = r
        return best_row

    def get_evidence(
        self,
        challenger: str,
        incumbent: str,
        role: Role,
    ) -> Optional[BenchmarkEvidence]:
        # Terminal-Bench on Harbor Hub is Agent / terminal benchmark
        if role != Role.AGENT:
            return None

        for board_id in self.DEFAULT_LEADERBOARD_IDS:
            c_row = self._find_row_for_model(challenger, board_id)
            if not c_row:
                continue

            i_row = self._find_row_for_model(incumbent, board_id)
            c_meta = c_row.get("metadata", {})
            c_acc = (c_row.get("metrics") or {}).get("accuracy")
            i_acc = (i_row.get("metrics") or {}).get("accuracy") if i_row else None

            board_title = (self._cached_boards.get(board_id, {}).get("leaderboard") or {}).get("title", "Terminal-Bench")
            c_agent_info = c_meta.get("agent_display", {})
            c_agent_label = c_agent_info.get("label") if isinstance(c_agent_info, dict) else str(c_agent_info)

            uncertainty = ""
            if i_row:
                i_agent_info = i_row.get("metadata", {}).get("agent_display", {})
                i_agent_label = i_agent_info.get("label") if isinstance(i_agent_info, dict) else str(i_agent_info)
                if c_agent_label != i_agent_label:
                    uncertainty = f"Harness difference: {c_agent_label} vs {i_agent_label}"

            return BenchmarkEvidence(
                source=self.name,
                benchmark=board_title,
                version="v2",
                score_challenger=round(c_acc, 2) if c_acc is not None else None,
                score_incumbent=round(i_acc, 2) if i_acc is not None else None,
                display_metric="%",
                harness=c_agent_label or "Harbor CLI agent",
                url=f"https://hub.harborframework.com",
                confidence=0.85 if not uncertainty else 0.75,
                known_uncertainty=uncertainty or "Harbor Hub curated benchmark run",
            )

        return None
