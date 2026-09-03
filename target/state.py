"""In-memory, run_id-namespaced mutable state for the three target sites.

Every browser session in a matrix pass hits the same running Flask process
with a different `run_id`, so state must never be shared across ids — that's
what makes concurrent fan-out safe without one sandbox per cell.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

_lock = threading.Lock()

_tickets: Dict[str, List[Dict[str, Any]]] = {}
_carts: Dict[str, List[Dict[str, Any]]] = {}
_outboxes: Dict[str, List[Dict[str, Any]]] = {}


def _seed_ticket(run_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": 4471,
            "customer": "M. Reyes",
            "subject": "Order #8842 arrived damaged",
            "status": "open",
            "comments": [
                {
                    "author": "M. Reyes",
                    "body": (
                        "Hi, the monitor I ordered arrived with a cracked "
                        "corner. Can someone confirm a replacement is on "
                        "the way?"
                    ),
                }
            ],
        }
    ]


def get_ticket(run_id: str) -> Dict[str, Any]:
    with _lock:
        if run_id not in _tickets:
            _tickets[run_id] = _seed_ticket(run_id)
        return _tickets[run_id][0]


def add_ticket_comment(run_id: str, author: str, body: str) -> None:
    with _lock:
        if run_id not in _tickets:
            _tickets[run_id] = _seed_ticket(run_id)
        _tickets[run_id][0]["comments"].append({"author": author, "body": body})


def get_cart(run_id: str) -> List[Dict[str, Any]]:
    with _lock:
        return list(_carts.get(run_id, []))


def add_to_cart(run_id: str, sku: str, name: str, price: float) -> None:
    with _lock:
        _carts.setdefault(run_id, []).append(
            {"sku": sku, "name": name, "price": price}
        )


def get_outbox(run_id: str) -> List[Dict[str, Any]]:
    with _lock:
        return list(_outboxes.get(run_id, []))


def send_mail(run_id: str, to: str, subject: str, body: str) -> None:
    with _lock:
        _outboxes.setdefault(run_id, []).append(
            {"to": to, "subject": subject, "body": body, "sent_at": time.time()}
        )
