"""Generated Context Surface models for the Data Assistant domain."""

from __future__ import annotations

from typing import Any

from context_surfaces.context_model import ContextField, ContextModel, ContextRelationship


class Employee(ContextModel):
    """Employee entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_employee:{id}"

    id: str = ContextField(
        description="Employee ID",
        is_key_component=True,
    )

    name: str = ContextField(
        description="Full name",
        index="text",
        weight=2.0,
    )

    email: str = ContextField(
        description="Email",
        index="text",
        no_stem=True,
    )

    role: str = ContextField(
        description="Job role",
        index="text",
    )

    team: str = ContextField(
        description="Team",
        index="text",
    )

    division: str = ContextField(
        description="Division: analytics, ratings, commodities, index_research",
        index="tag",
    )

    clearance: str = ContextField(
        description="Data clearance: standard, confidential, restricted",
        index="tag",
    )

    region: str = ContextField(
        description="Region",
        index="tag",
    )


class DataProduct(ContextModel):
    """DataProduct entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_dataproduct:{id}"

    id: str = ContextField(
        description="Data product ID",
        is_key_component=True,
    )

    name: str = ContextField(
        description="Data product name",
        index="text",
        weight=2.0,
    )

    division: str = ContextField(
        description="Owning division: analytics, ratings, commodities, index_research",
        index="tag",
    )

    owner_team: str = ContextField(
        description="Owning team",
        index="text",
    )

    steward: str = ContextField(
        description="Data steward",
        index="text",
    )

    description: str = ContextField(
        description="What the data product contains and who uses it",
        index="text",
    )

    classification: str = ContextField(
        description="Classification: internal, confidential, restricted",
        index="tag",
    )

    refresh: str = ContextField(
        description="Refresh frequency: real_time, daily, weekly, monthly",
        index="tag",
    )

    quality_score: str = ContextField(
        description="Data quality score out of 100",
        index="tag",
    )

    status: str = ContextField(
        description="Status: active, beta, deprecated",
        index="tag",
    )

    access_policy: str = ContextField(
        description="Access policy: self_serve, approval_required",
        index="tag",
    )

    replacement_id: str = ContextField(
        description="Replacement data product if deprecated",
        index="tag",
    )

    replacement: Any = ContextRelationship(
        description="Product that replaces this one",
        target="DataProduct",
        source_field="replacement_id",
    )


class AccessRequest(ContextModel):
    """AccessRequest entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_accessrequest:{id}"

    id: str = ContextField(
        description="Request ID",
        is_key_component=True,
    )

    user_id: str = ContextField(
        description="Requesting employee",
        index="tag",
    )

    data_product_id: str = ContextField(
        description="Requested data product ID, like DP-01",
        index="tag",
    )

    data_product_name: str = ContextField(
        description="Requested data product name, like Company Fundamentals",
        index="tag",
    )

    requested_date: str = ContextField(
        description="Date requested (YYYY-MM-DD)",
        index="tag",
    )

    status: str = ContextField(
        description="Status: approved, pending, denied, expired",
        index="tag",
    )

    approved_until: str = ContextField(
        description="Access end date (YYYY-MM-DD) when approved",
        index="tag",
    )

    justification: str = ContextField(
        description="Business justification",
        index="text",
    )

    approver: str = ContextField(
        description="Approver or steward",
        index="text",
    )

    notes: str = ContextField(
        description="Decision notes",
        index="text",
    )

    user: Any = ContextRelationship(
        description="Requesting employee",
        target="Employee",
        source_field="user_id",
    )

    data_product: Any = ContextRelationship(
        description="Requested data product",
        target="DataProduct",
        source_field="data_product_id",
    )


class QualityIncident(ContextModel):
    """QualityIncident entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_incident:{id}"

    id: str = ContextField(
        description="Incident ID",
        is_key_component=True,
    )

    data_product_id: str = ContextField(
        description="Affected data product ID, like DP-01",
        index="tag",
    )

    data_product_name: str = ContextField(
        description="Affected data product name, like Company Fundamentals",
        index="tag",
    )

    opened_date: str = ContextField(
        description="Date opened (YYYY-MM-DD)",
        index="tag",
    )

    severity: str = ContextField(
        description="Severity: sev1, sev2, sev3",
        index="tag",
    )

    status: str = ContextField(
        description="Status: open, mitigated, resolved",
        index="tag",
    )

    summary: str = ContextField(
        description="What went wrong",
        index="text",
        weight=2.0,
    )

    impact: str = ContextField(
        description="Who and what is affected",
        index="text",
    )

    resolution: str = ContextField(
        description="Resolution or workaround",
        index="text",
    )

    data_product: Any = ContextRelationship(
        description="Affected data product",
        target="DataProduct",
        source_field="data_product_id",
    )


class SupportInteraction(ContextModel):
    """SupportInteraction entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_interaction:{id}"

    id: str = ContextField(
        description="Interaction ID",
        is_key_component=True,
    )

    user_id: str = ContextField(
        description="Employee who asked",
        index="tag",
    )

    interaction_date: str = ContextField(
        description="Date (YYYY-MM-DD)",
        index="tag",
    )

    channel: str = ContextField(
        description="Channel: chat_assistant, ticket, steward_office_hours",
        index="tag",
    )

    topic: str = ContextField(
        description="Topic",
        index="text",
        weight=2.0,
    )

    days_since_event: str = ContextField(
        description="Days between the triggering event and this question",
        index="tag",
    )

    summary: str = ContextField(
        description="Summary of the interaction",
        index="text",
    )

    resolution: str = ContextField(
        description="How it was resolved",
        index="text",
    )

    follow_up: str = ContextField(
        description="Did the employee come back about the same issue: yes/no",
        index="tag",
    )

    summary_embedding: list[float] = ContextField(
        description="Vector embedding of the summary, for finding similar interactions",
        index="vector",
        vector_dim=1536,
        distance_metric="cosine",
    )

    user: Any = ContextRelationship(
        description="Employee who asked",
        target="Employee",
        source_field="user_id",
    )


class PolicyDoc(ContextModel):
    """PolicyDoc entity for the Data Assistant domain."""

    __redis_key_template__ = "datagov_policydoc:{doc_id}"

    doc_id: str = ContextField(
        description="Document ID",
        is_key_component=True,
    )

    title: str = ContextField(
        description="Document title",
        index="text",
        weight=2.0,
    )

    category: str = ContextField(
        description="Category: policy, procedure, faq",
        index="tag",
    )

    content: str = ContextField(
        description="Full document text",
        index="text",
    )

    content_embedding: list[float] = ContextField(
        description="Vector embedding of document content",
        index="vector",
        vector_dim=1536,
        distance_metric="cosine",
    )
