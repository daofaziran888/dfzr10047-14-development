"""来源文件清单领域服务的命名兼容入口，实现位于 source_manifest。"""
from app.services.source_manifest import SourceManifestService

SourceFileManifestService = SourceManifestService

__all__ = ["SourceManifestService", "SourceFileManifestService"]
