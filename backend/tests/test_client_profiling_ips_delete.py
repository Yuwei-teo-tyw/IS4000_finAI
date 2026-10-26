"""DELETE /ips/{client_id}/{version}: removes a version, promotes the newest remaining one, 404/403 edge cases."""
from fastapi.testclient import TestClient

from app.app import app

URL = "/agents/client-profiling"


def _save(c, cid, body):
    r = c.post(f"{URL}/ips/{cid}", json={"parts": [{"part": 1, "title": "Demographics", "body": body}]})
    assert r.status_code == 200, r.text
    return r.json()["ips"]["version"]


def test_delete_version_and_promote():
    c = TestClient(app)
    book = c.get(f"{URL}/book").json()
    cid = next(x["id"] for x in book["clients"])
    v1 = _save(c, cid, "one")
    v2 = _save(c, cid, "two")
    assert c.delete(f"{URL}/ips/{cid}/{v2}").json() == {"deleted": True, "version": v2}
    versions = c.get(f"{URL}/ips/{cid}").json()["versions"]
    assert all(v["version"] != v2 for v in versions)
    assert next(v for v in versions if v["version"] == v1)["status"] == "Active"


def test_delete_missing_version_404():
    c = TestClient(app)
    cid = next(x["id"] for x in c.get(f"{URL}/book").json()["clients"])
    assert c.delete(f"{URL}/ips/{cid}/9999").status_code == 404


def test_delete_not_in_book_403():
    assert TestClient(app).delete(f"{URL}/ips/nobody/1").status_code == 403
