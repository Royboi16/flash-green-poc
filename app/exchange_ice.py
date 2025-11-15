from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from app.config import settings
from app.exchange import Fill


class ICEPowerExchange:
    """Thin REST wrapper for ICE order placement."""

    TERMINAL_STATES = {"FILLED", "REJECTED"}

    def __init__(self) -> None:
        self.base_url = settings.ice_api_url
        self.api_key = settings.ice_api_key
        self.api_secret = settings.ice_api_secret
        self.symbol = settings.ice_symbol
        if not all([self.base_url, self.api_key, self.api_secret, self.symbol]):
            raise RuntimeError("Missing ICE live-trading config")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-KEY": self.api_key,
                "X-API-SECRET": self.api_secret,
                "Content-Type": "application/json",
            }
        )

    def advance(self) -> None:  # pragma: no cover - API driven
        return None

    def quote(self) -> float:
        resp = self._request("get", f"{self.base_url}/marketdata/{self.symbol}/price")
        return float(resp.json()["last_price"])

    def buy(self, qty_mwh: float, max_price: float) -> Fill:
        payload = {
            "symbol": self.symbol,
            "side": "BUY",
            "quantity": qty_mwh,
            "price": max_price,
            "type": "LIMIT",
        }
        resp = self._request("post", f"{self.base_url}/orders", json=payload)
        order_id = resp.json()["id"]
        report = self._wait_for_completion(order_id, qty_mwh)
        return Fill(
            qty_mwh=report["filled_qty"],
            price=report["avg_price"],
            order_id=order_id,
            status=report["status"],
            executions=report["executions"],
            error=report.get("error") or report.get("cancel_reason"),
        )

    def sell(self, qty_mwh: float) -> Fill:
        payload = {
            "symbol": self.symbol,
            "side": "SELL",
            "quantity": qty_mwh,
            "type": "MARKET",
        }
        resp = self._request("post", f"{self.base_url}/orders", json=payload)
        order_id = resp.json()["id"]
        report = self._wait_for_completion(order_id, qty_mwh)
        return Fill(
            qty_mwh=report["filled_qty"],
            price=report["avg_price"],
            order_id=order_id,
            status=report["status"],
            executions=report["executions"],
            error=report.get("error") or report.get("cancel_reason"),
        )

    def _wait_for_completion(self, order_id: str, requested_qty: float) -> Dict[str, Any]:
        deadline = time.time() + settings.order_timeout_secs
        last_report: Dict[str, Any] | None = None

        while time.time() < deadline:
            last_report = self._fetch_order(order_id, requested_qty)
            if last_report["status"] in self.TERMINAL_STATES:
                return last_report
            time.sleep(settings.order_poll_interval)

        # timed out – cancel and fetch final state
        self.cancel_order(order_id)
        return self._fetch_order(order_id, requested_qty)

    def _fetch_order(self, order_id: str, requested_qty: float | None = None) -> Dict[str, Any]:
        resp = self._request("get", f"{self.base_url}/orders/{order_id}")
        payload = resp.json()
        return self._normalize_order(payload, requested_qty)

    def cancel_order(self, order_id: str) -> None:
        self._request("delete", f"{self.base_url}/orders/{order_id}")

    # ─── helpers ──────────────────────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(self._format_error(method, url, resp))
        return resp

    def _format_error(self, method: str, url: str, resp: requests.Response) -> str:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        detail = payload.get("error") or payload.get("message") or resp.text
        return f"ICE API {method.upper()} {url} failed: {detail.strip()}"

    def _normalize_order(
        self, payload: Dict[str, Any], requested_qty: float | None
    ) -> Dict[str, Any]:
        qty_requested = requested_qty or float(
            payload.get("quantity")
            or payload.get("orig_qty")
            or payload.get("size")
            or 0.0
        )
        filled = float(payload.get("filled_qty") or payload.get("executed_qty") or 0.0)
        avg_price = float(payload.get("avg_price") or payload.get("price") or 0.0)
        raw_status = (payload.get("status") or "").upper()
        status = self._normalize_status(raw_status, filled, qty_requested)
        executions = self._normalize_executions(payload.get("executions") or payload.get("fills") or [])
        cancel_reason = payload.get("cancel_reason") or payload.get("reject_reason") or payload.get("reason")
        error_message = payload.get("error") or payload.get("message")
        is_active = status not in self.TERMINAL_STATES and raw_status not in {
            "CANCELLED",
            "CANCELED",
            "REJECTED",
            "EXPIRED",
        }
        return {
            "id": payload.get("id"),
            "status": status,
            "filled_qty": filled,
            "avg_price": avg_price,
            "executions": executions,
            "cancel_reason": cancel_reason,
            "error": error_message,
            "is_active": is_active,
            "raw_status": raw_status,
            "qty_requested": qty_requested,
        }

    def _normalize_status(self, raw_status: str, filled: float, requested: float) -> str:
        if raw_status in {"FILLED", "COMPLETED"}:
            return "FILLED"
        if raw_status in {"PARTIALLY_FILLED", "PARTIAL"}:
            return "PARTIALLY_FILLED"
        if raw_status in {"NEW", "PENDING_NEW", "OPEN", "WORKING"}:
            return "PARTIALLY_FILLED" if filled > 0 else "NEW"
        if raw_status in {"CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "DONE_FOR_DAY"}:
            return "FILLED" if filled >= requested > 0 else "REJECTED"
        return "PARTIALLY_FILLED" if 0 < filled < requested else "NEW"

    def _normalize_executions(self, executions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for exec_report in executions:
            normalized.append(
                {
                    "qty": float(
                        exec_report.get("qty")
                        or exec_report.get("quantity")
                        or exec_report.get("size")
                        or 0.0
                    ),
                    "price": float(exec_report.get("price") or 0.0),
                    "timestamp": exec_report.get("timestamp")
                    or exec_report.get("ts")
                    or exec_report.get("time"),
                }
            )
        return normalized

