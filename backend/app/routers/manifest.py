"""来源清单导入、逐项回执、文件核对与指纹核销的专用 HTTP 接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from app.services import service_for
from app.services.result_deliver import ResultDeliverService
from app.services.source_manifest import SourceManifestService
from app.store import store

router = APIRouter(tags=["来源清单批量受理"])
manifest_service = SourceManifestService()


def _manifest_svc() -> SourceManifestService:
    # 优先使用注册表里的实例；服务本身只依赖全局 store，新建实例也等价。
    registered = service_for("source_manifest")
    return registered if isinstance(registered, SourceManifestService) else manifest_service


@router.post("/api/file_intake/manifests/preview")
@router.post("/api/file_intake/manifest/preview")
@router.post("/api/file_intake/manifest-preview")
@router.post("/api/file_intake/preview")
@router.post("/api/file-intake/manifests/preview")
@router.post("/api/source_manifest/preview")
@router.post("/api/manifests/preview")
@router.post("/api/manifest/preview")
def preview_manifest(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _manifest_svc().preview_manifest(payload)


@router.post("/api/file_intake/manifests/upload")
@router.post("/api/file_intake/manifest/upload")
async def upload_manifest(request: Request, preview: bool = False, manifest_no: str = "") -> dict[str, Any]:
    body = (await request.body()).decode("utf-8-sig", errors="replace")
    payload: dict[str, Any] = {"text": body}
    if manifest_no:
        payload["manifest_no"] = manifest_no
    service = _manifest_svc()
    return service.preview_manifest(payload) if preview else service.import_manifest(payload)


@router.post("/api/file_intake/manifests/import")
@router.post("/api/file_intake/manifest/import")
@router.post("/api/file_intake/import")
@router.post("/api/file_intake/manifest-import")
@router.post("/api/file_intake/manifests")
@router.post("/api/file_intake/manifest")
@router.post("/api/file_intake/batch")
@router.post("/api/file_intake/batch-register")
@router.post("/api/file_intake/items/batch")
@router.post("/api/file-intake/manifests/import")
@router.post("/api/source_manifest/import")
@router.post("/api/manifests/import")
@router.post("/api/manifest/import")
@router.post("/api/manifests")
def import_manifest(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _manifest_svc().import_manifest(payload)


@router.get("/api/file_intake/manifests")
@router.get("/api/file_intake/manifest")
@router.get("/api/source_manifest/manifests")
@router.get("/api/manifests")
def list_manifests() -> dict[str, Any]:
    items = _manifest_svc().list_manifests()
    return {"items": items, "total": len(items), "ok": True}


@router.get("/api/file_intake/manifests/{manifest_no}")
@router.get("/api/file_intake/manifest/{manifest_no}")
@router.get("/api/manifests/{manifest_no}")
def manifest_detail(manifest_no: str) -> dict[str, Any]:
    detail = _manifest_svc().get_manifest_detail(manifest_no)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"清单 {manifest_no} 不存在")
    return {"ok": True, **detail}


@router.post("/api/file_intake/manifests/{manifest_no}/continue")
@router.post("/api/file_intake/manifests/{manifest_no}/retry")
@router.post("/api/manifests/{manifest_no}/continue")
@router.post("/api/manifests/{manifest_no}/retry")
def continue_manifest(
    manifest_no: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return _manifest_svc().continue_manifest(manifest_no, payload)


@router.post("/api/file_intake/receipts/external-confirmation")
@router.post("/api/file_intake/receipts/confirm-external")
@router.post("/api/file_intake/confirm_external")
@router.post("/api/file_intake/external-confirmation")
@router.post("/api/manifests/external-confirmation")
@router.post("/api/manifests/confirm-external")
@router.post("/api/manifest/confirm-external")
def confirm_external(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _manifest_svc().confirm_external(payload)


@router.post("/api/file_intake/receipts/{receipt_id}/external-confirmation")
@router.post("/api/file_intake/receipts/{receipt_id}/confirm")
def confirm_receipt_by_path(
    receipt_id: str, payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    payload = {**payload, "receipt_id": receipt_id}
    return _manifest_svc().confirm_external(payload)


@router.get("/api/file_intake/files/{receive_no}/content")
@router.get("/api/file_intake/batches/{receive_no}/content")
@router.get("/api/file_intake/{receive_no}/content")
def read_file_content(receive_no: str, raw: bool = False) -> Any:
    result = _manifest_svc().file_content(receive_no)
    if result is None:
        raise HTTPException(status_code=404, detail=f"收件编号 {receive_no} 不存在")
    if raw:
        return Response(content=str(result.get("content") or ""), media_type="text/plain; charset=utf-8")
    return {"ok": True, **result}


@router.get("/api/result_deliver/records/{delivery_no}/content")
@router.get("/api/result_deliver/{delivery_no}/target-content")
def read_target_content(delivery_no: str, raw: bool = False) -> Any:
    record = next(
        (row for row in store.rows("result_deliver") if row.get("投递记录编号") == delivery_no),
        None,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"投递记录 {delivery_no} 不存在")
    result = {
        "ok": True,
        "delivery_no": delivery_no,
        "target_path": record.get("目标位置", ""),
        "content": record.get("目标实际内容", ""),
        "content_hash": record.get("目标内容指纹", ""),
        "receive_no": record.get("实际收件编号") or record.get("收件编号", ""),
    }
    if raw:
        return Response(content=str(result["content"]), media_type="text/plain; charset=utf-8")
    return result


@router.post("/api/result_deliver/reconcile-fingerprints")
@router.post("/api/result_deliver/reconcile_fingerprints")
@router.post("/api/result_deliver/reconcile-fingerprint-batches")
@router.post("/api/result_deliver/reconcile_fingerprint_batches")
@router.post("/api/result_deliver/reconcile")
@router.post("/api/result_deliver/write-off")
@router.post("/api/result_deliver/write_off_batches")
@router.post("/api/deliveries/reconcile-fingerprints")
@router.post("/api/deliveries/reconcile")
def reconcile_deliveries(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    service = ResultDeliverService()
    return service.reconcile_manifest_batches(
        manifest_no=str(payload.get("manifest_no") or payload.get("清单编号") or ""),
        source=str(payload.get("source") or payload.get("来源渠道") or ""),
        receipt_ids=payload.get("receipt_ids") or payload.get("selected"),
        deliver=bool(payload.get("deliver", True)),
        reconcile_time=str(payload.get("time") or payload.get("reconcile_time") or ""),
    )


@router.get("/api/result_deliver/reconcile-fingerprints")
@router.get("/api/result_deliver/reconcile_fingerprints")
@router.get("/api/result_deliver/reconcile-fingerprint-batches")
@router.get("/api/result_deliver/reconcile")
def preview_reconciliation(manifest_no: str = "", source: str = "") -> dict[str, Any]:
    service = ResultDeliverService()
    return service.reconcile_manifest_batches(
        manifest_no=manifest_no, source=source, deliver=False,
    )
