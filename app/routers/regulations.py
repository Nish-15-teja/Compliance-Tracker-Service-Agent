import os
import shutil
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import get_db, Regulation, RegulationRawPage
from app.ingestion import parse_document
from app.agents.extraction_agent import extract_clauses, extract_all_obligations_for_regulation
from app.agents.change_impact_agent import detect_changes, propagate_impact
from app.schemas import RegulationUploadResponse

from app.db import get_db, Regulation, RegulationRawPage, RegulationClause

router = APIRouter(prefix="/regulations", tags=["Regulations"])

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "regulations")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("")
def list_regulations(db: Session = Depends(get_db)):
    try:
        regs = db.query(Regulation).order_by(Regulation.id.desc()).all()
        results = []
        for r in regs:
            clause_cnt = len(r.clauses) if r.clauses else 0
            ob_cnt = sum(len(c.obligations) for c in r.clauses) if r.clauses else 0
            results.append({
                "id": r.id,
                "title": r.title,
                "version_label": r.version_label,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
                "is_current_version": r.is_current_version,
                "clause_count": clause_cnt,
                "obligation_count": ob_cnt,
                "page_count": len(r.raw_pages) if r.raw_pages else 0
            })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list regulations: {str(e)}")

@router.get("/{id}/clauses")
def list_regulation_clauses(id: int, db: Session = Depends(get_db)):
    reg = db.query(Regulation).filter(Regulation.id == id).first()
    if not reg:
        raise HTTPException(status_code=404, detail=f"Regulation {id} not found")
    clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == id).all()
    return [
        {
            "id": c.id,
            "clause_identifier": c.clause_identifier,
            "clause_text": c.clause_text,
            "source_page": c.source_page,
            "parent_clause_identifier": c.parent_clause_identifier,
            "obligation_count": len(c.obligations) if c.obligations else 0
        }
        for c in clauses
    ]


@router.post("/upload", response_model=RegulationUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_regulation(
    file: UploadFile = File(...),
    title: str = Form(...),
    version_label: str = Form(...),
    db: Session = Depends(get_db)
):
    file_location = os.path.join(UPLOAD_DIR, f"{version_label}_{file.filename}")
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        parsed_doc = parse_document(file_location)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse document: {str(e)}")

    db.query(Regulation).filter(Regulation.title == title).update({"is_current_version": False})

    regulation = Regulation(
        title=title,
        version_label=version_label,
        source_file_path=file_location,
        is_current_version=True
    )
    db.add(regulation)
    db.commit()
    db.refresh(regulation)

    for page in parsed_doc.pages:
        raw_page = RegulationRawPage(
            regulation_id=regulation.id,
            page_number=page.page_number,
            raw_text=page.text_block
        )
        db.add(raw_page)

    db.commit()

    return RegulationUploadResponse(
        regulation_id=regulation.id,
        title=regulation.title,
        version_label=regulation.version_label,
        page_count=len(parsed_doc.pages),
        message="Regulation uploaded and raw pages staged successfully."
    )

@router.post("/{id}/extract-clauses")
def extract_regulation_clauses(
    id: int,
    db: Session = Depends(get_db)
):
    try:
        summary = extract_clauses(regulation_id=id, db=db)
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Clause extraction failed: {str(e)}")

@router.post("/{id}/extract-obligations")
def extract_regulation_obligations(
    id: int,
    db: Session = Depends(get_db)
):
    try:
        summary = extract_all_obligations_for_regulation(regulation_id=id, db=db)
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Obligation extraction failed: {str(e)}")

@router.post("/{new_id}/detect-changes")
def detect_regulation_changes(
    new_id: int,
    compare_to: int,
    db: Session = Depends(get_db)
):
    try:
        report = detect_changes(old_regulation_id=compare_to, new_regulation_id=new_id, db=db)
        return report
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Change detection failed: {str(e)}")

@router.post("/{new_id}/propagate-impact")
def propagate_regulation_impact(
    new_id: int,
    db: Session = Depends(get_db)
):
    try:
        summary = propagate_impact(new_regulation_id=new_id, db=db)
        return summary
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impact propagation failed: {str(e)}")
