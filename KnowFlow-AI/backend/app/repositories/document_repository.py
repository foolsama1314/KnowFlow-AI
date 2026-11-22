"""文档数据访问。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Document, DocumentBlock, DocumentChunk, DocumentPage


def create_document(
    db,
    *,
    name: str,
    original_name: str,
    file_type: str,
    file_size: int,
    file_path: str,
    file_hash: str,
) -> Document:
    document = Document(
        name=name,
        original_name=original_name,
        file_type=file_type,
        file_size=file_size,
        file_path=file_path,
        file_hash=file_hash,
        status="uploaded",
        page_count=0,
        chunk_count=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_document(db, document_id: str) -> Document | None:
    return db.get(Document, document_id)


def find_by_hash(db, file_hash: str) -> Document | None:
    return db.scalar(select(Document).where(Document.file_hash == file_hash).limit(1))


def list_documents(
    db,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    file_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[Document], int]:
    stmt = select(Document)
    if status:
        stmt = stmt.where(Document.status == status)
    if file_type:
        stmt = stmt.where(Document.file_type == file_type)
    if keyword:
        stmt = stmt.where(Document.name.contains(keyword))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def delete_document(db, document: Document) -> None:
    db.query(DocumentBlock).filter(DocumentBlock.document_id == document.id).delete()
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
    db.query(DocumentPage).filter(DocumentPage.document_id == document.id).delete()
    db.delete(document)
    db.commit()


def get_pages(db, document_id: str) -> list[DocumentPage]:
    return list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        ).all()
    )


def get_blocks(db, document_id: str) -> list[DocumentBlock]:
    return list(
        db.scalars(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.block_order, DocumentBlock.id)
        ).all()
    )


def get_chunks(db, chunk_ids: list[str]) -> dict[str, DocumentChunk]:
    if not chunk_ids:
        return {}
    rows = db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))).all()
    return {row.id: row for row in rows}
