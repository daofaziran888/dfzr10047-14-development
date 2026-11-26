"""来源清单批量受理、同名异件、来源隔离与指纹核销的验收测试。"""
from __future__ import annotations

import pytest

from app.services.result_deliver import ResultDeliverService
from app.services.source_manifest import SourceManifestService
from app.store import store


@pytest.fixture
def manifest_store():
    store.reload_seed()
    yield store
    store.reload_seed()


def _first_manifest():
    return {
        "manifest_no": "SM-ACCEPT",
        "items": [
            {
                "item_key": "甲", "file_name": "甲.csv", "source_channel": "upstream-a",
                "content": "A1", "external_confirmation": "待确认", "parse_status": "已解析",
            },
            {
                "item_key": "乙", "file_name": "乙.csv", "source_channel": "",
                "content": "乙-B1",
            },
        ],
    }


def _second_manifest():
    return {
        "manifest_no": "SM-ACCEPT",
        "items": [
            {
                "item_key": "甲", "file_name": "甲.csv", "source_channel": "upstream-a",
                "content": "A2",
            },
            {
                "item_key": "乙", "file_name": "乙.csv", "source_channel": "partner-b",
                "content": "乙-B1",
            },
        ],
    }


def test_preview_marks_missing_source(manifest_store):
    svc = SourceManifestService()
    preview = svc.preview_manifest(_first_manifest())
    assert preview["invalid_items"] == 1
    yi = next(item for item in preview["items"] if item["item_key"] == "乙")
    assert "来源渠道" in yi["errors"]


def test_full_correction_confirmation_and_delivery_mapping(manifest_store):
    svc = SourceManifestService()
    first = svc.import_manifest(_first_manifest(), import_time="t1")
    statuses = {row["item_key"]: row["acceptance_status"] for row in first["receipts"]}
    assert statuses["甲"] == "待外部确认"
    assert statuses["乙"] == "待补正"

    second = svc.import_manifest(_second_manifest(), import_time="t2")
    assert len(second["receipts"]) == 3
    a1 = next(row for row in second["receipts"] if row["content_label"] == "A1")
    a2 = next(row for row in second["receipts"] if row["content_label"] == "A2")
    assert a1["receive_no"] != a2["receive_no"]
    assert a1["same_name_variant"] is True or a2["same_name_variant"] is True

    confirmed = svc.confirm_external({"receipt_id": a1["id"], "time": "t3"})
    assert confirmed["ok"] is True
    wrong_confirmation = svc.confirm_external({
        "receipt_id": a2["id"], "content": "A1", "time": "t3",
    })
    assert wrong_confirmation["ok"] is False

    report = ResultDeliverService().reconcile_manifest_batches("SM-ACCEPT", reconcile_time="t4")
    assert report["counts"]["failed"] == 0
    assert report["counts"]["delivered"] == 3
    by_content = {
        item["receipt"]["content_label"]: item["receipt"]
        for item in report["items"]
        if item["receipt"]["manifest_no"] == "SM-ACCEPT"
    }
    for label in ("A1", "A2", "乙-B1"):
        receipt = by_content[label]
        assert receipt["delivery_no"]
        assert receipt["actual_receive_no"]
        assert receipt["目标内容指纹"] == receipt["content_hash"]

    repeated = svc.import_manifest(_second_manifest(), import_time="t5")
    assert len(repeated["receipts"]) == 3
    repeat_report = ResultDeliverService().reconcile_manifest_batches(
        "SM-ACCEPT", reconcile_time="t6",
    )
    assert repeat_report["counts"]["processed"] == 0
    assert repeat_report["counts"]["skipped"] == 3


def test_different_sources_do_not_offset(manifest_store):
    svc = SourceManifestService()
    result = svc.import_manifest({"items": [
        {"item_key": "同名", "file_name": "same.csv", "source_channel": "S1", "content": "X"},
        {"item_key": "同名", "file_name": "same.csv", "source_channel": "S2", "content": "X"},
    ]})
    rows = [row for row in result["receipts"] if row["item_key"] == "同名"]
    assert len(rows) == 2
    assert len({row["source"] for row in rows}) == 2
    assert len({row["receive_no"] for row in rows}) == 2

    report = ResultDeliverService().reconcile_manifest_batches()
    delivery_rows = [
        item["receipt"] for item in report["items"]
        if item["receipt"].get("item_key") == "同名"
    ]
    assert len({row["delivery_no"] for row in delivery_rows}) == 2


def test_retry_pending_item_preserves_existing_receipt(manifest_store):
    svc = SourceManifestService()
    first = svc.import_manifest({"manifest_no": "SM-R", "items": [
        {"item_key": "乙", "content": "B"},
    ]})
    pending = first["receipts"][0]
    retried = svc.retry_items("SM-R", [pending["id"]])
    assert retried["receipts"][0]["acceptance_status"] == "待补正"

    corrected = svc.continue_manifest("SM-R", {"items": [{
        "receipt_id": pending["id"], "item_key": "乙",
        "source_channel": "partner", "content": "B",
    }]})
    receipt = corrected["receipts"][0]
    assert receipt["acceptance_status"] == "可投递"
    assert receipt["receive_no"]

    ResultDeliverService().reconcile_manifest_batches("SM-R")
    again = svc.retry_items("SM-R", [pending["id"]])
    assert again["receipts"][0]["delivery_no"]
