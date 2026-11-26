"""结果复核包领域测试：三联核对、迟到补证、复核资格与重新执行留痕。

运行：cd backend && .venv/bin/pytest tests/test_review_package.py -v
"""
from __future__ import annotations

import pytest

from app.services.review_package import (
    EVIDENCE_TABLE,
    PACKAGE_ACTIVE,
    PACKAGE_SUPERSEDED,
    PACKAGE_TABLE,
    REQUEST_OPEN,
    REQUEST_SUBMITTED,
    REQUEST_TABLE,
    REQUEST_WAITING_EVIDENCE,
    ReviewPackageService,
    normalize_version,
    param_fingerprint,
)
from app.store import store


@pytest.fixture(autouse=True)
def reset_review_tables():
    """每个用例前清空复核台账，保证用例顺序无关、结论可重复。"""
    for table in (PACKAGE_TABLE, REQUEST_TABLE, EVIDENCE_TABLE):
        store.rows(table).clear()
    yield


@pytest.fixture(scope="module")
def service():
    return ReviewPackageService()


def _registry_params(service: ReviewPackageService, version: str) -> dict[str, str]:
    row = service._registry_by_version(version)
    assert row is not None
    return {field: row.get(field, "") for field in [
        "噪声机制", "Epsilon值", "敏感度", "分布类型", "输出精度", "关联字段",
    ]}


class TestTripleBinding:
    """三联（输入/参数/费用）绑定核对。"""

    def test_query_with_direct_reference_is_eligible(self, service):
        result = service.evaluate(1)
        assert result["eligible"] is True
        assert result["checks"]["input"]["ok"] is True
        assert result["checks"]["fee"]["ok"] is True
        assert result["checks"]["params"]["ok"] is True
        assert result["checks"]["params"]["source"] == "direct"

    def test_legacy_executions_without_direct_ref_start_ineligible(self, service):
        # 两笔缺直接引用的旧执行，初始都没有可印证 v2 的证据。
        for query_id in (4, 5):
            result = service.evaluate(query_id)
            assert result["eligible"] is False
            assert result["claimed_version"] == "v2.0"
            assert result["current_effective_version"] == "v3.0"
            assert any("原执行参数证据" in reason for reason in result["reasons"])

    def test_new_param_must_not_replace_old_result(self, service):
        result = service.evaluate(5)
        # 当前只有新版 v3 配置，明确禁止把新参数写为旧结果的输入。
        assert any("新参数不得写为旧结果的输入" in reason for reason in result["reasons"])

    def test_unexecuted_query_has_no_reviewable_result(self, service):
        result = service.evaluate(2)  # 预算不足、未真正执行
        assert result["eligible"] is False
        assert any("不是成功执行" in reason for reason in result["reasons"])

        rejected = service.evaluate(3)  # 已拒绝
        assert rejected["eligible"] is False

    def test_missing_query(self, service):
        result = service.evaluate(9999)
        assert result["eligible"] is False
        assert "不存在" in result["reasons"][0]


class TestEvidenceArrival:
    """迟到参数证据的采信与归属。"""

    def test_wrong_version_evidence_is_recorded_but_not_adopted(self, service):
        service.open_request(5)
        evidence, message = service.register_evidence(
            5, "v3.0", _registry_params(service, "v3.0"), "参数轮换后的当前配置",
        )
        assert evidence["valid"] is False
        assert "不符" in evidence["match_detail"]
        # 证据留痕但资格不变，申请仍待补证。
        result = service.evaluate(5)
        assert result["eligible"] is False
        request = service.list_requests(5)[0]
        assert request["status"] == REQUEST_WAITING_EVIDENCE

    def test_tampered_snapshot_fails_fingerprint(self, service):
        params = _registry_params(service, "v2.0")
        params["Epsilon值"] = "9.9"  # 篡改参数本体
        evidence, _ = service.register_evidence(4, "v2.0", params, "来源不明的快照")
        assert evidence["valid"] is False
        assert "指纹" in evidence["match_detail"]

    def test_valid_late_evidence_attaches_to_open_request(self, service):
        request, _ = service.open_request(4)
        assert request["status"] == REQUEST_WAITING_EVIDENCE

        evidence, message = service.register_evidence(
            4, "v2.0", _registry_params(service, "v2.0"), "外部归档通道补传的原执行回执",
        )
        assert evidence["valid"] is True
        assert "独立印证成立" in evidence["match_detail"]

        # 补证归入已经打开的复核申请，不产生新待办。
        requests = service.list_requests(4)
        assert len(requests) == 1
        updated = requests[0]
        assert updated["id"] == request["id"]
        assert updated["status"] == REQUEST_OPEN
        assert updated["supplement_evidence_no"] == evidence["evidence_no"]
        assert "未产生新待办" in message

    def test_refresh_detail_reflects_late_evidence(self, service):
        package, _ = service.build_package(5)
        assert package["evaluation"]["eligible"] is False

        # DIFF-0004 的有效补证只改变 4 的资格，不影响 5。
        service.register_evidence(4, "v2.0", _registry_params(service, "v2.0"), "补传")
        refreshed_5 = service.get_package(package["id"])
        assert refreshed_5["evaluation"]["eligible"] is False

        package_4, _ = service.build_package(4)
        refreshed_4 = service.get_package(package_4["id"])
        assert refreshed_4["evaluation"]["eligible"] is True
        assert refreshed_4["evaluation"]["checks"]["params"]["source"] == "evidence"


class TestReviewSubmission:
    """复核提交：有效补证可提交，无证记录不得被签成旧结果。"""

    def test_submit_blocked_until_evidence_complete(self, service):
        request_5, _ = service.open_request(5)
        blocked, message = service.submit_request(request_5["id"])
        assert blocked["status"] == REQUEST_WAITING_EVIDENCE
        assert blocked["receipt_no"] is None
        assert "驳回" in message

    def test_full_scenario_submission_and_reexecution(self, service):
        # 两笔缺直接引用的旧执行各自开复核。
        request_4, _ = service.open_request(4)
        request_5, _ = service.open_request(5)
        assert request_4["status"] == REQUEST_WAITING_EVIDENCE
        assert request_5["status"] == REQUEST_WAITING_EVIDENCE

        # 期间只有 4 到达能独立印证 v2 的原执行回执。
        service.register_evidence(4, "v2.0", _registry_params(service, "v2.0"), "归档补传")

        # 刷新证据包详情页：4 转可复核，5 仍不可复核。
        package_4, _ = service.build_package(4)
        package_5, _ = service.build_package(5)
        assert service.get_package(package_4["id"])["evaluation"]["eligible"] is True
        assert service.get_package(package_5["id"])["evaluation"]["eligible"] is False

        # 提交已经打开的复核：4 成功且复用原申请；5 被拒签。
        submitted_4, msg_4 = service.submit_request(request_4["id"])
        assert submitted_4["status"] == REQUEST_SUBMITTED
        assert submitted_4["receipt_no"].startswith("RC-")
        assert "复核已提交" in msg_4

        rejected_5, msg_5 = service.submit_request(request_5["id"])
        assert rejected_5["status"] == REQUEST_WAITING_EVIDENCE
        assert rejected_5["receipt_no"] is None
        assert any("原执行参数证据" in reason for reason in rejected_5["block_reasons"])

        # 需要重新执行时：新包签发，原执行回执保留可查。
        new_package, re_msg = service.build_package(4, reexecute=True)
        assert new_package["reexecuted"] is True
        assert new_package["status"] == PACKAGE_ACTIVE
        assert "原执行回执保留可查" in re_msg

        old_package = service.get_package(package_4["id"])
        assert old_package["status"] == PACKAGE_SUPERSEDED
        assert old_package is not None  # 旧回执仍可查

        packages = service.list_packages(4)
        assert len(packages) == 2
        assert {p["status"] for p in packages} == {PACKAGE_ACTIVE, PACKAGE_SUPERSEDED}

    def test_submit_is_idempotent(self, service):
        request_4, _ = service.open_request(4)
        service.register_evidence(4, "v2.0", _registry_params(service, "v2.0"), "补传")
        first, _ = service.submit_request(request_4["id"])
        again, message = service.submit_request(request_4["id"])
        assert first["receipt_no"] == again["receipt_no"]
        assert "请勿重复签发" in message

    def test_reopen_after_submit_returns_same_request(self, service):
        request_4, _ = service.open_request(4)
        service.register_evidence(4, "v2.0", _registry_params(service, "v2.0"), "补传")
        service.submit_request(request_4["id"])
        reopened, message = service.open_request(4)
        assert reopened["id"] == request_4["id"]
        assert reopened["status"] == REQUEST_SUBMITTED
        assert "不重复开待办" in message
        assert len(service.list_requests(4)) == 1


class TestPackageLifecycle:
    """复核包构建幂等与重新执行规则。"""

    def test_build_package_is_idempotent(self, service):
        first, msg1 = service.build_package(4)
        second, msg2 = service.build_package(4)
        assert first["id"] == second["id"]
        assert "已存在" in msg2
        assert len(service.list_packages(4)) == 1

    def test_build_rejects_non_executed_query(self, service):
        package, message = service.build_package(3)
        assert package is None
        assert "不能构建" in message

    def test_reexecute_supersedes_and_preserves_old_receipt(self, service):
        first, _ = service.build_package(4)
        second, _ = service.build_package(4, reexecute=True)
        assert second["id"] != first["id"]
        assert service.get_package(first["id"])["status"] == PACKAGE_SUPERSEDED
        assert service.get_package(second["id"])["status"] == PACKAGE_ACTIVE


class TestFingerprint:
    """参数指纹与版本规范化。"""

    def test_version_normalization(self):
        assert normalize_version("v2") == "v2.0"
        assert normalize_version("V3.0") == "v3.0"
        assert normalize_version("") == ""

    def test_fingerprint_stable_and_sensitive(self, service):
        params = _registry_params(service, "v2.0")
        fp1 = param_fingerprint("v2.0", params)
        fp2 = param_fingerprint("v2", dict(params))
        assert fp1 == fp2
        tampered = dict(params)
        tampered["Epsilon值"] = "0.9"
        assert param_fingerprint("v2.0", tampered) != fp1

    def test_param_registry_lists_versions(self, service):
        versions = service.param_versions()
        labels = {item["version"] for item in versions}
        assert {"v1.0", "v1.1", "v2.0", "v3.0"}.issubset(labels)
        current = [item for item in versions if item["status"] == "已生效"]
        assert len(current) == 1
        assert current[0]["version"] == "v3.0"
