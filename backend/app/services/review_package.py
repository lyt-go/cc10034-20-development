"""结果复核包领域服务。

噪声引擎只维护参数配置，差分查询执行后缺少"把当时证据重新拿回来"的能力。
本服务围绕一次差分查询执行构建结果复核包，把同一笔实际执行的
结果（输入/输出）、参数（配置版本与指纹）、费用（Epsilon 与费用回执）
三联绑定，并管理迟到的原执行参数证据与复核申请：

- 包内只锁定执行当时声明的参数版本，参数轮换后绝不拿当前新参数顶替旧结果；
- 旧执行丢失直接配置引用时，只接受能独立印证该版本的原执行参数证据；
- 重新执行会签发新复核包，原执行回执标记为"已替代"但仍可查；
- 只有原输入、参数、费用三联互相核对通过，复核申请才允许提交；
- 迟到的有效补证会落到已经打开的复核申请上，不产生新的待办。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.store import store

QUERY_MODULE = "differential_sql"
NOISE_MODULE = "noise_engine"
PACKAGE_TABLE = "review_package"
REQUEST_TABLE = "review_request"
EVIDENCE_TABLE = "param_evidence"

# 参与参数指纹的字段：指纹只由参数本体决定，与状态、生效时间等台账信息无关。
FINGERPRINT_FIELDS = ["噪声机制", "Epsilon值", "敏感度", "分布类型", "输出精度", "关联字段"]

PACKAGE_ACTIVE = "有效"
PACKAGE_SUPERSEDED = "已替代"
REQUEST_WAITING_EVIDENCE = "待补证"
REQUEST_OPEN = "待提交"
REQUEST_SUBMITTED = "已提交"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_version(version: str | None) -> str:
    """把 v2 / V2 统一成 v2.0，便于版本对账；空值原样返回空串。"""
    text = str(version or "").strip()
    if not text:
        return ""
    text = text.lower()
    if text.count(".") == 0:
        text = f"{text}.0"
    return text


def parse_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def param_fingerprint(version: str, params: dict[str, Any]) -> str:
    """按参数版本 + 参数本体计算稳定指纹，用于独立印证。"""
    basis = "|".join(str(params.get(field, "")).strip() for field in FINGERPRINT_FIELDS)
    digest = hashlib.sha256(f"{normalize_version(version)}:{basis}".encode("utf-8")).hexdigest()[:12]
    return f"fp:{normalize_version(version)}:{digest}"


class ReviewPackageService:
    """结果复核包、参数证据与复核申请的全部业务判断都收敛在本服务。"""

    # ————————————————————————————————————
    # 基础读取
    # ————————————————————————————————————
    def _table(self, name: str) -> list[dict[str, Any]]:
        return store.rows(name)

    def _find_query(self, query_id: int) -> dict[str, Any] | None:
        return store.find(QUERY_MODULE, query_id)

    def param_versions(self) -> list[dict[str, Any]]:
        """参数台账：列出全部配置版本及指纹，供操作员选择/比对。"""
        result: list[dict[str, Any]] = []
        for row in store.rows(NOISE_MODULE):
            version = normalize_version(row.get("配置版本"))
            result.append({
                "config_id": row.get("配置编号"),
                "version": version,
                "status": row.get("status"),
                "fingerprint": param_fingerprint(version, row),
                "params": {field: row.get(field, "") for field in FINGERPRINT_FIELDS},
            })
        return result

    def _registry_by_version(self, version: str) -> dict[str, Any] | None:
        target = normalize_version(version)
        for row in store.rows(NOISE_MODULE):
            if normalize_version(row.get("配置版本")) == target:
                return row
        return None

    def _current_effective_version(self) -> str:
        for row in store.rows(NOISE_MODULE):
            if row.get("status") == "已生效":
                return normalize_version(row.get("配置版本"))
        return ""

    def _valid_evidence(self, query_id: int) -> list[dict[str, Any]]:
        return [
            row for row in self._table(EVIDENCE_TABLE)
            if int(row.get("query_id", 0)) == query_id and row.get("valid") is True
        ]

    # ————————————————————————————————————
    # 三联核对：输入 / 费用 / 参数
    # ————————————————————————————————————
    def _check_input(self, row: dict[str, Any]) -> tuple[bool, str]:
        if row.get("status") != "已执行":
            return False, f"查询状态为「{row.get('status')}」，不是成功执行，无结果可复核"
        if not str(row.get("查询语句", "")).strip():
            return False, "原查询语句缺失，无法核对原输入"
        injection = str(row.get("噪声注入量", ""))
        if not injection or "未执行" in injection or "被拒绝" in injection:
            return False, "噪声注入量缺失或该执行未真正注入噪声"
        row_count = parse_number(row.get("返回行数"))
        if row_count is None or row_count < 1:
            return False, "返回行数缺失或为0，缺少可复核的结果输出"
        return True, f"原输入与结果输出一致（返回{row.get('返回行数')}行）"

    def _check_fee(self, row: dict[str, Any]) -> tuple[bool, str]:
        epsilon = parse_number(row.get("消耗Epsilon"))
        if epsilon is None or epsilon <= 0:
            return False, "消耗Epsilon缺失或非正数，费用无法核对"
        if not str(row.get("费用回执", "")).strip():
            return False, "缺少当时执行签发的费用回执"
        budget_left = str(row.get("预算剩余", "")).strip()
        if not budget_left or budget_left.upper() == "N/A":
            return False, "预算剩余记录缺失，费用与预算无法对应"
        return True, f"费用回执{row.get('费用回执')}与消耗{epsilon}Epsilon对应"

    def _check_params(self, row: dict[str, Any]) -> tuple[bool, str, str, str]:
        """返回 (是否通过, 说明, 参数来源, 指纹)。来源：direct/evidence/none。"""
        claimed = normalize_version(row.get("参数版本"))
        if not claimed:
            return False, "执行记录未声明参数版本，参数链断裂", "none", ""
        registry = self._registry_by_version(claimed)
        if registry is None:
            return False, f"参数版本{claimed}在噪声配置台账中无登记，无法核对", "none", ""
        canonical_fp = param_fingerprint(claimed, registry)
        current = self._current_effective_version()

        direct_ref = str(row.get("配置引用", "")).strip()
        if direct_ref:
            if str(registry.get("配置编号")) != direct_ref:
                return (
                    False,
                    f"直接配置引用{direct_ref}与执行声明的参数版本{claimed}不一致，拒绝以错版参数入包",
                    "none",
                    canonical_fp,
                )
            note = f"直接配置引用{direct_ref}印证参数版本{claimed}"
            if current and current != claimed:
                note += f"；当前生效版本已轮换为{current}，本包仍锁定{claimed}"
            return True, note, "direct", canonical_fp

        evidence_rows = [
            ev for ev in self._valid_evidence(int(row["id"]))
            if normalize_version(ev.get("param_version")) == claimed
            and ev.get("fingerprint") == canonical_fp
        ]
        if evidence_rows:
            latest = evidence_rows[-1]
            note = f"原执行参数证据{latest.get('evidence_no')}独立印证参数版本{claimed}"
            if current and current != claimed:
                note += f"；当前生效版本已轮换为{current}，证据仅印证旧版{claimed}，不以新参数顶替"
            return True, note, "evidence", canonical_fp

        if current and current != claimed:
            return (
                False,
                f"直接配置引用已丢失，且无印证{claimed}的原执行参数证据；当前仅能取到新版{current}，"
                "新参数不得写为旧结果的输入",
                "none",
                canonical_fp,
            )
        return (
            False,
            f"直接配置引用已丢失，且缺少能独立印证参数版本{claimed}的原执行参数证据",
            "none",
            canonical_fp,
        )

    def evaluate(self, query_id: int) -> dict[str, Any]:
        """对一次执行做三联核对，输出可复核性结论与逐项原因。"""
        row = self._find_query(query_id)
        if row is None:
            return {
                "query_id": query_id,
                "eligible": False,
                "reasons": [f"查询记录 {query_id} 不存在或已归档"],
                "checks": {},
                "claimed_version": "",
                "current_effective_version": self._current_effective_version(),
            }
        input_ok, input_detail = self._check_input(row)
        fee_ok, fee_detail = self._check_fee(row)
        param_ok, param_detail, param_source, fingerprint = self._check_params(row)
        reasons: list[str] = []
        if not input_ok:
            reasons.append(f"输入/结果：{input_detail}")
        if not fee_ok:
            reasons.append(f"费用：{fee_detail}")
        if not param_ok:
            reasons.append(f"参数：{param_detail}")
        return {
            "query_id": query_id,
            "query_no": row.get("查询编号"),
            "eligible": input_ok and fee_ok and param_ok,
            "reasons": reasons,
            "checks": {
                "input": {"ok": input_ok, "detail": input_detail},
                "fee": {"ok": fee_ok, "detail": fee_detail},
                "params": {"ok": param_ok, "detail": param_detail, "source": param_source},
            },
            "claimed_version": normalize_version(row.get("参数版本")),
            "locked_fingerprint": fingerprint,
            "current_effective_version": self._current_effective_version(),
        }

    # ————————————————————————————————————
    # 复核包构建与重新执行
    # ————————————————————————————————————
    def _active_package(self, query_id: int) -> dict[str, Any] | None:
        for package in self._table(PACKAGE_TABLE):
            if int(package.get("query_id", 0)) == query_id and package.get("status") == PACKAGE_ACTIVE:
                return package
        return None

    def _next_receipt(self, prefix: str, table: str, field: str) -> str:
        seq = len(self._table(table)) + 1
        return f"{prefix}-{seq:04d}"

    def _snapshot(self, row: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": dict(row),
            "evaluation": dict(evaluation),
            "captured_at": _now(),
        }

    def build_package(self, query_id: int, *, reexecute: bool = False) -> tuple[dict[str, Any] | None, str]:
        row = self._find_query(query_id)
        if row is None:
            return None, f"查询记录 {query_id} 不存在或已归档"
        if row.get("status") != "已执行":
            return None, f"查询{row.get('查询编号')}状态为「{row.get('status')}」，未成功执行，不能构建结果复核包"

        existing = self._active_package(query_id)
        if existing is not None and not reexecute:
            # 幂等返回同一有效包，但核对结论按当前证据重新计算（迟到证据需可见）。
            existing["evaluation"] = self.evaluate(query_id)
            existing["snapshot"]["evaluation"] = existing["evaluation"]
            return existing, "复核包已存在，返回当前有效回执"

        if reexecute and existing is not None:
            # 参数轮换后重新执行：旧包原样保留为已替代，原执行回执仍可查。
            existing["status"] = PACKAGE_SUPERSEDED
            existing["superseded_at"] = _now()

        evaluation = self.evaluate(query_id)
        package = {
            "id": max((int(r.get("id", 0)) for r in self._table(PACKAGE_TABLE)), default=0) + 1,
            "receipt_no": self._next_receipt("RP", PACKAGE_TABLE, "receipt_no"),
            "query_id": query_id,
            "query_no": row.get("查询编号"),
            "status": PACKAGE_ACTIVE,
            "reexecuted": reexecute,
            "created_at": _now(),
            "snapshot": self._snapshot(row, evaluation),
            "evaluation": evaluation,
        }
        self._table(PACKAGE_TABLE).append(package)
        message = "重新执行已签发新复核包，原执行回执保留可查" if reexecute else "结果复核包已构建"
        return package, message

    def list_packages(self, query_id: int | None = None) -> list[dict[str, Any]]:
        rows = self._table(PACKAGE_TABLE)
        if query_id is not None:
            rows = [r for r in rows if int(r.get("query_id", 0)) == query_id]
        return sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)

    def get_package(self, package_id: int) -> dict[str, Any] | None:
        package = next(
            (r for r in self._table(PACKAGE_TABLE) if int(r.get("id", 0)) == package_id),
            None,
        )
        if package is None:
            return None
        # 详情页刷新：有效包实时重算核对结论，让迟到补证立刻反映到资格上；
        # 已替代的包冻结构建时快照，只补充当前结论作参考。
        if package.get("status") == PACKAGE_ACTIVE:
            evaluation = self.evaluate(int(package["query_id"]))
            package["evaluation"] = evaluation
            package["snapshot"]["evaluation"] = evaluation
        else:
            package["latest_evaluation"] = self.evaluate(int(package["query_id"]))
        package["evidence"] = self.list_evidence(int(package["query_id"]))
        package["requests"] = self.list_requests(int(package["query_id"]))
        return package

    # ————————————————————————————————————
    # 迟到的原执行参数证据
    # ————————————————————————————————————
    def register_evidence(
        self,
        query_id: int,
        param_version: str,
        snapshot: dict[str, Any],
        source: str,
        evidence_no: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        row = self._find_query(query_id)
        if row is None:
            return None, f"查询记录 {query_id} 不存在或已归档"
        claimed = normalize_version(row.get("参数版本"))
        incoming = normalize_version(param_version)
        registry = self._registry_by_version(incoming)

        valid = True
        match_detail = ""
        fingerprint = ""
        if not claimed:
            valid = False
            match_detail = "执行记录未声明参数版本，证据无法挂靠"
        elif incoming != claimed:
            valid = False
            match_detail = (
                f"证据参数版本{incoming}与该执行声明的{claimed}不符，"
                "参数已轮换，新参数证据不得写为旧结果的输入"
            )
        elif registry is None:
            valid = False
            match_detail = f"参数版本{incoming}在噪声配置台账中无登记，无法独立印证"
        else:
            fingerprint = param_fingerprint(incoming, snapshot)
            canonical_fp = param_fingerprint(incoming, registry)
            if fingerprint != canonical_fp:
                valid = False
                match_detail = (
                    f"证据参数指纹{fingerprint}与台账版本{incoming}规范指纹{canonical_fp}不一致，"
                    "不能独立印证原执行参数"
                )
            else:
                match_detail = f"证据指纹与台账版本{incoming}规范指纹一致，独立印证成立"

        evidence = {
            "id": max((int(r.get("id", 0)) for r in self._table(EVIDENCE_TABLE)), default=0) + 1,
            "evidence_no": evidence_no or self._next_receipt("EV", EVIDENCE_TABLE, "evidence_no"),
            "query_id": query_id,
            "query_no": row.get("查询编号"),
            "param_version": incoming,
            "source": source or "外部补证通道",
            "fingerprint": fingerprint,
            "valid": valid,
            "match_detail": match_detail,
            "snapshot": dict(snapshot),
            "received_at": _now(),
        }
        self._table(EVIDENCE_TABLE).append(evidence)
        if not valid:
            return evidence, f"证据已登记但不可采信：{match_detail}"

        # 有效补证落到该执行已经打开、尚未提交的复核申请上，不新增待办。
        affected: list[int] = []
        for request in self._table(REQUEST_TABLE):
            if (
                int(request.get("query_id", 0)) == query_id
                and request.get("status") == REQUEST_WAITING_EVIDENCE
            ):
                request["status"] = REQUEST_OPEN
                request["evidence_supplemented_at"] = _now()
                request["supplement_evidence_no"] = evidence["evidence_no"]
                affected.append(int(request["id"]))
        if affected:
            return evidence, f"补证有效，已归入复核申请{affected}，未产生新待办"
        return evidence, "补证有效，已归入该执行的证据包"

    def list_evidence(self, query_id: int | None = None) -> list[dict[str, Any]]:
        rows = self._table(EVIDENCE_TABLE)
        if query_id is not None:
            rows = [r for r in rows if int(r.get("query_id", 0)) == query_id]
        return sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)

    # ————————————————————————————————————
    # 复核申请（待办）
    # ————————————————————————————————————
    def open_request(self, query_id: int) -> tuple[dict[str, Any] | None, str]:
        row = self._find_query(query_id)
        if row is None:
            return None, f"查询记录 {query_id} 不存在或已归档"
        existing = self.list_requests(query_id)
        # 同一执行只允许一笔复核申请：已提交的直接返回原回执，未提交的返回原待办，
        # 重复打开不产生新待办；补证是否改变资格由刷新时的三联核对给出。
        if existing:
            request = existing[0]
            evaluation = self.evaluate(query_id)
            request["latest_evaluation"] = evaluation
            if request.get("status") == REQUEST_SUBMITTED:
                return request, f"该执行复核已提交（回执{request.get('receipt_no')}），不重复开待办"
            return request, "复核申请已打开，返回现有待办"

        evaluation = self.evaluate(query_id)
        status = REQUEST_OPEN if evaluation["eligible"] else REQUEST_WAITING_EVIDENCE
        request = {
            "id": max((int(r.get("id", 0)) for r in self._table(REQUEST_TABLE)), default=0) + 1,
            "request_no": self._next_receipt("RR", REQUEST_TABLE, "request_no"),
            "query_id": query_id,
            "query_no": row.get("查询编号"),
            "status": status,
            "opened_at": _now(),
            "submitted_at": None,
            "receipt_no": None,
            "block_reasons": [] if evaluation["eligible"] else evaluation["reasons"],
            "latest_evaluation": evaluation,
        }
        self._table(REQUEST_TABLE).append(request)
        if evaluation["eligible"]:
            return request, "复核申请已打开，三联核对通过，可提交复核"
        return request, "复核申请已打开但暂不可复核：" + "；".join(evaluation["reasons"])

    def submit_request(self, request_id: int) -> tuple[dict[str, Any] | None, str]:
        request = next(
            (r for r in self._table(REQUEST_TABLE) if int(r.get("id", 0)) == request_id),
            None,
        )
        if request is None:
            return None, f"复核申请 {request_id} 不存在"
        if request.get("status") == REQUEST_SUBMITTED:
            return request, "该复核已提交，请勿重复签发"

        evaluation = self.evaluate(int(request["query_id"]))
        request["latest_evaluation"] = evaluation
        if not evaluation["eligible"]:
            # 无证记录不得被签成旧结果：保持待补证，不允许提交。
            request["status"] = REQUEST_WAITING_EVIDENCE
            request["block_reasons"] = evaluation["reasons"]
            return request, "复核提交被驳回：" + "；".join(evaluation["reasons"])

        request["status"] = REQUEST_SUBMITTED
        request["submitted_at"] = _now()
        request["block_reasons"] = []
        request["receipt_no"] = f"RC-{int(request['id']):04d}"
        return request, f"复核已提交，证据回执编号{request['receipt_no']}"

    def list_requests(self, query_id: int | None = None) -> list[dict[str, Any]]:
        rows = self._table(REQUEST_TABLE)
        if query_id is not None:
            rows = [r for r in rows if int(r.get("query_id", 0)) == query_id]
        return sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)


service = ReviewPackageService()


def _seed_legacy_evidence() -> None:
    """为保留直接引用的历史执行 DIFF-0001 预置一条当时签发的参数证据。

    指纹由本服务统一算法现场计算，避免在种子数据里硬编码哈希。
    两笔缺直接引用的旧执行（DIFF-0004/0005）不在此预置，留给复核流程演示。
    """
    table = store.rows(EVIDENCE_TABLE)
    if table:
        return
    query = store.find(QUERY_MODULE, 1)
    if query is None:
        return
    version = normalize_version(query.get("参数版本"))
    registry = service._registry_by_version(version)
    if registry is None:
        return
    table.append({
        "id": 1,
        "evidence_no": "EV-0001",
        "query_id": 1,
        "query_no": query.get("查询编号"),
        "param_version": version,
        "source": "执行时刻随单签发",
        "fingerprint": param_fingerprint(version, registry),
        "valid": True,
        "match_detail": f"执行时刻随单证据，印证参数版本{version}",
        "snapshot": {field: registry.get(field, "") for field in FINGERPRINT_FIELDS},
        "received_at": "2026-10-01T10:31:00",
    })


_seed_legacy_evidence()
