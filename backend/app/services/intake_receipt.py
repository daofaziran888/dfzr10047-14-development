"""逐项受理回执服务的命名兼容入口，复用来源清单受理实现。"""
from app.services.source_manifest import SourceManifestService


class IntakeReceiptService(SourceManifestService):
    """保留独立类名，供按受理回执领域命名的调用方导入。"""


__all__ = ["IntakeReceiptService"]
