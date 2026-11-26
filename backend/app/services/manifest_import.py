"""来源文件清单导入服务的兼容模块，具体实现见 source_manifest。"""
from app.services.source_manifest import SourceManifestService

ManifestImportService = SourceManifestService

__all__ = ["SourceManifestService", "ManifestImportService"]
