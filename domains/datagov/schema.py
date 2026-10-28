"""Financial data and analytics provider data model - single source of truth.

A data-discovery and governance assistant for employees who find, request and rely on enterprise
data products. Synthetic users, data products, access requests, incidents, support history and
policy documents loaded directly into Redis. Each EntitySpec drives ContextModel code generation
(and therefore the MCP tools), Redis Search indexes and sample data.
"""

from __future__ import annotations

from backend.app.core.domain_schema import (
    EntitySpec,
    FieldSpec,
    RelationshipSpec,
    entity_by_class,
    entity_by_file,
)


ENTITY_SPECS: tuple[EntitySpec, ...] = (
    EntitySpec(
        class_name="Employee",
        redis_key_template="datagov_employee:{id}",
        file_name="employees.jsonl",
        id_field="id",
        fields=(
            FieldSpec("id", "str", "Employee ID", is_key_component=True),
            FieldSpec("name", "str", "Full name", index="text", weight=2.0),
            FieldSpec("email", "str", "Email", index="text", no_stem=True),
            FieldSpec("role", "str", "Job role", index="text"),
            FieldSpec("team", "str", "Team", index="text"),
            FieldSpec(
                "division", "str",
                "Division: analytics, ratings, commodities, index_research", index="tag",
            ),
            FieldSpec("clearance", "str", "Data clearance: standard, confidential, restricted", index="tag"),
            FieldSpec("region", "str", "Region", index="tag"),
        ),
    ),
    EntitySpec(
        class_name="DataProduct",
        redis_key_template="datagov_dataproduct:{id}",
        file_name="data_products.jsonl",
        id_field="id",
        fields=(
            FieldSpec("id", "str", "Data product ID", is_key_component=True),
            FieldSpec("name", "str", "Data product name", index="text", weight=2.0),
            FieldSpec(
                "division", "str",
                "Owning division: analytics, ratings, commodities, index_research", index="tag",
            ),
            FieldSpec("owner_team", "str", "Owning team", index="text"),
            FieldSpec("steward", "str", "Data steward", index="text"),
            FieldSpec("description", "str", "What the data product contains and who uses it", index="text"),
            FieldSpec(
                "classification", "str",
                "Classification: internal, confidential, restricted", index="tag",
            ),
            FieldSpec("refresh", "str", "Refresh frequency: real_time, daily, weekly, monthly", index="tag"),
            FieldSpec("quality_score", "str", "Data quality score out of 100", index="tag"),
            FieldSpec("status", "str", "Status: active, beta, deprecated", index="tag"),
            FieldSpec(
                "access_policy", "str", "Access policy: self_serve, approval_required", index="tag"
            ),
            FieldSpec("replacement_id", "str", "Replacement data product if deprecated", index="tag"),
        ),
        relationships=(
            RelationshipSpec(
                "replacement", "Product that replaces this one", "replacement_id", "DataProduct"
            ),
        ),
    ),
    EntitySpec(
        class_name="AccessRequest",
        redis_key_template="datagov_accessrequest:{id}",
        file_name="access_requests.jsonl",
        id_field="id",
        fields=(
            FieldSpec("id", "str", "Request ID", is_key_component=True),
            FieldSpec("user_id", "str", "Requesting employee", index="tag"),
            FieldSpec("data_product_id", "str", "Requested data product ID, like DP-01", index="tag"),
            FieldSpec("data_product_name", "str", "Requested data product name, like Company Fundamentals", index="tag"),
            FieldSpec("requested_date", "str", "Date requested (YYYY-MM-DD)", index="tag"),
            FieldSpec(
                "status", "str", "Status: approved, pending, denied, expired", index="tag"
            ),
            FieldSpec("approved_until", "str", "Access end date (YYYY-MM-DD) when approved", index="tag"),
            FieldSpec("justification", "str", "Business justification", index="text"),
            FieldSpec("approver", "str", "Approver or steward", index="text"),
            FieldSpec("notes", "str", "Decision notes", index="text"),
        ),
        relationships=(
            RelationshipSpec("user", "Requesting employee", "user_id", "Employee"),
            RelationshipSpec("data_product", "Requested data product", "data_product_id", "DataProduct"),
        ),
    ),
    EntitySpec(
        class_name="QualityIncident",
        redis_key_template="datagov_incident:{id}",
        file_name="incidents.jsonl",
        id_field="id",
        fields=(
            FieldSpec("id", "str", "Incident ID", is_key_component=True),
            FieldSpec("data_product_id", "str", "Affected data product ID, like DP-01", index="tag"),
            FieldSpec("data_product_name", "str", "Affected data product name, like Company Fundamentals", index="tag"),
            FieldSpec("opened_date", "str", "Date opened (YYYY-MM-DD)", index="tag"),
            FieldSpec("severity", "str", "Severity: sev1, sev2, sev3", index="tag"),
            FieldSpec("status", "str", "Status: open, mitigated, resolved", index="tag"),
            FieldSpec("summary", "str", "What went wrong", index="text", weight=2.0),
            FieldSpec("impact", "str", "Who and what is affected", index="text"),
            FieldSpec("resolution", "str", "Resolution or workaround", index="text"),
        ),
        relationships=(
            RelationshipSpec("data_product", "Affected data product", "data_product_id", "DataProduct"),
        ),
    ),
    EntitySpec(
        class_name="SupportInteraction",
        redis_key_template="datagov_interaction:{id}",
        file_name="interactions.jsonl",
        id_field="id",
        fields=(
            FieldSpec("id", "str", "Interaction ID", is_key_component=True),
            FieldSpec("user_id", "str", "Employee who asked", index="tag"),
            FieldSpec("interaction_date", "str", "Date (YYYY-MM-DD)", index="tag"),
            FieldSpec("channel", "str", "Channel: chat_assistant, ticket, steward_office_hours", index="tag"),
            FieldSpec("topic", "str", "Topic", index="text", weight=2.0),
            FieldSpec("days_since_event", "str", "Days between the triggering event and this question", index="tag"),
            FieldSpec("summary", "str", "Summary of the interaction", index="text"),
            FieldSpec("resolution", "str", "How it was resolved", index="text"),
            FieldSpec("follow_up", "str", "Did the employee come back about the same issue: yes/no", index="tag"),
            FieldSpec(
                "summary_embedding", "list[float]", "Vector embedding of the summary, for finding similar interactions",
                index="vector", vector_dim=1536, distance_metric="cosine",
            ),
        ),
        relationships=(RelationshipSpec("user", "Employee who asked", "user_id", "Employee"),),
    ),
    EntitySpec(
        class_name="PolicyDoc",
        redis_key_template="datagov_policydoc:{doc_id}",
        file_name="policydocs.jsonl",
        id_field="doc_id",
        fields=(
            FieldSpec("doc_id", "str", "Document ID", is_key_component=True),
            FieldSpec("title", "str", "Document title", index="text", weight=2.0),
            FieldSpec("category", "str", "Category: policy, procedure, faq", index="tag"),
            FieldSpec("content", "str", "Full document text", index="text"),
            FieldSpec(
                "content_embedding", "list[float]", "Vector embedding of document content",
                index="vector", vector_dim=1536, distance_metric="cosine",
            ),
        ),
    ),
)

ENTITY_BY_FILE = entity_by_file(ENTITY_SPECS)
ENTITY_BY_CLASS = entity_by_class(ENTITY_SPECS)
