"""
Proposal storage for GET /portfolio/{request_id}.

In-memory and bounded (oldest proposals evicted first): enough for the
prototype, and lost on restart. A production version would persist to the
same Postgres instance the main app uses, with access control and an audit
trail; keep that behind this interface so routes don't change.
"""
import threading
from collections import OrderedDict
from typing import Optional

from app.agents.portfolio_agent.schemas.response import PortfolioResponse


class ProposalStore:
    def __init__(self, max_items: int = 500):
        self._items: "OrderedDict[str, PortfolioResponse]" = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()

    def exists(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._items

    def save(self, response: PortfolioResponse) -> None:
        with self._lock:
            self._items[response.request_id] = response
            self._items.move_to_end(response.request_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def get(self, request_id: str) -> Optional[PortfolioResponse]:
        with self._lock:
            return self._items.get(request_id)
