"""来源文件清单批量受理服务：页内预览、补正、按来源与内容核销并串联结果投递，产出清单受理回执数据集。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _sha(text: str, length: int = 16) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _md5(text: str, length: int = 16) -> str:
    return "md5:" + hashlib.md5(text.encode("utf-8")).hexdigest()[:length]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _first(data: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        if key in data and _text(data[key]):
            return _text(data[key])
    return ""


def _safe_part(value: str, fallback: str = "item") -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    text = "-".join(part for part in text.split("-") if part)
    return (text[:32] or fallback).lower()


class SourceManifestService(BaseModuleService):
    MODULE = "source_manifest"
    ENTITY = "来源清单"
    OPERATION_TERM = "导入"
    LIST_FIELDS = [
        "清单编号", "清单指纹", "来源范围", "项目总数", "受理数",
        "待补正数", "待外部确认数", "已投递数", "最近导入时间",
    ]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["预览", "校验未通过", "部分受理", "已受理", "已核销"]
    ACTION_RULES: dict[str, str] = {}

    ALIASES = {
        "item_key": ["项目标识", "文件标识", "标识", "item_key", "file_key", "key", "code"],
        "file_name": ["原始文件名", "文件名", "文件", "file_name", "filename", "name"],
        "source": ["来源渠道", "来源", "source_channel", "channel", "source"],
        "content": ["内容正文", "正文", "内容", "content", "body", "text", "content_text"],
        "content_label": ["内容版本", "内容标签", "版本标识", "content_label", "version", "payload"],
        "content_hash_ref": ["内容指纹", "content_hash", "fingerprint", "hash", "哈希", "sha256"],
        "file_format": ["声明格式", "文件格式", "格式", "declared_format", "format"],
        "suffix": ["文件后缀", "后缀", "suffix"],
        "inbox": ["收件入口", "接收入口", "接收节点", "收件节点", "inbox", "receive_node", "entry"],
        "row_count": ["结果行数", "投递行数", "row_count", "rows"],
        "target_path": ["目标位置", "target_path", "target"],
        "confirmation_no": ["外部确认编号", "确认编号", "confirmation_no"],
        "external_status": ["外部确认状态", "确认状态", "external_confirmation", "confirm_status"],
        "parse_status": ["解析状态", "parse_status"],
        "receipt_id": ["受理编号ID", "明细ID", "receipt_id", "item_id"],
        "receive_no": ["实际收件编号", "收件编号", "批次编号", "receive_no", "intake_batch"],
        "delivery_no": ["投递记录编号", "delivery_no"],
    }

    # ------------------------------------------------------------------
    # 输入解析与预览
    # ------------------------------------------------------------------
    def parse_items(self, payload: Any = None, **kwargs: Any) -> tuple[str, list[dict[str, Any]]]:
        """把 JSON/CSV/字典输入统一成清单条目，返回清单编号提示和原始条目。"""
        data: dict[str, Any] = {}
        if isinstance(payload, dict):
            data = dict(payload)
        elif isinstance(payload, list):
            kwargs["items"] = payload
        elif isinstance(payload, str):
            kwargs["text"] = payload
        if isinstance(payload, dict) and isinstance(payload.get("manifest"), (list, dict)):
            manifest_value = payload["manifest"]
            if isinstance(manifest_value, list):
                kwargs["items"] = manifest_value
            else:
                nested = manifest_value.get("items") or manifest_value.get("rows")
                if nested is not None:
                    kwargs["items"] = nested

        manifest_no = _first({**data, **kwargs}, ["manifest_no", "清单编号", "import_no"])
        text = _first({**data, **kwargs}, [
            "text", "manifest_text", "csv_text", "content_csv", "csv", "清单文本", "清单内容",
        ])
        items = (
            data.get("items") or data.get("rows") or data.get("entries")
            or data.get("files") or data.get("records") or data.get("source_files")
            or data.get("项目") or data.get("清单项目") or data.get("文件清单")
            or kwargs.get("items")
        )
        if items is None and isinstance(payload, list):
            items = payload
        if items is None and text:
            parsed_text_items = self._parse_text(text)
            return manifest_no, parsed_text_items
        if items is None:
            return manifest_no, []
        if not isinstance(items, list):
            items = [items]
        return manifest_no, [item if isinstance(item, dict) else {"value": item} for item in items]

    @staticmethod
    def _parse_text(text: str) -> list[dict[str, Any]]:
        text = text.replace("\ufeff", "")
        stripped = text.strip()
        if not stripped:
            return []
        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, list):
                return [item if isinstance(item, dict) else {"value": item} for item in loaded]
            if isinstance(loaded, dict):
                items = loaded.get("items") or loaded.get("rows") or []
                return [item if isinstance(item, dict) else {"value": item} for item in items]
        except (json.JSONDecodeError, TypeError):
            pass

        sample = stripped[:4096]
        if "\t" in sample and "," not in sample.splitlines()[0]:
            reader = csv.DictReader(io.StringIO(stripped), delimiter="\t")
        else:
            reader = csv.DictReader(io.StringIO(stripped))
        rows = [dict(row) for row in reader]
        if rows and reader.fieldnames and any(name and "=" in name for name in reader.fieldnames):
            # 不是标准 CSV 时退回逐行 key=content 解析。
            rows = []
        if rows:
            return rows

        simple: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, content = line.split("=", 1)
                simple.append({"项目标识": key.strip(), "内容": content.strip()})
            elif "," in line:
                key, content = line.split(",", 1)
                simple.append({"项目标识": key.strip(), "内容": content.strip()})
        return simple

    def normalize_item(self, raw: dict[str, Any], index: int) -> dict[str, Any]:
        """归一化一个清单项并计算来源内身份、内容证据和校验错误。"""
        item = {field: _first(raw, aliases) for field, aliases in self.ALIASES.items()}
        item["client_id"] = _first(raw, ["client_id", "row_id", "preview_id"]) or f"row-{index + 1}"
        if "selected" in raw:
            item["selected"] = bool(raw.get("selected"))
        elif "本次续做" in raw:
            item["selected"] = str(raw.get("本次续做")).lower() not in {"0", "false", "否", ""}
        else:
            item["selected"] = True

        if not item["item_key"] and not item["file_name"]:
            value = _text(raw.get("value"))
            if value:
                item["item_key"] = value
        if not item["item_key"] and item["file_name"]:
            item["item_key"] = item["file_name"].rsplit(".", 1)[0]
        if not item["file_name"] and item["item_key"]:
            suffix = item["suffix"] or (f".{item['file_format']}" if item["file_format"] else "")
            item["file_name"] = f"{item['item_key']}{suffix}"

        if not item["content"] and item["content_label"]:
            item["content"] = item["content_label"]
        elif item["content"] and not item["content_label"]:
            item["content_label"] = item["content"][:32]

        if not item["suffix"] and "." in item["file_name"]:
            item["suffix"] = "." + item["file_name"].rsplit(".", 1)[-1].lower()
        if not item["file_format"]:
            item["file_format"] = item["suffix"].lstrip(".") or "unknown"

        if not item["row_count"]:
            item["row_count"] = "1"

        wait_flag = _first(raw, [
            "wait_external", "requires_external_confirmation", "external_required",
            "需外部确认", "需要外部确认", "等待外部确认",
        ]).casefold()
        if wait_flag in {"1", "true", "yes", "y", "是", "待确认", "等待"} and not item["external_status"]:
            item["external_status"] = "待确认"

        errors: dict[str, str] = {}
        if not item["item_key"]:
            errors["项目标识"] = "缺少项目标识或原始文件名"
        if not item["source"]:
            errors["来源渠道"] = "缺少来源渠道，不能用其他来源的登记或结论抵扣"
        if not item["content"] and not item["content_hash_ref"]:
            errors["内容"] = "缺少内容、内容版本或内容指纹，无法按内容核销"

        item["valid"] = not errors
        item["errors"] = errors
        item["missing_fields"] = list(errors)
        item["content_hash"] = (
            _sha(item["content"]) if item["content"] else item["content_hash_ref"]
        )
        item["structure_hash"] = _md5(item["file_format"] + "|" + item["file_name"])
        item["source_key"] = item["source"].casefold()
        item["identity_key"] = "|".join([
            item["source_key"], item["item_key"].casefold(), item["content_hash"],
        ]) if item["valid"] else ""
        item["variant_group"] = "|".join([item["source_key"], item["item_key"].casefold()])
        item["inbox"] = item["inbox"] or (
            f"inbox://{_safe_part(item['source'], 'unknown-source')}/"
            f"{_safe_part(item['item_key'], 'file')}"
            if item["source"] and item["item_key"] else ""
        )
        item["content_url"] = ""
        item["match_type"] = self._match_type(item)
        return item

    def _match_type(self, item: dict[str, Any]) -> str:
        if not item["valid"]:
            return "校验未通过"
        receipts = store.rows("manifest_receipt")
        exact = next((r for r in receipts if r.get("身份键") == item["identity_key"]), None)
        if exact is not None:
            return "重复清单/已受理"
        same_identity = [
            r for r in receipts
            if r.get("异件组") == item["variant_group"] and r.get("内容指纹") != item["content_hash"]
        ]
        if same_identity:
            return "同名异件"
        other_source_same_name = [
            r for r in receipts
            if r.get("项目标识") == item["item_key"]
            and r.get("来源渠道", "").casefold() != item["source_key"]
            and (r.get("原始文件名") == item["file_name"] or r.get("声明格式") == item["file_format"])
        ]
        if other_source_same_name:
            return "异源同名/结论隔离"
        return "新受理"

    def normalize_payload(self, payload: Any = None, **kwargs: Any) -> tuple[str, list[dict[str, Any]], str]:
        manifest_no, raw_items = self.parse_items(payload, **kwargs)
        items = [self.normalize_item(raw, i) for i, raw in enumerate(raw_items)]
        fingerprint = self.manifest_fingerprint(items)
        return manifest_no, items, fingerprint

    @staticmethod
    def manifest_fingerprint(items: list[dict[str, Any]]) -> str:
        canonical_rows = sorted(
            [
                _text(item.get("source")), _text(item.get("item_key")),
                _text(item.get("file_name")), _text(item.get("content")),
            ]
            for item in items
        )
        canonical = json.dumps(canonical_rows, ensure_ascii=False, sort_keys=True)
        return _sha(canonical)

    def preview_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        _no, items, fingerprint = self.normalize_payload(payload, **kwargs)
        existing = self._find_manifest_by_fingerprint(fingerprint)
        for item in items:
            item["related_receipts"] = self.related_receipts(item)
        return {
            "ok": True,
            "message": "清单预览已生成，可补填校验未通过项目并勾选本次续做项",
            "manifest_no": existing.get("清单编号", "") if existing else _no,
            "manifest_fingerprint": fingerprint,
            "duplicate": bool(existing),
            "items": items,
            "valid_items": sum(1 for x in items if x["valid"]),
            "invalid_items": sum(1 for x in items if not x["valid"]),
            "summary": self._preview_summary(items),
        }

    @staticmethod
    def _preview_summary(items: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(items),
            "valid": sum(1 for x in items if x["valid"]),
            "invalid": sum(1 for x in items if not x["valid"]),
            "selected": sum(1 for x in items if x.get("selected")),
            "same_name_variants": sum(1 for x in items if x.get("match_type") == "同名异件"),
        }

    def related_receipts(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in store.rows("manifest_receipt"):
            same_exact = item["identity_key"] and row.get("身份键") == item["identity_key"]
            same_variant = item["variant_group"] and row.get("异件组") == item["variant_group"]
            other_source = (
                row.get("项目标识") == item.get("item_key")
                and row.get("来源渠道", "").casefold() != item.get("source_key")
            )
            if same_exact or same_variant or other_source:
                result.append(self.public_receipt(row))
        return result

    # ------------------------------------------------------------------
    # 清单持久化与逐项受理
    # ------------------------------------------------------------------
    def _next_pk(self, table: str) -> int:
        rows = store.rows(table)
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def _find_manifest_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            fingerprints = [row.get("清单指纹", ""), *row.get("历史指纹", [])]
            if fingerprint in fingerprints:
                return row
        return None

    def get_manifest_row(self, manifest_no: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(self.MODULE) if row.get("清单编号") == manifest_no),
            None,
        )

    def get_manifest_detail(self, manifest_no: str) -> dict[str, Any] | None:
        row = self.get_manifest_row(manifest_no)
        if row is None:
            return None
        receipts = [
            self.public_receipt(r)
            for r in store.rows("manifest_receipt")
            if r.get("清单编号") == manifest_no
        ]
        return {**row, "receipts": receipts, "items": receipts}

    def list_manifests(self) -> list[dict[str, Any]]:
        return [dict(row) for row in reversed(store.rows(self.MODULE))]

    def import_manifest(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        """提交清单。单项失败不影响其他项；相同来源+标识+内容幂等受理。"""
        data = payload if isinstance(payload, dict) else {}
        submitted_no, items, fingerprint = self.normalize_payload(payload, **kwargs)
        if not items and (
            data.get("receipt_ids") or data.get("selected")
            or data.get("retry_existing") or data.get("continue_existing")
        ):
            items = self._retry_items_from_store(
                submitted_no or _text(data.get("manifest_no") or data.get("清单编号")),
                data.get("receipt_ids") or data.get("selected"),
            )
            _no, items, fingerprint = self.normalize_payload({"items": items}, **kwargs)
        if not items:
            return {"ok": False, "message": "清单中没有可导入项目", "manifest_no": "", "receipts": []}

        import_time = _first({**(payload if isinstance(payload, dict) else {}), **kwargs},
                             ["import_time", "submit_time", "time"]) or _now()
        selected_filter = self._selected_filter(payload, kwargs)
        existing_by_hash = self._find_manifest_by_fingerprint(fingerprint)
        manifest_no = (
            submitted_no
            or (existing_by_hash or {}).get("清单编号", "")
            or f"SM-{self._next_pk(self.MODULE):04d}"
        )
        manifest = self.get_manifest_row(manifest_no)
        if manifest is None:
            manifest = {
                "id": self._next_pk(self.MODULE),
                "清单编号": manifest_no,
                "清单指纹": fingerprint,
                "历史指纹": [],
                "来源范围": "",
                "项目总数": 0,
                "受理数": 0,
                "待补正数": 0,
                "待外部确认数": 0,
                "已投递数": 0,
                "最近导入时间": import_time,
                "status": "部分受理",
                "pending": True,
                "abnormal": False,
            }
            store.rows(self.MODULE).append(manifest)
        elif fingerprint != manifest.get("清单指纹"):
            manifest.setdefault("历史指纹", []).append(manifest.get("清单指纹"))
            manifest["清单指纹"] = fingerprint
        manifest["最近导入时间"] = import_time

        receipts: list[dict[str, Any]] = []
        processed = 0
        skipped = 0
        for item in items:
            if not self._is_selected(item, selected_filter):
                skipped += 1
                continue
            processed += 1
            try:
                row = self._upsert_and_accept_item(manifest_no, item, import_time)
            except Exception as exc:  # 单项异常隔离：其他成功项保留，不要求整单重传
                row = self._new_receipt_row(manifest_no, item, import_time)
                store.rows("manifest_receipt").append(row)
                row.update(self._receipt_base(item))
                row.update({
                    "受理状态": "处理失败",
                    "status": "处理失败",
                    "pending": True,
                    "abnormal": True,
                    "错误信息": f"服务端处理失败：{exc}",
                })
            receipts.append(self.public_receipt(row))

        self._refresh_manifest_counts(manifest_no)
        detail = self.get_manifest_detail(manifest_no)
        assert detail is not None
        invalid = sum(1 for r in detail["receipts"] if r.get("受理状态") == "待补正")
        duplicate = existing_by_hash is not None and existing_by_hash.get("清单编号") == manifest_no
        duplicate_prefix = "相同清单重复导入，只记一次受理；" if duplicate else ""
        detail.update({
            "ok": True,
            "duplicate": duplicate,
            "processed": processed,
            "skipped": skipped,
            "accepted": manifest.get("受理数", 0),
            "invalid": manifest.get("待补正数", 0),
            "pending_correction": manifest.get("待补正数", 0),
            "waiting_confirmation": manifest.get("待外部确认数", 0),
            "delivered_count": manifest.get("已投递数", 0),
            "message": (
                f"{duplicate_prefix}清单 {manifest_no} 已处理 {processed} 项，跳过 {skipped} 项；"
                f"待补正 {invalid} 项，已有成功回执不会因其他项目报错而重传"
            ),
        })
        if kwargs.get("auto_deliver") or (isinstance(payload, dict) and payload.get("auto_deliver")):
            from app.services.result_deliver import ResultDeliverService
            detail["reconciliation"] = ResultDeliverService().reconcile_manifest_batches(
                manifest_no=manifest_no, reconcile_time=import_time,
            )
        return detail

    @staticmethod
    def _selected_filter(payload: Any, kwargs: dict[str, Any]) -> set[str] | None:
        raw = kwargs.get("selected")
        if raw is None and isinstance(payload, dict):
            raw = payload.get("selected_items") or payload.get("selected")
        if raw is None:
            return None
        if not isinstance(raw, list):
            raw = [raw]
        values: set[str] = set()
        for value in raw:
            if isinstance(value, dict):
                for key in ("id", "receipt_id", "client_id", "项目标识", "key"):
                    if key in value:
                        values.add(_text(value[key]))
            else:
                values.add(_text(value))
        return values

    @staticmethod
    def _is_selected(item: dict[str, Any], selected_filter: set[str] | None) -> bool:
        if selected_filter is not None:
            candidates = {
                _text(item.get("client_id")), _text(item.get("item_key")),
                _text(item.get("receipt_id")),
            }
            return bool(candidates & selected_filter)
        return bool(item.get("selected", True))

    def _find_pending_receipt(self, manifest_no: str, item: dict[str, Any]) -> dict[str, Any] | None:
        receipt_id = item.get("receipt_id")
        if receipt_id and str(receipt_id).isdigit():
            row = store.find("manifest_receipt", int(receipt_id))
            if row is not None:
                return row
        for row in store.rows("manifest_receipt"):
            if row.get("清单编号") != manifest_no:
                continue
            if row.get("项目标识") != item["item_key"] or row.get("受理状态") != "待补正":
                continue
            row_source = str(row.get("来源渠道") or "").casefold()
            if row_source and item.get("source_key") and row_source != item["source_key"]:
                continue
            if (
                item.get("content_hash") and row.get("内容指纹")
                and row.get("内容指纹") != item["content_hash"]
            ):
                continue
            return row
        if item["item_key"]:
            pending = []
            for row in store.rows("manifest_receipt"):
                if row.get("项目标识") != item["item_key"] or row.get("受理状态") != "待补正":
                    continue
                row_source = str(row.get("来源渠道") or "").casefold()
                same_or_missing_source = (
                    not row_source or row_source == item.get("source_key", "")
                )
                same_content = (
                    not item.get("content_hash")
                    or not row.get("内容指纹")
                    or row.get("内容指纹") == item.get("content_hash")
                )
                if same_or_missing_source and same_content:
                    pending.append(row)
            if pending:
                return pending[-1]
        return None

    def _find_exact_receipt(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if not item["identity_key"]:
            return None
        return next(
            (r for r in store.rows("manifest_receipt") if r.get("身份键") == item["identity_key"]),
            None,
        )

    def _upsert_and_accept_item(
        self, manifest_no: str, item: dict[str, Any], when: str,
    ) -> dict[str, Any]:
        # 校验未通过：保留/更新待补正明细，不创建收件批次。
        if not item["valid"]:
            row = self._find_pending_receipt(manifest_no, item)
            if row is None:
                row = self._new_receipt_row(manifest_no, item, when)
                store.rows("manifest_receipt").append(row)
            row.update(self._receipt_base(item))
            row["受理状态"] = "待补正"
            row["status"] = "待补正"
            row["pending"] = True
            row["abnormal"] = True
            row["错误信息"] = "；".join(item["errors"].values())
            return row

        exact = self._find_exact_receipt(item)
        if exact is not None:
            # 相同来源+标识+内容：幂等复用实际收件编号和已有回执。
            exact["最近重复提交时间"] = when
            exact["重复提交次数"] = str(int(_text(exact.get("重复提交次数")) or "0") + 1)
            if manifest_no != exact.get("清单编号"):
                exact.setdefault("出现清单", [])
                if manifest_no not in exact["出现清单"]:
                    exact["出现清单"].append(manifest_no)
            return exact

        pending = self._find_pending_receipt(manifest_no, item)
        if pending is not None:
            row = pending
        else:
            row = self._new_receipt_row(manifest_no, item, when)
            store.rows("manifest_receipt").append(row)

        row.update(self._receipt_base(item))
        row["错误信息"] = ""
        row["重复提交次数"] = "0"
        row["受理时间"] = when

        require_external = self._requires_external_confirmation(item)
        row["外部确认"] = "待确认" if require_external else "未要求"
        row["外部确认状态"] = row["外部确认"]
        row["外部确认编号"] = item["confirmation_no"] if require_external and item["confirmation_no"] else ""
        if require_external and item.get("external_status") in {"已确认", "confirmed"}:
            row["外部确认"] = "已确认"
            row["外部确认状态"] = "已确认"
            row["外部确认编号"] = item["confirmation_no"] or f"EXT-{row['id']:04d}"
            row["确认时间"] = when

        intake = self._create_or_reuse_intake(row, item, when)
        row["收件编号"] = intake["批次编号"]
        row["实际收件编号"] = intake["批次编号"]
        row["收件入口"] = intake.get("接收节点", item["inbox"])
        row["content_url"] = f"/api/file_intake/files/{intake['批次编号']}/content"

        variants = [
            r for r in store.rows("manifest_receipt")
            if r.get("异件组") == item["variant_group"] and r.get("id") != row.get("id")
        ]
        if variants:
            row["同名异件"] = "是"
            row["关联异件"] = [r.get("受理编号") for r in variants]
            for old in variants:
                linked = set(old.get("关联异件") or [])
                linked.add(row["受理编号"])
                old["关联异件"] = sorted(linked)
                old["同名异件"] = "是"
        else:
            row["同名异件"] = "否"

        if row["外部确认"] == "待确认":
            row["受理状态"] = "待外部确认"
            row["status"] = "待外部确认"
            row["pending"] = True
            row["abnormal"] = False
        else:
            row["受理状态"] = "可投递"
            row["status"] = "已受理"
            row["pending"] = True
            row["abnormal"] = False

        self._record_fingerprint(row, item, when)
        return row

    def _new_receipt_row(self, manifest_no: str, item: dict[str, Any], when: str) -> dict[str, Any]:
        pk = self._next_pk("manifest_receipt")
        row = {
            "id": pk,
            "受理编号": f"AR-{pk:04d}",
            "清单编号": manifest_no,
            "投递记录编号": item.get("delivery_no", ""),
            "收件编号": item.get("receive_no", ""),
            "实际收件编号": "",
            "契约编号": f"OC-MR-{pk:04d}",
            "投递记录建议编号": f"RD-MR-{pk:04d}",
            "创建时间": when,
        }
        return row

    @staticmethod
    def _receipt_base(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "项目标识": item["item_key"],
            "原始文件名": item["file_name"],
            "来源渠道": item["source"],
            "声明格式": item["file_format"],
            "文件后缀": item["suffix"],
            "收件入口": item["inbox"],
            "内容标签": item["content_label"],
            "内容正文": item["content"],
            "内容证据": item["content_hash"],
            "内容指纹": item["content_hash"],
            "结构指纹": item["structure_hash"],
            "身份键": item["identity_key"],
            "异件组": item["variant_group"],
            "目标位置": item.get("target_path", ""),
            "结果行数": item.get("row_count", "1") or "1",
        }

    @staticmethod
    def _requires_external_confirmation(item: dict[str, Any]) -> bool:
        status = item.get("external_status", "")
        if status in {"待确认", "等待确认", "pending", "waiting"}:
            return True
        # 验收样例可显式传 wait_external/需外部确认；字典归一化未保留布尔值，
        # 因此 parse 后这里从原始 aliases 无法取，调用方通常用状态字段。
        return "待外部确认" in status or "等待外部确认" in status

    def _create_or_reuse_intake(
        self, receipt: dict[str, Any], item: dict[str, Any], when: str,
    ) -> dict[str, Any]:
        receive_no = receipt.get("收件编号") or f"FI-MR-{int(receipt['id']):04d}"
        existing = next(
            (r for r in store.rows("file_intake") if r.get("批次编号") == receive_no),
            None,
        )
        if existing is not None:
            return existing

        pk = max((int(r.get("id", 0)) for r in store.rows("file_intake")), default=0) + 1
        waiting = receipt.get("外部确认") == "待确认"
        intake = {
            "id": pk,
            "status": "待外部确认" if waiting else "已接收",
            "pending": True,
            "abnormal": False,
            "批次编号": receive_no,
            "来源渠道": item["source"],
            "原始文件名": item["file_name"],
            "字节大小": str(len(item["content"].encode("utf-8"))),
            "投递时间": when,
            "文件后缀": item["suffix"],
            "声明格式": item["file_format"],
            "接收节点": item["inbox"],
            "项目标识": item["item_key"],
            "内容指纹": item["content_hash"],
            "清单编号": receipt["清单编号"],
            "受理编号": receipt["受理编号"],
            "内容正文": item["content"],
        }
        if item.get("parse_status"):
            intake["解析状态"] = item["parse_status"]
            if "已解析" in item["parse_status"] and waiting:
                intake["status"] = "待外部确认"
        store.rows("file_intake").append(intake)
        return intake

    def _record_fingerprint(
        self, receipt: dict[str, Any], item: dict[str, Any], when: str,
    ) -> None:
        """保存来源隔离的指纹结论；不把其他来源的同内容/同格式当作抵扣。"""
        rows = store.rows("dup_fingerprint")
        fingerprint_no = f"DF-MR-{int(receipt['id']):04d}"
        row = next((r for r in rows if r.get("指纹编号") == fingerprint_no), None)
        if row is None:
            row = {"id": self._next_pk("dup_fingerprint"), "指纹编号": fingerprint_no}
            rows.append(row)

        source_content_hit = next(
            (r for r in rows
             if r.get("来源渠道") == item["source"]
             and r.get("内容指纹") == item["content_hash"]
             and r.get("关联批次") != receipt["收件编号"]),
            None,
        )
        if source_content_hit is not None:
            verdict, disposition, status = "来源内内容重复", "复用已受理回执", "确认重复"
            duplicate_of = source_content_hit.get("关联批次", "")
        elif receipt.get("同名异件") == "是":
            verdict, disposition, status = "同名异件，需独立核对", "独立核对后放行", "判定唯一"
            duplicate_of = ""
        else:
            verdict, disposition, status = "来源内唯一", "放行", "判定唯一"
            duplicate_of = ""

        row.update({
            "关联批次": receipt["收件编号"],
            "内容指纹": item["content_hash"],
            "结构指纹": item["structure_hash"],
            "命中重复批次": duplicate_of,
            "重复判定": verdict,
            "去重处置": disposition,
            "判定时间": when,
            "来源渠道": item["source"],
            "项目标识": item["item_key"],
            "清单编号": receipt["清单编号"],
            "status": status,
            "pending": False,
            "abnormal": False,
        })

    def _refresh_manifest_counts(self, manifest_no: str) -> None:
        manifest = self.get_manifest_row(manifest_no)
        if manifest is None:
            return
        receipts = [r for r in store.rows("manifest_receipt") if r.get("清单编号") == manifest_no]
        valid = [r for r in receipts if r.get("受理状态") != "待补正"]
        sources = sorted({r.get("来源渠道", "") for r in receipts if r.get("来源渠道")})
        delivered = sum(1 for r in valid if r.get("受理状态") == "已投递" or r.get("投递记录编号"))
        waiting = sum(1 for r in valid if r.get("受理状态") == "待外部确认")
        invalid = len(receipts) - len(valid)
        manifest.update({
            "来源范围": "、".join(sources),
            "项目总数": len(receipts),
            "受理数": len(valid),
            "待补正数": invalid,
            "待外部确认数": waiting,
            "已投递数": delivered,
        })
        if invalid and valid:
            manifest["status"] = "部分受理"
            manifest["pending"] = True
            manifest["abnormal"] = True
        elif invalid:
            manifest["status"] = "校验未通过"
            manifest["pending"] = True
            manifest["abnormal"] = True
        elif delivered == len(valid) and valid:
            manifest["status"] = "已核销"
            manifest["pending"] = False
            manifest["abnormal"] = False
        else:
            manifest["status"] = "已受理"
            manifest["pending"] = waiting > 0
            manifest["abnormal"] = False

    def _retry_items_from_store(
        self, manifest_no: str, receipt_ids: list[Any] | None,
    ) -> list[dict[str, Any]]:
        id_set = {str(v) for v in (receipt_ids or [])}
        rows = store.rows("manifest_receipt")
        if manifest_no:
            rows = [r for r in rows if r.get("清单编号") == manifest_no]
        if id_set:
            rows = [
                r for r in rows
                if id_set & {str(r.get("id", "")), str(r.get("受理编号", "")), str(r.get("收件编号", ""))}
            ]
        else:
            rows = [r for r in rows if r.get("受理状态") not in {"已投递"}]
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append({
                "receipt_id": row.get("id"),
                "manifest_no": row.get("清单编号"),
                "item_key": row.get("项目标识", ""),
                "file_name": row.get("原始文件名", ""),
                "source_channel": row.get("来源渠道", ""),
                "content": row.get("内容正文") or row.get("内容标签", ""),
                "declared_format": row.get("声明格式", ""),
                "receive_node": row.get("收件入口", ""),
                "row_count": row.get("结果行数", "1"),
                "target_path": row.get("目标位置", ""),
                "external_confirmation": row.get("外部确认", ""),
                "selected": True,
            })
        return items

    def continue_manifest(self, manifest_no: str, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        data = dict(payload) if isinstance(payload, dict) else {}
        data["manifest_no"] = manifest_no
        if kwargs:
            data.update(kwargs)
        return self.import_manifest(data)

    def retry_items(self, manifest_no: str, item_ids: list[Any] | None = None,
                    updates: dict[str, Any] | list[dict[str, Any]] | None = None,
                    **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"manifest_no": manifest_no}
        if updates:
            payload["items"] = updates if isinstance(updates, list) else [updates]
        if item_ids is not None:
            payload["selected"] = item_ids
        payload.update(kwargs)
        return self.import_manifest(payload)

    # ------------------------------------------------------------------
    # 外部确认、文件核对与回执
    # ------------------------------------------------------------------
    def find_receipt(self, locator: Any) -> dict[str, Any] | None:
        text_value = _text(locator)
        if isinstance(locator, int) or text_value.isdigit():
            row = store.find("manifest_receipt", int(text_value))
            if row is not None:
                return row
        for key in ("受理编号", "实际收件编号", "收件编号", "投递记录编号"):
            row = next((r for r in store.rows("manifest_receipt") if r.get(key) == text_value), None)
            if row is not None:
                return row
        return None

    def confirm_external(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        data = {**(payload if isinstance(payload, dict) else {}), **kwargs}
        receipt = self.find_receipt(
            data.get("receipt_id") or data.get("受理编号") or data.get("收件编号")
            or data.get("receive_no") or data.get("id")
        )
        content = _first(data, ["content", "内容", "content_label", "A1"])
        content_hash = _first(data, ["content_hash", "内容指纹", "内容证据"])
        source = _first(data, ["source", "来源渠道"])
        item_key = _first(data, ["item_key", "项目标识", "标识"])

        if receipt is None and (source and item_key and (content or content_hash)):
            expected_hash = content_hash or _sha(content)
            receipt = next(
                (r for r in store.rows("manifest_receipt")
                 if r.get("来源渠道") == source
                 and r.get("项目标识") == item_key
                 and r.get("内容指纹") == expected_hash),
                None,
            )
        if receipt is None:
            return {"ok": False, "message": "未找到与该受理编号或来源/标识/内容匹配的回执", "receipt": None}

        expected_hash = content_hash or (_sha(content) if content else "")
        if expected_hash and receipt.get("内容指纹") != expected_hash:
            return {
                "ok": False,
                "message": "确认内容证据与目标受理项目不一致；旧确认不能核销同名异件",
                "receipt": self.public_receipt(receipt),
            }

        if receipt.get("外部确认") == "已确认":
            return {
                "ok": True,
                "duplicate": True,
                "message": "该回执的外部确认已登记，保留原确认和实际投递回执",
                "receipt": self.public_receipt(receipt),
            }

        when = _first(data, ["confirm_time", "time", "确认时间"]) or _now()
        confirmation_no = _first(data, ["confirmation_no", "外部确认编号", "确认编号"]) or f"EXT-{receipt['id']:04d}"
        receipt["外部确认"] = "已确认"
        receipt["外部确认状态"] = "已确认"
        receipt["外部确认编号"] = confirmation_no
        receipt["确认时间"] = when
        if receipt.get("受理状态") == "待外部确认":
            receipt["受理状态"] = "可投递"
            receipt["status"] = "已受理"
            receipt["pending"] = True
        intake = next(
            (r for r in store.rows("file_intake") if r.get("批次编号") == receipt.get("收件编号")),
            None,
        )
        if intake is not None and intake.get("status") == "待外部确认":
            intake["status"] = "已接收"
            intake["pending"] = True
        self._refresh_manifest_counts(receipt["清单编号"])
        return {"ok": True, "message": f"旧外部确认 {confirmation_no} 已补到内容证据对应的受理项目",
                "receipt": self.public_receipt(receipt)}

    def file_content(self, receive_no: str) -> dict[str, Any] | None:
        intake = next(
            (r for r in store.rows("file_intake") if r.get("批次编号") == receive_no),
            None,
        )
        receipt = next(
            (r for r in store.rows("manifest_receipt") if r.get("收件编号") == receive_no),
            None,
        )
        if intake is None and receipt is None:
            return None
        content = _text((intake or {}).get("内容正文") or (receipt or {}).get("内容正文"))
        return {
            "receive_no": receive_no,
            "file_name": (intake or receipt or {}).get("原始文件名", ""),
            "source": (intake or receipt or {}).get("来源渠道", ""),
            "content": content,
            "content_hash": _sha(content) if content else (receipt or {}).get("内容指纹", ""),
            "inbox": (intake or receipt or {}).get("接收节点") or (receipt or {}).get("收件入口", ""),
        }

    @staticmethod
    def public_receipt(row: dict[str, Any]) -> dict[str, Any]:
        """返回可 JSON 化的逐项回执，并同时提供中英文键名便于接口消费。"""
        data = {key: value for key, value in row.items() if key != "id"}
        receive_no = str(row.get("实际收件编号") or row.get("收件编号") or "")
        delivery_no = str(row.get("投递记录编号") or "")
        data.update({
            "id": row.get("id"),
            "receipt_id": row.get("id"),
            "manifest_no": row.get("清单编号", ""),
            "acceptance_no": row.get("受理编号", ""),
            "item_key": row.get("项目标识", ""),
            "file_name": row.get("原始文件名", ""),
            "source": row.get("来源渠道", ""),
            "source_channel": row.get("来源渠道", ""),
            "content_hash": row.get("内容指纹") or row.get("内容证据", ""),
            "content_evidence": row.get("内容证据") or row.get("内容指纹", ""),
            "content_label": row.get("内容标签", ""),
            "content": row.get("内容正文", ""),
            "same_name_variant": row.get("同名异件", "否") == "是",
            "inbox_entry": row.get("收件入口", ""),
            "receive_no": receive_no,
            "actual_receive_no": row.get("实际收件编号", ""),
            "intake_batch": receive_no,
            "delivery_no": delivery_no,
            "result_delivery_no": delivery_no,
            "target_path": row.get("目标位置", ""),
            "acceptance_status": row.get("受理状态") or row.get("status", ""),
        })
        return data

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        receipts = store.rows("manifest_receipt")
        base.update({
            "receipt_count": len(receipts),
            "waiting_external": sum(1 for r in receipts if r.get("受理状态") == "待外部确认"),
            "delivered": sum(1 for r in receipts if r.get("投递记录编号")),
        })
        return base

    # 常见命名别名：保持与资源路由/不同测试调用习惯兼容。
    def preview_import(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.preview_manifest(payload, **kwargs)

    def batch_import(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.import_manifest(payload, **kwargs)

    def batch_register(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.import_manifest(payload, **kwargs)

    def register_source_files(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.import_manifest(payload, **kwargs)

    def retry_failed_items(self, manifest_no: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.retry_items(manifest_no, *args, **kwargs)

    def retry_unfinished(self, manifest_no: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.retry_items(manifest_no, *args, **kwargs)

    def provide_external_confirmation(self, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.confirm_external(payload, **kwargs)

    def write_off_by_source_and_content(self, **kwargs: Any) -> dict[str, Any]:
        from app.services.result_deliver import ResultDeliverService
        return ResultDeliverService().reconcile_manifest_batches(**kwargs)
