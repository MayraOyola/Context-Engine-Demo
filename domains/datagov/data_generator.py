"""Generate synthetic data for the Financial data and analytics provider demo.

All people, data products, requests, incidents and interactions are fictional. Dates are offsets
from today so the story ("an incident opened three days ago") stays true whenever setup runs.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

import openai

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.domain_contract import GeneratedDataset  # noqa: E402

OUTPUT_DIR = ROOT / "output" / "datagov"
DEMO_USER_ID = "E1001"

TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def fake_embedding(text: str) -> list[float]:
    digest = sha256(text.encode("utf-8")).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(1536)]


def embed(texts: list[str]) -> list[list[float]]:
    if not os.getenv("OPENAI_API_KEY"):
        return [fake_embedding(text) for text in texts]
    client = openai.OpenAI()
    response = client.embeddings.create(
        input=texts,
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    return [item.embedding for item in response.data]


# ── Employees ──────────────────────────────────────────────────────────────

EMPLOYEES = [
    {"id": "E1001", "name": "Priya Nair", "email": "priya.nair@example.com", "role": "Senior Data Scientist",
     "team": "Credit Analytics", "division": "analytics", "clearance": "confidential", "region": "North America"},
    {"id": "E1002", "name": "Daniel Okafor", "email": "daniel.okafor@example.com", "role": "Data Engineer",
     "team": "Ratings Data Platform", "division": "ratings", "clearance": "confidential", "region": "EMEA"},
    {"id": "E1003", "name": "Elena Rossi", "email": "elena.rossi@example.com", "role": "Risk and Compliance Analyst",
     "team": "Commodity Risk", "division": "commodities", "clearance": "restricted", "region": "EMEA"},
    {"id": "E1004", "name": "Marcus Lee", "email": "marcus.lee@example.com", "role": "Quant Researcher",
     "team": "Index Research", "division": "index_research", "clearance": "confidential", "region": "APAC"},
    {"id": "E1005", "name": "Sofia Alvarez", "email": "sofia.alvarez@example.com", "role": "Data Analyst",
     "team": "ESG Insights", "division": "analytics", "clearance": "standard", "region": "North America"},
    {"id": "E1006", "name": "Tom Becker", "email": "tom.becker@example.com", "role": "Analytics Engineer",
     "team": "Ratings Data Platform", "division": "ratings", "clearance": "confidential", "region": "North America"},
]

# ── Data products ──────────────────────────────────────────────────────────

DATA_PRODUCTS = [
    {"id": "DP-01", "name": "Company Fundamentals", "division": "analytics", "owner_team": "Fundamentals Data",
     "steward": "R. Hughes", "description": "Standardized financial statements and ratios for public and private companies, used for credit and equity models.",
     "classification": "confidential", "refresh": "daily", "quality_score": "96", "status": "active",
     "access_policy": "self_serve", "replacement_id": ""},
    {"id": "DP-02", "name": "Ratings Actions Feed", "division": "ratings", "owner_team": "Ratings Data Platform",
     "steward": "A. Moreau", "description": "Rating actions, outlooks and watch listings with effective dates. The legacy flat-file delivery is being replaced by the Ratings Actions API.",
     "classification": "restricted", "refresh": "real_time", "quality_score": "93", "status": "deprecated",
     "access_policy": "approval_required", "replacement_id": "DP-03"},
    {"id": "DP-03", "name": "Ratings Actions API", "division": "ratings", "owner_team": "Ratings Data Platform",
     "steward": "A. Moreau", "description": "REST and streaming API for rating actions, replacing the legacy Ratings Actions Feed. Schema versioned with a six-month overlap.",
     "classification": "restricted", "refresh": "real_time", "quality_score": "95", "status": "active",
     "access_policy": "approval_required", "replacement_id": ""},
    {"id": "DP-04", "name": "Credit Default Probability", "division": "analytics", "owner_team": "Credit Analytics",
     "steward": "P. Das", "description": "Model-based probability of default scores for companies, refreshed daily with factor attribution.",
     "classification": "confidential", "refresh": "daily", "quality_score": "91", "status": "active",
     "access_policy": "self_serve", "replacement_id": ""},
    {"id": "DP-05", "name": "Commodity Price Assessments", "division": "commodities", "owner_team": "Price Assessment",
     "steward": "L. Fontaine", "description": "Daily benchmark price assessments for energy, metals and agriculture, with methodology notes.",
     "classification": "restricted", "refresh": "daily", "quality_score": "98", "status": "active",
     "access_policy": "approval_required", "replacement_id": ""},
    {"id": "DP-06", "name": "ESG Scores", "division": "analytics", "owner_team": "ESG Insights",
     "steward": "N. Kapoor", "description": "Company-level environmental, social and governance scores with underlying indicators.",
     "classification": "internal", "refresh": "weekly", "quality_score": "89", "status": "active",
     "access_policy": "self_serve", "replacement_id": ""},
    {"id": "DP-07", "name": "Corporate Ownership and Hierarchies", "division": "analytics", "owner_team": "Entity Data",
     "steward": "S. Walker", "description": "Parent, subsidiary and ultimate-owner relationships across legal entities.",
     "classification": "confidential", "refresh": "weekly", "quality_score": "92", "status": "active",
     "access_policy": "self_serve", "replacement_id": ""},
    {"id": "DP-08", "name": "Supply Chain Relationships", "division": "analytics", "owner_team": "Entity Data",
     "steward": "S. Walker", "description": "Customer and supplier links between companies, with relationship type and confidence.",
     "classification": "confidential", "refresh": "weekly", "quality_score": "84", "status": "beta",
     "access_policy": "approval_required", "replacement_id": ""},
    {"id": "DP-09", "name": "Index Constituent History", "division": "index_research", "owner_team": "Index Operations",
     "steward": "K. Tan", "description": "Point-in-time index membership, weights and corporate action adjustments.",
     "classification": "restricted", "refresh": "daily", "quality_score": "97", "status": "active",
     "access_policy": "approval_required", "replacement_id": ""},
    {"id": "DP-10", "name": "News Sentiment Signals", "division": "analytics", "owner_team": "Data Science",
     "steward": "J. Ortiz", "description": "Entity-level sentiment and event signals derived from licensed news content. Redistribution is restricted by license.",
     "classification": "internal", "refresh": "real_time", "quality_score": "87", "status": "active",
     "access_policy": "self_serve", "replacement_id": ""},
]

# ── Access requests ────────────────────────────────────────────────────────

ACCESS_REQUESTS = [
    {"id": "AR-5001", "user_id": "E1001", "data_product_id": "DP-04", "requested_date": day(-25), "status": "approved",
     "approved_until": day(65), "justification": "Credit-risk model training", "approver": "P. Das",
     "notes": "Approved for 90 days. Renewal requires a new justification."},
    {"id": "AR-5002", "user_id": "E1001", "data_product_id": "DP-08", "requested_date": day(-2), "status": "pending",
     "approved_until": "", "justification": "Supply-chain contagion features for the credit model", "approver": "S. Walker",
     "notes": "Beta product. Steward review in progress; standard SLA is 5 business days."},
    {"id": "AR-5003", "user_id": "E1001", "data_product_id": "DP-01", "requested_date": day(-120), "status": "approved",
     "approved_until": "", "justification": "Standing analytics access", "approver": "R. Hughes",
     "notes": "Self-serve; no expiry."},
    {"id": "AR-5011", "user_id": "E1002", "data_product_id": "DP-02", "requested_date": day(-200), "status": "approved",
     "approved_until": day(-8), "justification": "Legacy ratings feed ingestion", "approver": "A. Moreau",
     "notes": "Legacy feed deprecated; access ends at cutover."},
    {"id": "AR-5012", "user_id": "E1002", "data_product_id": "DP-03", "requested_date": day(-10), "status": "approved",
     "approved_until": day(355), "justification": "Migration to the Ratings Actions API", "approver": "A. Moreau",
     "notes": "Approved for 12 months."},
    {"id": "AR-5021", "user_id": "E1003", "data_product_id": "DP-05", "requested_date": day(-30), "status": "approved",
     "approved_until": day(335), "justification": "Quarterly commodity risk reporting", "approver": "L. Fontaine",
     "notes": "Restricted data. Access reviewed every quarter."},
    {"id": "AR-5022", "user_id": "E1003", "data_product_id": "DP-09", "requested_date": day(-6), "status": "denied",
     "approved_until": "", "justification": "Cross-division index benchmark comparison", "approver": "K. Tan",
     "notes": "Denied: restricted to the Index Research division. Request through the Index Research steward with a sponsor."},
    {"id": "AR-5031", "user_id": "E1004", "data_product_id": "DP-09", "requested_date": day(-40), "status": "approved",
     "approved_until": day(325), "justification": "Index methodology research", "approver": "K. Tan",
     "notes": "Approved for 12 months."},
    {"id": "AR-5041", "user_id": "E1005", "data_product_id": "DP-06", "requested_date": day(-15), "status": "approved",
     "approved_until": "", "justification": "ESG analysis", "approver": "N. Kapoor",
     "notes": "Self-serve; no expiry."},
    {"id": "AR-5051", "user_id": "E1006", "data_product_id": "DP-02", "requested_date": day(-5), "status": "pending",
     "approved_until": "", "justification": "Migration test environment", "approver": "A. Moreau",
     "notes": "Product is deprecated; the steward recommends requesting the Ratings Actions API instead."},
]

# ── Quality incidents ──────────────────────────────────────────────────────

INCIDENTS = [
    {"id": "INC-9001", "data_product_id": "DP-01", "opened_date": day(-3), "severity": "sev2", "status": "mitigated",
     "summary": "Restated quarterly filings loaded twice for a subset of issuers",
     "impact": "Duplicate fundamentals rows for about 1,200 issuers between the nightly loads. Models that join on filing date may double count.",
     "resolution": "Deduplication applied to the daily load. Consumers should re-pull data since the first load of the incident window."},
    {"id": "INC-9002", "data_product_id": "DP-04", "opened_date": day(-1), "severity": "sev3", "status": "open",
     "summary": "Delay in the daily default probability refresh for APAC issuers",
     "impact": "APAC scores are one day stale until the upstream feed catches up.",
     "resolution": "Workaround: use the prior day's scores and the as-of date field. ETA end of day."},
    {"id": "INC-9003", "data_product_id": "DP-10", "opened_date": day(-14), "severity": "sev3", "status": "resolved",
     "summary": "Sentiment scores missing for some entities after a licensing change",
     "impact": "A set of entities returned null sentiment for four days.",
     "resolution": "Scores restored. Redistribution restrictions on the source content remain in force."},
    {"id": "INC-9004", "data_product_id": "DP-05", "opened_date": day(-9), "severity": "sev2", "status": "resolved",
     "summary": "Methodology note missing on a metals benchmark assessment",
     "impact": "Several daily assessments were published without the methodology reference.",
     "resolution": "Notes backfilled. No price values changed."},
    {"id": "INC-9005", "data_product_id": "DP-02", "opened_date": day(-18), "severity": "sev2", "status": "resolved",
     "summary": "Legacy flat-file delivery delayed during the API cutover rehearsal",
     "impact": "Flat files arrived up to two hours late on three days.",
     "resolution": "Rehearsal complete. The legacy feed's final delivery date is set."},
]

# ── Historical support interactions (stand-in for years of assistant, ticket and office-hours history) ──

INTERACTIONS = [
    {"id": "INT-7001", "user_id": "E1001", "interaction_date": day(-60), "channel": "ticket",
     "topic": "Access to Credit Default Probability", "days_since_event": "0",
     "summary": "Asked how to get access to the default probability scores for a model-training project.",
     "resolution": "Pointed to the self-serve request flow and the 90-day approval policy.", "follow_up": "no"},
    {"id": "INT-7002", "user_id": "E1001", "interaction_date": day(-26), "channel": "chat_assistant",
     "topic": "Access request status for Credit Default Probability", "days_since_event": "1",
     "summary": "Checked whether the default probability access request had been approved.",
     "resolution": "Confirmed approved for 90 days.", "follow_up": "no"},
    {"id": "INT-7101", "user_id": "E1002", "interaction_date": day(-30), "channel": "ticket",
     "topic": "Field mapping after the Ratings Actions API cutover", "days_since_event": "2",
     "summary": "Asked how legacy flat-file fields map to the new API schema after the cutover notice.",
     "resolution": "Shared the field mapping document and the six-month overlap policy.", "follow_up": "yes"},
    {"id": "INT-7102", "user_id": "E1006", "interaction_date": day(-12), "channel": "chat_assistant",
     "topic": "Legacy feed end date and migration steps", "days_since_event": "5",
     "summary": "Asked when the legacy ratings feed will stop and what to do before then.",
     "resolution": "Gave the deprecation date and pointed to the migration policy.", "follow_up": "yes"},
    {"id": "INT-7103", "user_id": "E1004", "interaction_date": day(-20), "channel": "steward_office_hours",
     "topic": "Re-pulling data after a duplicate-rows incident", "days_since_event": "1",
     "summary": "Asked whether to re-pull fundamentals data after the duplicate-rows incident and how far back.",
     "resolution": "Advised re-pulling from the start of the incident window.", "follow_up": "yes"},
    {"id": "INT-7104", "user_id": "E1005", "interaction_date": day(-8), "channel": "chat_assistant",
     "topic": "Restatements double counted in a model after a data incident", "days_since_event": "2",
     "summary": "Noticed duplicate rows in fundamentals data affecting a model input and asked how to correct it.",
     "resolution": "Explained the deduplication applied and the need to re-pull.", "follow_up": "yes"},
    {"id": "INT-7105", "user_id": "E1006", "interaction_date": day(-4), "channel": "chat_assistant",
     "topic": "Schema change notice for the Ratings Actions API", "days_since_event": "1",
     "summary": "Asked which fields change in the next schema version and how long the old version is supported.",
     "resolution": "Shared the versioning policy: two versions in parallel for six months.", "follow_up": "no"},
    {"id": "INT-7201", "user_id": "E1003", "interaction_date": day(-16), "channel": "ticket",
     "topic": "Evidence of restricted data access for the quarterly audit", "days_since_event": "10",
     "summary": "Asked for a report of who accessed restricted commodity data last quarter for audit evidence.",
     "resolution": "Pointed to the access review log and the audit evidence procedure.", "follow_up": "yes"},
    {"id": "INT-7202", "user_id": "E1004", "interaction_date": day(-35), "channel": "chat_assistant",
     "topic": "Redistributing sentiment signals to a client", "days_since_event": "0",
     "summary": "Asked whether sentiment signals can be shared with an external client.",
     "resolution": "Explained that redistribution is restricted by the content license and routed to licensing.", "follow_up": "no"},
    {"id": "INT-7203", "user_id": "E1005", "interaction_date": day(-22), "channel": "chat_assistant",
     "topic": "Difference between beta and active data products", "days_since_event": "0",
     "summary": "Asked what beta status means for a data product's reliability.",
     "resolution": "Explained that beta products have no quality SLA and may change.", "follow_up": "no"},
]

# ── Policy documents (RAG) ─────────────────────────────────────────────────

POLICY_DOCS = [
    {"doc_id": "DOC-001", "title": "How to request access to a data product", "category": "procedure",
     "content": "Self-serve data products grant access immediately after the requester accepts the usage terms. "
                "Approval-required products route to the data steward, whose standard review time is five business days. "
                "Approved access to confidential data lasts 90 days by default and can be renewed with a new justification. "
                "Restricted data is limited to employees whose clearance is restricted, and some products are limited to a single division."},
    {"doc_id": "DOC-002", "title": "Data classification levels", "category": "policy",
     "content": "Internal data can be used across the company. Confidential data is limited to employees with a business need and a current access approval. "
                "Restricted data is limited to named users, requires steward approval, access is reviewed every quarter, and exports require a logged business reason."},
    {"doc_id": "DOC-003", "title": "Data quality incident management", "category": "procedure",
     "content": "Incidents are rated sev1 to sev3 by impact. The data steward posts the affected data product, the affected window, and a workaround. "
                "Consumers should check whether their pipelines ran inside the affected window and re-pull data from the start of that window once the incident is mitigated. "
                "Open incidents are shown on the data product page until resolved."},
    {"doc_id": "DOC-004", "title": "Data product deprecation and migration policy", "category": "policy",
     "content": "A deprecated data product is announced at least six months before its final delivery date. A replacement is named and both versions run in parallel for the overlap period. "
                "Consumers must request access to the replacement before the cutover; access to the deprecated product ends on the final delivery date."},
    {"doc_id": "DOC-005", "title": "Audit evidence and access reviews", "category": "procedure",
     "content": "Access to restricted data is reviewed each quarter. Audit evidence includes the access review log, approver, justification and access end date. "
                "Requests for evidence are handled by the data governance office, and records are retained for one year."},
    {"doc_id": "DOC-006", "title": "Licensing and redistribution", "category": "policy",
     "content": "Some data products include licensed third-party content. Redistribution to external clients is not permitted unless the license allows it. "
                "Questions about sharing data outside the company go to the licensing team before any data leaves the company."},
    {"doc_id": "DOC-007", "title": "Data quality scores", "category": "faq",
     "content": "The data quality score out of 100 combines completeness, timeliness, accuracy checks and consumer-reported issues. "
                "Beta products are not scored against an SLA. A score below 85 should be treated as a signal to check the data product page for open incidents."},
    {"doc_id": "DOC-008", "title": "Lineage and impact analysis", "category": "faq",
     "content": "Each data product page shows its upstream sources and downstream consumers. Before changing a pipeline, use lineage to find consumers that depend on a field. "
                "Stewards notify downstream owners of schema changes at least thirty days ahead for non-breaking changes."},
]


def write_jsonl(output_dir: Path, filename: str, rows: list[dict]) -> None:
    path = output_dir / filename
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  {path.name}: {len(rows)} records")


def update_env(key: str, value: str) -> None:
    env_path = ROOT / ".env"
    safe_value = f'"{value}"' if " " in value else value
    if not env_path.exists():
        env_path.write_text(f"{key}={safe_value}\n")
        return
    lines = env_path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={safe_value}"
            break
    else:
        lines.append(f"{key}={safe_value}")
    env_path.write_text("\n".join(lines) + "\n")


def generate_demo_data(
    *,
    output_dir: Path | None = None,
    seed: int | None = None,
    update_env_file: bool = False,
) -> GeneratedDataset:
    del seed
    resolved_output_dir = output_dir or OUTPUT_DIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating embeddings for policy docs and interaction summaries...")
    doc_embeddings = embed([doc["content"] for doc in POLICY_DOCS])
    policy_docs = [{**doc, "content_embedding": emb} for doc, emb in zip(POLICY_DOCS, doc_embeddings)]
    int_embeddings = embed([f"{i['topic']}. {i['summary']}" for i in INTERACTIONS])
    interactions = [{**i, "summary_embedding": emb} for i, emb in zip(INTERACTIONS, int_embeddings)]

    names = {p["id"]: p["name"] for p in DATA_PRODUCTS}
    access_requests = [{**r, "data_product_name": names[r["data_product_id"]]} for r in ACCESS_REQUESTS]
    incidents = [{**i, "data_product_name": names[i["data_product_id"]]} for i in INCIDENTS]

    print("Writing JSONL files:")
    write_jsonl(resolved_output_dir, "employees.jsonl", EMPLOYEES)
    write_jsonl(resolved_output_dir, "data_products.jsonl", DATA_PRODUCTS)
    write_jsonl(resolved_output_dir, "access_requests.jsonl", access_requests)
    write_jsonl(resolved_output_dir, "incidents.jsonl", incidents)
    write_jsonl(resolved_output_dir, "interactions.jsonl", interactions)
    write_jsonl(resolved_output_dir, "policydocs.jsonl", policy_docs)

    demo = EMPLOYEES[0]
    if update_env_file:
        update_env("DEMO_USER_ID", demo["id"])
        update_env("DEMO_USER_NAME", demo["name"])
        update_env("DEMO_USER_EMAIL", demo["email"])
    print(f"\nDemo user: {demo['name']} ({demo['id']})")

    return GeneratedDataset(
        output_dir=str(resolved_output_dir),
        env_updates={
            "DEMO_USER_ID": demo["id"],
            "DEMO_USER_NAME": demo["name"],
            "DEMO_USER_EMAIL": demo["email"],
        },
        summary={
            "employees": len(EMPLOYEES),
            "data_products": len(DATA_PRODUCTS),
            "access_requests": len(ACCESS_REQUESTS),
            "incidents": len(INCIDENTS),
            "interactions": len(interactions),
            "policy_docs": len(policy_docs),
        },
    )


def main() -> None:
    generate_demo_data(output_dir=OUTPUT_DIR, update_env_file=True)


if __name__ == "__main__":
    main()
