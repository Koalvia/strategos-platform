"""Pydantic v2 schemas for the billing (Facturación / Costes) domain.

The domain has **no database model** — billing and cost figures are aggregated
live from Business Central (the system of record) on every request, exactly like
the customers/projects directories.

Amounts are in local currency (EUR) as plain floats, rounded to two decimals by
the service. Two views:

* per **customer**: net billing (invoices minus credit-memo *facturas
  rectificativas*);
* per **project**: net billing attributable to the project, its usage cost, and
  the hours logged against it.
"""

from pydantic import BaseModel


class CustomerBillingResponse(BaseModel):
    """Net billing for one customer (invoices minus credit memos)."""

    customer_id: str
    customer_name: str
    net_billed: float


class ProjectBillingResponse(BaseModel):
    """Billing, cost and logged hours for one project.

    ``billed`` is net billing (invoices minus credit memos) on lines tagged with
    this project; ``cost`` is the sum of ``jobLedgerEntries`` *usage* cost;
    ``hours`` is the sum of ``timeSheetPostingEntries`` quantity.
    """

    project_id: str
    project_name: str
    billed: float
    cost: float
    hours: float


class CustomerBillingGroupResponse(BaseModel):
    """One customer with its per-project billing nested underneath.

    A hierarchical view that folds the per-customer and per-project breakdowns
    into a single accordion-friendly shape: the customer is the parent row and
    ``projects`` are the child rows.

    ``net_billed`` is the authoritative per-customer net billing (invoices minus
    credit memos, attributed through the sales-document header — the same figure
    :class:`CustomerBillingResponse` carries). ``cost`` and ``hours`` are rolled
    up from ``projects`` (usage cost / logged hours), so they cover only work
    tagged to one of the customer's projects. ``net_billed`` therefore need not
    equal the sum of the children's ``billed`` — non-project invoice lines count
    toward the customer total but sit under no project.
    """

    customer_id: str
    customer_name: str
    net_billed: float
    cost: float
    hours: float
    projects: list[ProjectBillingResponse]
