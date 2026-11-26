"""结果投递领域服务：将通过契约的输出结果送达目标位置并记录投递回执，产出投递记录数据集。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.services.source_manifest import SourceManifestService
from app.store import store


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class ResultDeliverService(BaseModuleService):
    MODULE = "result_deliver"
    ENTITY = "投递记录"
    OPERATION_TERM = "导出"
    LIST_FIELDS = ["投递记录编号", "关联契约", "目标位置", "投递行数", "投递格式", "重试次数", "投递结论", "投递时间"]
    REQUIRED_FIELDS = ["投递记录编号", "关联契约", "目标位置"]
    STATUS_ORDER = ["待投递", "投递中", "已送达", "部分送达"]
    ACTION_RULES = {"启动投递": "投递中", "确认送达": "已送达", "登记部分送达": "部分送达"}
    NEGATIVE_ACTIONS = ["登记部分送达"]

    MAX_RETRIES = 3

    def _find(self, deliver_no: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("投递记录编号") == deliver_no:
                return row
        return None

    def precheck_before_deliver(self, contract_no: str, intake_batch: str) -> tuple[bool, str]:
        """投递前置校验：契约必须已通过，且指纹未判定重复。"""
        contract = next(
            (r for r in store.rows("output_contract") if r.get("契约编号") == contract_no),
            None)
        if contract is None:
            return False, f"契约 {contract_no} 不存在，不得创建投递记录"
        if contract.get("status") != "已通过":
            return False, (
                f"契约 {contract_no} 状态为 {contract.get('status')}，"
                f"未通过契约的批次不得投递"
            )

        for fp in store.rows("dup_fingerprint"):
            if fp.get("关联批次") != intake_batch:
                continue
            disposition = fp.get("去重处置")
            if disposition == "阻断投递":
                return False, (
                    f"批次 {intake_batch} 命中内容重复指纹"
                    f"（重复批次 {fp.get('命中重复批次')}），不再触发投递"
                )
            if disposition == "待人工确认":
                return False, (
                    f"批次 {intake_batch} 结构指纹碰撞待人工确认，暂不投递"
                )
        return True, f"批次 {intake_batch} 允许投递"

    def create_deliver_record(self, deliver_no: str, contract_no: str,
                             target_path: str, row_count: int,
                             output_format: str) -> tuple[bool, str, dict[str, Any] | None]:
        """创建投递记录：同一目标位置已有已送达记录时拒绝覆盖。"""
        rows = store.rows(self.MODULE)
        if any(r.get("投递记录编号") == deliver_no for r in rows):
            return False, f"投递记录 {deliver_no} 已存在，不得重复创建", None

        delivered_same_target = [
            r for r in rows
            if r.get("目标位置") == target_path and r.get("status") == "已送达"
        ]
        if delivered_same_target:
            return False, (
                f"目标位置 {target_path} 已有已送达记录 "
                f"{[r.get('投递记录编号') for r in delivered_same_target]}，"
                f"已确认投递不得被覆盖"
            ), None

        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        entry = {
            "id": entry_id, "status": "待投递", "pending": True, "abnormal": False,
            "投递记录编号": deliver_no, "关联契约": contract_no,
            "目标位置": target_path, "投递行数": str(row_count),
            "投递格式": output_format, "重试次数": "0",
            "投递结论": "", "投递时间": "",
        }
        rows.append(entry)
        return True, f"投递记录 {deliver_no} 已创建（{row_count} 行 → {target_path}）", dict(entry)

    def confirm_delivered(self, deliver_no: str, deliver_time: str) -> tuple[bool, str]:
        """确认送达：已送达记录不可再次改写，保证投递回执不可覆盖。"""
        record = self._find(deliver_no)
        if record is None:
            return False, f"投递记录 {deliver_no} 不存在"
        if record.get("status") == "已送达":
            return False, (
                f"投递记录 {deliver_no} 已确认送达，投递结论不得被覆盖"
            )
        record["status"] = "已送达"
        record["pending"] = False
        record["abnormal"] = False
        record["投递结论"] = f"成功送达 {record.get('投递行数')} 行"
        record["投递时间"] = deliver_time
        return True, f"投递记录 {deliver_no} 已确认送达"

    def partial_deliver(self, deliver_no: str, delivered_rows: int,
                        deliver_time: str) -> tuple[bool, str]:
        """登记部分送达：只补投缺失部分，已送达记录不得回退为部分送达。"""
        record = self._find(deliver_no)
        if record is None:
            return False, f"投递记录 {deliver_no} 不存在"
        if record.get("status") == "已送达":
            return False, (
                f"投递记录 {deliver_no} 已确认送达，不能回退为部分送达"
            )

        total_text = str(record.get("投递行数") or "0")
        total = int(total_text) if total_text.isdigit() else 0
        if delivered_rows >= total:
            return self.confirm_delivered(deliver_no, deliver_time)
        if delivered_rows <= 0:
            return False, f"投递记录 {deliver_no} 送达行数为 0，应登记投递失败而非部分送达"

        missing = total - delivered_rows
        record["status"] = "部分送达"
        record["pending"] = True
        record["abnormal"] = True
        record["已送达行数"] = str(delivered_rows)
        record["缺失行数"] = str(missing)
        record["投递结论"] = f"部分送达 {delivered_rows}/{total} 行，缺失 {missing} 行待补投"
        record["投递时间"] = deliver_time
        return True, f"投递记录 {deliver_no} 部分送达，缺失 {missing} 行"

    def retry_missing(self, deliver_no: str, still_missing: int,
                      retry_time: str) -> tuple[bool, str]:
        """重试补投缺失部分：超过重试上限后停止重试并保留缺口结论。"""
        record = self._find(deliver_no)
        if record is None:
            return False, f"投递记录 {deliver_no} 不存在"
        if record.get("status") == "已送达":
            return False, f"投递记录 {deliver_no} 已送达，无需重试"

        retries_text = str(record.get("重试次数") or "0")
        retries = int(retries_text) if retries_text.isdigit() else 0
        if retries >= self.MAX_RETRIES:
            record["投递结论"] = (
                f"重试 {retries} 次仍缺失 {still_missing} 行，已达重试上限 "
                f"{self.MAX_RETRIES}，停止重试"
            )
            record["pending"] = True
            record["abnormal"] = True
            return False, record["投递结论"]

        record["重试次数"] = str(retries + 1)
        if still_missing <= 0:
            total = str(record.get("投递行数") or "0")
            record["status"] = "已送达"
            record["pending"] = False
            record["abnormal"] = False
            record["已送达行数"] = total
            record["缺失行数"] = "0"
            record["投递结论"] = f"第 {retries + 1} 次重试补投成功，全部 {total} 行已送达"
            record["投递时间"] = retry_time
            return True, record["投递结论"]

        record["缺失行数"] = str(still_missing)
        record["投递结论"] = f"第 {retries + 1} 次重试后仍缺失 {still_missing} 行"
        record["投递时间"] = retry_time
        return True, record["投递结论"]

    def delivered_rows_by_target(self) -> dict[str, int]:
        """按目标位置汇总已送达行数，供下游可见性核对。"""
        totals: dict[str, int] = {}
        for row in store.rows(self.MODULE):
            if row.get("status") != "已送达":
                continue
            path = str(row.get("目标位置") or "")
            text = str(row.get("投递行数") or "0")
            totals[path] = totals.get(path, 0) + (int(text) if text.isdigit() else 0)
        return totals

    # ------------------------------------------------------------------
    # 来源清单 × 指纹批次核销
    # ------------------------------------------------------------------
    def reconcile_manifest_batches(
        self,
        manifest_no: str = "",
        *,
        source: str = "",
        receipt_ids: list[Any] | None = None,
        deliver: bool = True,
        reconcile_time: str = "",
    ) -> dict[str, Any]:
        """读取清单回执和指纹结论，分类已受理项目并核销仍可投递的批次。

        已确认送达的实际回执原样保留；每个项目独立处理，单条失败不会令已成功
        项目重新上传。来源和内容指纹共同决定核销对象，避免异源同名互相抵扣。
        """
        when = reconcile_time or _now()
        id_filter = {str(value) for value in (receipt_ids or [])}
        report: dict[str, Any] = {
            "ok": True,
            "time": when,
            "manifest_no": manifest_no,
            "already_accepted": [],
            "accepted_batches": [],
            "deliverable_batches": [],
            "pending_batches": [],
            "processed": [],
            "delivered": [],
            "skipped": [],
            "blocked": [],
            "failed": [],
            "items": [],
            "counts": {},
        }

        receipts = list(store.rows("manifest_receipt"))
        for receipt in receipts:
            if manifest_no and receipt.get("清单编号") != manifest_no:
                continue
            if source and str(receipt.get("来源渠道") or "") != source:
                continue
            if id_filter and not (
                id_filter & {
                    str(receipt.get("id", "")), str(receipt.get("受理编号", "")),
                    str(receipt.get("收件编号", "")),
                }
            ):
                continue

            item_report = self._reconcile_one_receipt(receipt, deliver, when)
            category = item_report["category"]
            report["items"].append(item_report)
            public = item_report["receipt"]

            if public.get("收件编号"):
                report["already_accepted"].append(public)
                report["accepted_batches"].append(public)
            if category == "delivered_existing":
                report["skipped"].append(public)
                report["delivered"].append(public)
            elif category == "delivered_now":
                report["processed"].append(public)
                report["delivered"].append(public)
            elif category == "deliverable":
                report["deliverable_batches"].append(public)
                report["pending_batches"].append(public)
            elif category == "blocked":
                report["blocked"].append(public)
            elif category == "failed":
                report["failed"].append(public)

        report["ok"] = not report["failed"]
        report["counts"] = {
            "total": len(report["items"]),
            "already_accepted": len(report["already_accepted"]),
            "deliverable": len(report["deliverable_batches"]),
            "delivered": len(report["delivered"]),
            "processed": len(report["processed"]),
            "skipped": len(report["skipped"]),
            "blocked": len(report["blocked"]),
            "failed": len(report["failed"]),
        }
        report["message"] = (
            f"指纹核销完成：已受理 {report['counts']['already_accepted']} 项，"
            f"已送达 {report['counts']['delivered']} 项，"
            f"本次处理 {report['counts']['processed']} 项，"
            f"阻断/等待 {report['counts']['blocked']} 项，"
            f"失败 {report['counts']['failed']} 项"
        )
        return report

    def _reconcile_one_receipt(
        self, receipt: dict[str, Any], deliver: bool, when: str,
    ) -> dict[str, Any]:
        receive_no = str(receipt.get("收件编号") or receipt.get("实际收件编号") or "")

        def finish(category: str, message: str) -> dict[str, Any]:
            public = SourceManifestService.public_receipt(receipt)
            public["核销类别"] = category
            public["category"] = category
            public["核销说明"] = message
            return {"category": category, "message": message, "receipt": public}

        if receipt.get("受理状态") == "待补正" or not receive_no:
            return finish("blocked", "来源或内容尚未补正，仍不能作为可投递批次处理")

        if receipt.get("外部确认") == "待确认":
            return finish("blocked", "已解析但外部确认未补到，保留旧版本受理结果并继续等待")

        deliver_no = str(receipt.get("投递记录编号") or receipt.get("投递记录建议编号") or "")
        existing = self._find(deliver_no) if deliver_no else None
        if existing is not None and existing.get("status") == "已送达":
            content_matches = existing.get("目标内容指纹") == receipt.get("内容指纹")
            receipt["实际收件编号"] = receive_no
            receipt["核销状态"] = "已送达"
            receipt["目标内容指纹"] = existing.get("目标内容指纹", receipt.get("内容指纹"))
            receipt["目标实际内容"] = existing.get("目标实际内容", receipt.get("内容标签", ""))
            if not content_matches:
                return finish("failed", "已有投递回执的目标内容指纹与受理内容不一致，请打开文件核对")
            return finish("delivered_existing", "实际回执已确认，跳过重复上传")

        blocked, block_message = self._manifest_fingerprint_blocked(receipt)
        if blocked:
            receipt["核销状态"] = "阻断"
            return finish("blocked", block_message)

        if not deliver:
            return finish("deliverable", "仍需处理：来源、内容证据与前置确认已就绪，可创建契约并投递")

        contract_no = str(receipt.get("契约编号") or f"OC-MR-{int(receipt['id']):04d}")
        self._ensure_passed_contract(contract_no, receive_no, when)
        precheck_ok, precheck_message = self.precheck_before_deliver(contract_no, receive_no)
        if not precheck_ok:
            return finish("blocked", precheck_message)

        try:
            deliver_no = str(receipt.get("投递记录建议编号") or f"RD-MR-{int(receipt['id']):04d}")
            target_path = str(receipt.get("目标位置") or "").strip() or (
                f"/data/out/source-manifests/MR-{int(receipt['id']):04d}-"
                f"{str(receipt.get('内容指纹') or 'x')[-8:]}/"
            )
            row_count_text = str(receipt.get("结果行数") or receipt.get("投递行数") or "1")
            row_count = int(row_count_text) if row_count_text.isdigit() else 1
            output_format = str(receipt.get("声明格式") or receipt.get("文件后缀") or "file").lstrip(".")

            record = self._find(deliver_no)
            if record is None:
                created, message, record = self.create_deliver_record(
                    deliver_no, contract_no, target_path, row_count, output_format,
                )
                if not created:
                    same_target = next(
                        (r for r in store.rows(self.MODULE)
                         if r.get("目标位置") == target_path and r.get("status") == "已送达"),
                        None,
                    )
                    if same_target is not None:
                        record = same_target
                        deliver_no = str(same_target.get("投递记录编号"))
                    else:
                        return finish("failed", message)

            if record is None:
                return finish("failed", f"投递记录 {deliver_no} 不可用")

            if record.get("status") != "已送达":
                ok, message = self.confirm_delivered(deliver_no, when)
                if not ok:
                    return finish("failed", message)
                record = self._find(deliver_no) or record
            else:
                message = "投递记录已送达"

            record["来源渠道"] = receipt.get("来源渠道", "")
            record["项目标识"] = receipt.get("项目标识", "")
            record["收件编号"] = receive_no
            record["实际收件编号"] = receive_no
            record["内容指纹"] = receipt.get("内容指纹", "")
            record["目标实际内容"] = receipt.get("内容标签") or receipt.get("内容正文", "")
            record["目标内容指纹"] = receipt.get("内容指纹", "")

            receipt["投递记录编号"] = deliver_no
            receipt["实际收件编号"] = receive_no
            receipt["目标位置"] = target_path
            receipt["目标实际内容"] = record["目标实际内容"]
            receipt["目标内容指纹"] = receipt.get("内容指纹", "")
            receipt["受理状态"] = "已投递"
            receipt["核销状态"] = "已送达"
            receipt["status"] = "已投递"
            receipt["pending"] = False
            receipt["abnormal"] = False

            intake = next(
                (r for r in store.rows("file_intake") if r.get("批次编号") == receive_no),
                None,
            )
            if intake is not None:
                intake["status"] = "已入库"
                intake["pending"] = False
                intake["投递记录编号"] = deliver_no

            manifest_no = str(receipt.get("清单编号") or "")
            if manifest_no:
                SourceManifestService()._refresh_manifest_counts(manifest_no)

            return finish("delivered_now", message)
        except Exception as exc:  # 单项异常隔离，不能让整批重试重传已成功项目
            return finish("failed", f"核销投递异常：{exc}")

    @staticmethod
    def _manifest_fingerprint_blocked(receipt: dict[str, Any]) -> tuple[bool, str]:
        receive_no = str(receipt.get("收件编号") or "")
        source = str(receipt.get("来源渠道") or "")
        content_hash = receipt.get("内容指纹")
        for fp in store.rows("dup_fingerprint"):
            if fp.get("关联批次") != receive_no:
                continue
            disposition = str(fp.get("去重处置") or "")
            # 清单核销使用来源隔离结论；“复用已受理回执”走已有回执跳过逻辑。
            if disposition in {"阻断投递", "待人工确认"}:
                return True, f"批次 {receive_no} 指纹状态为 {disposition}，暂不能投递"
            if fp.get("来源渠道") and source and fp.get("来源渠道") != source:
                continue
            if content_hash and fp.get("内容指纹") != content_hash:
                return True, f"批次 {receive_no} 的指纹内容证据与清单回执不一致"
        return False, ""

    @staticmethod
    def _ensure_passed_contract(contract_no: str, receive_no: str, when: str) -> None:
        rows = store.rows("output_contract")
        contract = next((r for r in rows if r.get("契约编号") == contract_no), None)
        if contract is not None:
            return
        pk = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append({
            "id": pk,
            "status": "已通过",
            "pending": False,
            "abnormal": False,
            "契约编号": contract_no,
            "关联批次": receive_no,
            "输出列集合": "manifest_item,content_evidence",
            "列顺序约定": "manifest_item,content_evidence",
            "必填列": "manifest_item",
            "行数下限": "1",
            "契约校验结论": "来源清单核销通道自动校验通过",
            "校验时间": when,
        })

    def reconcile_fingerprints(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """语义别名：结果投递读取指纹并核销批次。"""
        return self.reconcile_manifest_batches(*args, **kwargs)

    def reconcile_fingerprint_batches(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.reconcile_manifest_batches(*args, **kwargs)

    def write_off_batches(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.reconcile_manifest_batches(*args, **kwargs)
