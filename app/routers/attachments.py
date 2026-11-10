"""Resolve: ticket attachment routes."""
from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.rate_limit import limiter
from app.dependencies import AttachmentSvc, CurrentUser
from app.schemas import AttachmentRead

attachments_router = APIRouter(
    prefix="/tickets/{ticket_id}/attachments", tags=["attachments"]
)


@attachments_router.post("", response_model=AttachmentRead, status_code=201)
@limiter.limit(settings.rate_limit_upload)
async def upload_attachment(
    request: Request,
    ticket_id: int,
    file: UploadFile,
    user: CurrentUser,
    svc: AttachmentSvc,
):
    """multipart/form-data with a 'file' field. JPEG, PNG, WebP or PDF."""
    return await svc.upload(user, ticket_id, file)


@attachments_router.get("/{attachment_id}/download")
async def download_attachment(
    ticket_id: int, attachment_id: int, user: CurrentUser, svc: AttachmentSvc
):
    att, path = await svc.get_for_download(user, ticket_id, attachment_id)
    return FileResponse(
        path,
        media_type=att.content_type,
        filename=att.filename,
        content_disposition_type="attachment",  # never render uploads in-browser
        headers={"X-Content-Type-Options": "nosniff"},
    )


@attachments_router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    ticket_id: int, attachment_id: int, user: CurrentUser, svc: AttachmentSvc
):
    await svc.delete(user, ticket_id, attachment_id)
    return Response(status_code=204)
