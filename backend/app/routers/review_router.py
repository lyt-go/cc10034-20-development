"""结果复核包 API：差分查询复核证据的构建、补证、申请与提交。

路由前缀 /api/review 为固定路径，在通用资源路由 /api/{module} 之前注册，
不会被动态模块路径抢占。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.review_package import service

router = APIRouter(prefix="/api/review", tags=["结果复核包"])


class BuildPackagePayload(BaseModel):
    query_id: int
    reexecute: bool = False


class EvidencePayload(BaseModel):
    query_id: int
    param_version: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    evidence_no: str | None = None


class OpenRequestPayload(BaseModel):
    query_id: int


@router.get("/param-versions")
def param_versions() -> dict[str, Any]:
    """参数台账：全部配置版本、当前指纹与生效状态。"""
    versions = service.param_versions()
    return {"items": versions, "total": len(versions), "current": service._current_effective_version()}


@router.post("/packages")
def build_package(payload: BuildPackagePayload) -> dict[str, Any]:
    """构建（或重新执行并重建）指定查询执行的结果复核包。"""
    package, message = service.build_package(payload.query_id, reexecute=payload.reexecute)
    return {"ok": package is not None, "message": message, "entry": package}


@router.get("/packages")
def list_packages(query_id: int | None = None) -> dict[str, Any]:
    items = service.list_packages(query_id)
    return {"items": items, "total": len(items)}


@router.get("/packages/{package_id}")
def get_package(package_id: int) -> dict[str, Any]:
    """证据包详情页：刷新即重算三联核对，迟到补证即时反映资格变化。"""
    package = service.get_package(package_id)
    if package is None:
        return {"ok": False, "message": f"复核包 {package_id} 不存在", "entry": None}
    return {"ok": True, "message": "复核包详情", "entry": package}


@router.post("/evidence")
def register_evidence(payload: EvidencePayload) -> dict[str, Any]:
    """登记迟到的原执行参数证据；错版或指纹不符的证据只留痕、不可采信。"""
    evidence, message = service.register_evidence(
        payload.query_id,
        payload.param_version,
        payload.snapshot,
        payload.source or "",
        payload.evidence_no,
    )
    return {"ok": evidence is not None and evidence.get("valid") is True, "message": message, "entry": evidence}


@router.get("/evidence")
def list_evidence(query_id: int | None = None) -> dict[str, Any]:
    items = service.list_evidence(query_id)
    return {"items": items, "total": len(items)}


@router.post("/requests")
def open_request(payload: OpenRequestPayload) -> dict[str, Any]:
    """打开一笔复核申请（待办）；资格不足时进入待补证，不阻塞登记。"""
    request, message = service.open_request(payload.query_id)
    return {"ok": request is not None, "message": message, "entry": request}


@router.get("/requests")
def list_requests(query_id: int | None = None) -> dict[str, Any]:
    items = service.list_requests(query_id)
    return {"items": items, "total": len(items)}


@router.post("/requests/{request_id}/submit")
def submit_request(request_id: int) -> dict[str, Any]:
    """提交复核：重新做三联核对，无证记录不会被签成旧结果。"""
    request, message = service.submit_request(request_id)
    return {
        "ok": request is not None and request.get("status") == "已提交",
        "message": message,
        "entry": request,
    }
