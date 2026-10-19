import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.endpoints.review_pack import router
from app.reports.render import render_review_pack

ALLOC = [
    {"asset_class": "Cash", "saa": 15, "old_taa": 14, "new_taa": 12, "band": 5},
    {"asset_class": "Fixed income", "saa": 35, "old_taa": 33, "new_taa": 40, "band": 5},
    {"asset_class": "Equities", "saa": 30, "old_taa": 33, "new_taa": 28, "band": 5},
    {"asset_class": "Gold", "saa": 20, "old_taa": 20, "new_taa": 20, "band": 5},
]


def sec(n, text="Hello.", complete=True, **kw):
    return {"n": n, "title": f"S{n}", "owner_label": "Relationship Manager (Isabel)", "complete": complete, "text": text, **kw}


def payload(sections, **kw):
    return {"doc": {"title": "Quarterly Review Pack", "client_name": "Mr Tan", "version": "Draft", "date": "1 Jan 2026"},
            "sections": sections, "allocation": ALLOC, **kw}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rm_text_appears_in_preview(client):
    r = client.post("/review-pack/render", json=payload([sec(1, "- Wants to retire at 60 [NOTE-1]")]))
    assert r.status_code == 200
    assert "Wants to retire at 60" in r.text and 'class="cite">NOTE-1<' in r.text


def test_chart_placeholder_renders_side_by_side_with_text():
    html = render_review_pack(payload([sec(1, "Profile.", chart="saa"), sec(4, "Shift.", chart="taa")]))
    assert html.count('class="with-chart"') == 2
    assert "<svg" in html and "Old vs new tactical allocation" in html


def test_script_in_text_is_escaped(client):
    r = client.post("/review-pack/render", json=payload([sec(1, "<script>alert(1)</script>")]))
    assert "<script>alert" not in r.text and "&lt;script&gt;" in r.text


def test_template_syntax_in_text_is_not_evaluated(client):
    r = client.post("/review-pack/render", json=payload([sec(1, "{{ 7*7 }} {% if 1 %}x{% endif %}")]))
    assert "49" not in r.text and "{{ 7*7 }}" in r.text


def test_unknown_chart_placeholder_fails_loudly(client):
    r = client.post("/review-pack/render", json=payload([sec(1, chart="nope")]))
    assert r.status_code == 422


def test_pending_section_shows_placeholder_and_draft_banner():
    html = render_review_pack(payload([sec(2, "", complete=False)]))
    assert "To be completed by" in html and "Draft, incomplete" in html


def test_bad_signature_data_url_is_dropped():
    sigs = {"rm": {"data_url": "javascript:alert(1)", "signed_at": "now"}}
    html = render_review_pack(payload([sec(6, kind="signoff")], signatures=sigs))
    assert "javascript:" not in html and "Not yet signed" in html
