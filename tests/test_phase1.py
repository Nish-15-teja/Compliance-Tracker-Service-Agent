import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import RegulationRawPage, Regulation
from tests.conftest import TestingSessionLocal

def create_sample_pdf(filepath: str):
    try:
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(filepath)
        c.drawString(100, 750, "Page 1: Article 1 General Provisions and scope requirements.")
        c.showPage()
        c.drawString(100, 750, "Page 2: Article 2 Mandatory security controls and data protection.")
        c.showPage()
        c.drawString(100, 750, "Page 3: Article 3 Incident notification within 72 hours.")
        c.showPage()
        c.save()
    except Exception:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Page 1: Article 1 General Provisions and scope requirements.\n---PAGE---\nPage 2: Article 2 Mandatory security controls and data protection.\n---PAGE---\nPage 3: Article 3 Incident notification within 72 hours.")

def test_phase1_document_ingestion():
    client = TestClient(app)
    test_pdf_path = "test_sample_3pages.pdf"
    create_sample_pdf(test_pdf_path)

    with open(test_pdf_path, "rb") as pdf_file:
        response = client.post(
            "/regulations/upload",
            data={"title": "EU GDPR Regulation", "version_label": "v1.0"},
            files={"file": ("sample.pdf", pdf_file, "application/pdf")}
        )

    if os.path.exists(test_pdf_path):
        os.remove(test_pdf_path)

    assert response.status_code == 201
    data = response.json()
    assert data["regulation_id"] is not None
    assert data["title"] == "EU GDPR Regulation"
    assert data["version_label"] == "v1.0"
    assert data["page_count"] == 3

    # Verify database contents directly
    db = TestingSessionLocal()
    regulation = db.query(Regulation).filter(Regulation.id == data["regulation_id"]).first()
    assert regulation is not None
    assert regulation.title == "EU GDPR Regulation"

    raw_pages = db.query(RegulationRawPage).filter(RegulationRawPage.regulation_id == regulation.id).order_by(RegulationRawPage.page_number).all()
    assert len(raw_pages) == 3
    assert raw_pages[0].page_number == 1
    assert "Article 1" in raw_pages[0].raw_text
    assert raw_pages[1].page_number == 2
    assert raw_pages[2].page_number == 3
