"""Tests for the customer visibility scope (``app.core.visibility``).

The scope answers one question — which customers may this caller see — and every
screen (Clientes, Proyectos, Dashboard, Usuarios) derives its answer from it.

Against the mock fixtures: RES-01 (marc@) is the manager, RES-02 (jordi@) is assigned
cust-001 and cust-002, RES-03 (laura@) has cust-003, and RES-04 (anna@) has none.

Only ``manageAllCustomers`` grants everything; everyone else — including an account
Business Central does not know — is limited to their own assignments.
"""

import pytest

from app.core.visibility import resolve_customer_scope
from app.domains.auth.models import User
from app.integrations.business_central.mock_client import MockBusinessCentralClient
from app.integrations.business_central.models import BCCustomerResource, BCResource


def _user(email: str) -> User:
    """A throwaway (unsaved) user — the resolver only reads ``email``."""
    return User(name="Test", email=email, hashed_password="not-a-real-hash")


@pytest.fixture
def bc():
    return MockBusinessCentralClient()


@pytest.mark.unit
def test_manager_sees_every_customer(bc):
    """A resource with manageAllCustomers is unrestricted."""
    scope = resolve_customer_scope(_user("marc@estrategos.ad"), bc)
    assert scope.customer_ids is None
    assert scope.sees_everything
    assert scope.reason == "manager"


@pytest.mark.unit
def test_assigned_user_sees_only_their_customers(bc):
    """A non-manager resource is limited to its customersResources rows."""
    scope = resolve_customer_scope(_user("jordi@estrategos.ad"), bc)
    assert scope.customer_ids == ("cust-001", "cust-002")
    assert not scope.sees_everything
    assert scope.reason == "assignments"


@pytest.mark.unit
def test_email_match_is_case_insensitive(bc):
    """Logging in with a differently-cased email resolves to the same resource."""
    scope = resolve_customer_scope(_user("JORDI@ESTRATEGOS.AD"), bc)
    assert scope.customer_ids == ("cust-001", "cust-002")


@pytest.mark.unit
def test_resource_without_assignments_sees_nothing(bc):
    """Resolving with zero assignments is an empty scope, not an unrestricted one."""
    scope = resolve_customer_scope(_user("anna@estrategos.ad"), bc)
    assert scope.customer_ids == ()
    assert not scope.sees_everything
    assert scope.reason == "assignments"


@pytest.mark.unit
def test_unlinked_user_sees_nothing(bc):
    """No BC resource carries this email, so the caller gets no customers.

    Restrictive by default: being unknown to Business Central is not a licence to
    see the whole company.
    """
    scope = resolve_customer_scope(_user("nobody@example.com"), bc)
    assert scope.customer_ids == ()
    assert not scope.sees_everything
    assert scope.reason == "unlinked"


@pytest.mark.unit
def test_blank_email_does_not_match_a_blank_resource_email():
    """A resource with no email must never swallow an account with no email."""

    class _BlankEmailBC(MockBusinessCentralClient):
        def get_resources(self):
            return [BCResource(id="E0001", name="Nobody", email="")]

    scope = resolve_customer_scope(_user(""), _BlankEmailBC())
    assert scope.reason == "unlinked"
    assert scope.customer_ids == ()


@pytest.mark.unit
def test_several_resources_union_their_customers():
    """One person can hold two resource cards; their customers add up."""

    class _TwoCardsBC(MockBusinessCentralClient):
        def get_resources(self):
            return [
                BCResource(id="E0018", name="Fatima", email="f@x.ad"),
                BCResource(id="E0027", name="Fatima (2)", email="f@x.ad"),
            ]

        def get_customer_resources(self):
            return [
                BCCustomerResource(customer_id="C1", resource_id="E0018"),
                BCCustomerResource(customer_id="C2", resource_id="E0027"),
            ]

    scope = resolve_customer_scope(_user("f@x.ad"), _TwoCardsBC())
    assert scope.customer_ids == ("C1", "C2")


@pytest.mark.unit
def test_manager_on_any_card_wins():
    """Holding one privileged card is enough, whichever card it is."""

    class _MixedCardsBC(MockBusinessCentralClient):
        def get_resources(self):
            return [
                BCResource(id="E1", name="X", email="x@x.ad"),
                BCResource(id="E2", name="X", email="x@x.ad", manage_all_customers=True),
            ]

    scope = resolve_customer_scope(_user("x@x.ad"), _MixedCardsBC())
    assert scope.sees_everything
    assert scope.reason == "manager"


@pytest.mark.unit
def test_bc_outage_restricts_the_scope_to_empty():
    """``customersResources`` degrades to ``[]`` on failure, which hides everything.

    Fail-closed, and deliberately so: the resolver cannot tell an outage from "no
    assignments", so it restricts rather than opens. The live client logs the failure
    because on screen the two are indistinguishable.
    """

    class _NoAssignmentsBC(MockBusinessCentralClient):
        def get_customer_resources(self):
            return []

    scope = resolve_customer_scope(_user("jordi@estrategos.ad"), _NoAssignmentsBC())
    assert scope.customer_ids == ()
    assert not scope.sees_everything
