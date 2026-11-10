"""Produce explainable analyst leads without making vulnerability claims."""


def analyze_relationships(relationships: list[dict]) -> list[dict]:
    findings = []
    for relationship in relationships:
        if relationship["predicate"] == "uses_vendor":
            title = "Documented third-party technology relationship"
            summary = (
                "The collected evidence associates an organization with a technology provider. "
                "This is dependency context, not evidence of a security weakness or internal trust path."
            )
            priority = "review" if relationship["verification_status"] == "corroborated" else "validate"
        else:
            title = f"Observed relationship: {relationship['predicate']}"
            summary = "A source record supports this relationship; review the linked evidence before drawing conclusions."
            priority = "informational"
        findings.append({
            "finding_id": f"finding_{relationship['relationship_id']}",
            "title": title,
            "summary": summary,
            "priority": priority,
            "confidence": relationship["confidence"],
            "verification_status": relationship["verification_status"],
            "relationship_id": relationship["relationship_id"],
            "evidence_count": relationship["evidence_count"],
            "independent_source_count": relationship["independent_source_count"],
            "analyst_review_required": relationship["analyst_review_required"] or priority == "validate",
        })
    return findings
