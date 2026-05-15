"""
Endpoints documents PDF ORU — upload, liste, visualisation, suppression.
"""
import uuid
from pathlib import Path
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.database import get_db
from app.dependencies import get_current_user
from app.models.document import PatientDocument
from app.models.patient import Patient
from app.models.user import User

router = APIRouter()
logger = get_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class DocumentResponse(BaseModel):
    id: str
    patient_id: str
    filename: str
    original_filename: str
    file_size: Optional[int]
    notes: Optional[str]
    uploaded_at: str

    model_config = {"from_attributes": True}


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    patient_id: UUID = Form(...),
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Upload un PDF ORU associé à un patient."""
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient introuvable")

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 50 MB)")

    doc_id = uuid.uuid4()
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"
    safe_filename = f"{doc_id}{suffix}"
    dest_dir = settings.DOCUMENTS_PATH / str(patient_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_filename

    with open(dest_path, "wb") as f:
        f.write(content)

    doc = PatientDocument(
        id=doc_id,
        patient_id=patient_id,
        filename=safe_filename,
        original_filename=file.filename or "document.pdf",
        file_path=str(dest_path),
        file_size=len(content),
        notes=notes,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    logger.info(f"[DOCUMENTS] Upload OK — patient={patient_id} doc={doc_id}")
    return DocumentResponse(
        id=str(doc.id),
        patient_id=str(doc.patient_id),
        filename=doc.filename,
        original_filename=doc.original_filename,
        file_size=doc.file_size,
        notes=doc.notes,
        uploaded_at=doc.uploaded_at.isoformat(),
    )


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    patient_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Liste les documents d'un patient, du plus récent au plus ancien."""
    stmt = (
        select(PatientDocument)
        .where(PatientDocument.patient_id == patient_id)
        .order_by(PatientDocument.uploaded_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()
    return [
        DocumentResponse(
            id=str(d.id),
            patient_id=str(d.patient_id),
            filename=d.filename,
            original_filename=d.original_filename,
            file_size=d.file_size,
            notes=d.notes,
            uploaded_at=d.uploaded_at.isoformat(),
        )
        for d in docs
    ]


@router.get("/{doc_id}/view")
async def view_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Sert le PDF inline (Content-Disposition: inline) pour la visionneuse."""
    doc = await db.get(PatientDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur")
    return FileResponse(
        path=doc.file_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.original_filename}"',
        },
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprime un document et son fichier physique."""
    doc = await db.get(PatientDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")

    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()

    await db.delete(doc)
    await db.commit()
    logger.info(f"[DOCUMENTS] Supprimé — doc={doc_id}")
