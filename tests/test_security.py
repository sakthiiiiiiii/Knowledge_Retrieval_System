# Test denied cases as well as allowed cases so missing or changed permissions cannot
# silently broaden access.

import pytest
from dataclasses import replace
from hr_rag.models import Principal, Block
from hr_rag.security import allowed, AccessDenied, authenticate
from hr_rag.policy import classify
from hr_rag.cache import cache_key
from hr_rag.config import Settings


def test_tenant_and_unknown_scopes_fail_closed():
    alice = Principal("a", "org1", groups=("hr",), teams=("Payments Platform",))
    assert not allowed(alice, {"tenant_id": "org2", "access_scopes": ["internal"]})
    assert not allowed(alice, {"tenant_id": "org1", "access_scopes": []})
    assert allowed(alice, {"tenant_id": "org1", "access_scopes": ["group:hr"]})
    assert not allowed(
        Principal("unsigned-role", "org1"),
        {"tenant_id": "org1", "access_scopes": ["internal"]},
    )
    assert not allowed(alice, {"tenant_id": "org1", "access_scopes": ["group:oncall"]})


def test_training_row_access_and_denial():
    blocks = [
        Block(
            "Employee ID: E1001",
            metadata={"sheet": "Employees"},
            employee_id="E1001",
            team="Payments Platform",
        ),
        Block(
            "Training for E1001", metadata={"sheet": "Training"}, employee_id="E1001"
        ),
        Block("All employees: 12", metadata={"sheet": "Summary"}),
    ]
    policy = {"employee_row_scopes": True, "scope": ["group:hr", "group:ld"]}
    classify(blocks, policy)
    p = {"tenant_id": "swiftpay", "access_scopes": list(blocks[1].scope)}
    assert allowed(Principal("manager", "swiftpay", teams=("Payments Platform",)), p)
    assert not allowed(Principal("other-manager", "swiftpay", teams=("Identity",)), p)
    assert allowed(Principal("hr", "swiftpay", groups=("hr",)), p)
    assert not allowed(Principal("employee", "swiftpay", employee_id="E1001"), p)
    assert blocks[2].scope == ()


def test_appendix_b_is_not_inherited_from_report():
    policy = {
        "scope": ["group:ops-report"],
        "classification": "confidential",
        "appendix_b_scope": ["group:oncall"],
        "appendix_b_classification": "restricted",
    }
    blocks = [
        Block("Availability 99.94%", heading="4. Key performance indicators"),
        Block("Appendix B. On-call roster", heading="Appendix B. On-call roster"),
    ]
    classify(blocks, policy)
    assert blocks[0].scope == ("group:ops-report",)
    assert blocks[1].scope == ("group:oncall",)


def test_cache_isolated_by_user_acl_revision_namespace_and_version():
    s = Settings()
    a = Principal("hr-user", "swiftpay", groups=("hr",), acl_revision="A")
    b = Principal("employee", "swiftpay", acl_revision="A")
    arg = ("hr", "How many leave days?", [], s)
    assert cache_key(a, *arg, 1) != cache_key(b, *arg, 1)
    assert cache_key(a, *arg, 1) != cache_key(replace(a, acl_revision="B"), *arg, 1)
    assert cache_key(a, *arg, 1) != cache_key(a, *arg, 2)
    assert cache_key(a, "hr", "How many leave days?", [], s, 1) != cache_key(
        a, "operations", "How many leave days?", [], s, 1
    )


def test_auth_disabled_fail_closed():
    with pytest.raises(AccessDenied):
        authenticate("fake", Settings())
