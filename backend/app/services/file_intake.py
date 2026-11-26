"""文件投递领域服务：负责异构文件批次接入登记、来源清单批量受理与接收节点分发，产出投递批次数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.source_manifest import SourceManifestService, _text
from app.store import store


class FileIntakeService(BaseModuleService):
    MODULE = "file_intake"
    ENTITY = "投递批次"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["批次编号", "来源渠道", "原始文件名", "字节大小", "投递时间", "文件后缀", "声明格式", "接收节点"]
    REQUIRED_FIELDS = ["批次编号", "来源渠道", "原始文件名"]
    STATUS_ORDER = ["已接收", "待探测", "待外部确认", "探测失败", "已入库"]
    ACTION_RULES = {"发起探测": "待探测", "标记失败": "探测失败", "确认入库": "已入库"}
    NEGATIVE_ACTIONS = []

    def __init__(self) -> None:
        # 清单逻辑放在独立服务中；这里保留委托方法，方便从文件投递工作台直接调用。
        self.manifest_service = SourceManifestService()

    def preview_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.preview_manifest(payload, **kwargs)

    def import_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.import_manifest(payload, **kwargs)

    def register_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.import_manifest(payload, **kwargs)

    def submit_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.import_manifest(payload, **kwargs)

    def manifest_detail(self, manifest_no: str) -> dict[str, Any] | None:
        return self.manifest_service.get_manifest_detail(manifest_no)

    def continue_manifest(self, manifest_no: str, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.continue_manifest(manifest_no, payload, **kwargs)

    def confirm_external(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.manifest_service.confirm_external(payload, **kwargs)

    def file_content(self, receive_no: str) -> dict[str, Any] | None:
        return self.manifest_service.file_content(receive_no)

    def open_file_for_receipt(self, receipt_or_no: Any) -> dict[str, Any] | None:
        """回执结果未知时，按受理编号/收件编号打开对应来源文件核对。"""
        value = _text(receipt_or_no)
        receipt = self.manifest_service.find_receipt(value)
        receive_no = value
        if receipt is not None:
            receive_no = str(receipt.get("收件编号") or receipt.get("实际收件编号") or value)
        return self.manifest_service.file_content(receive_no)

    def list_manifests(self) -> list[dict[str, Any]]:
        return self.manifest_service.list_manifests()

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action == "补登外部确认":
            entry = store.find(self.MODULE, entry_id)
            if entry is None:
                return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
            result = self.manifest_service.confirm_external({
                "receive_no": entry.get("批次编号", ""),
            })
            if not result.get("ok"):
                return None, str(result.get("message") or "外部确认失败")
            return entry, str(result.get("message"))
        return super().run_action(entry_id, action)
