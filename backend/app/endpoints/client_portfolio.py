"""IS-97 HTTP interface: GET /agents/client-portfolio/{client_id}. Read-only; scoped to the RM's book (403 otherwise);
portfolio DB down -> 503 {available: false, message} with no holdings."""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.agents.client_portfolio import service
from app.agents.client_profiling.store import DEFAULT_RM, StoreUnavailableError, get_default_store

PREFIX = "/agents/client-portfolio"
router = APIRouter(prefix=PREFIX, tags=["client-portfolio"])


@router.get("/{client_id}")
def get_portfolio(client_id: str, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)):
    try:
        in_book = client_id in get_default_store().book_ids()  # single-RM book, read server-side (x_rm_id kept for parity)
    except StoreUnavailableError:
        return JSONResponse({"available": False, "message": service.UNAVAILABLE_MSG, "holdings": []}, status_code=503)
    res = service.get_client_portfolio(client_id)
    if not res.get("available"):
        return JSONResponse(res, status_code=503)
    # Out-of-book clients: 403 if they have holdings (no data leaks); a clean "no holdings" if they have none, so the
    # frontend can simply hide the section for any client without a portfolio.
    if not in_book and res.get("status") != "no_holdings":
        raise HTTPException(status_code=403, detail="Client is not in your book")
    return res
