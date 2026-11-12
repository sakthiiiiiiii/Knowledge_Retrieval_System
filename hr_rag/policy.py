"""Dataset-specific approved policy; unknown documents quarantine rather than becoming public."""

import json
from pathlib import Path
from .config import ROOT


class Quarantined(ValueError):
    pass


def policy_for(name, path=None):
    policies = json.loads(
        Path(path or ROOT / "config" / "dataset_policies.json").read_text()
    )

    # Use explicit file policies so newly uploaded or unknown files are held for
    # review.
    policy = policies.get(Path(name).name)
    if not policy:
        raise Quarantined("No approved policy for file; quarantined")
    if policy.get("pending_review"):
        raise Quarantined("Research source pending explicit review; quarantined")
    if not policy.get("scope"):
        raise Quarantined("Policy lacks approved scopes")
    return policy


def classify(blocks, policy):
    """Apply section and row scopes BEFORE chunking; unclassified material fails closed."""
    if policy.get("employee_row_scopes"):
        # Use the Employees sheet to resolve team ownership for training rows that
        # omit a team.
        teams = {
            b.employee_id: b.team
            for b in blocks
            if b.metadata.get("sheet") == "Employees" and b.employee_id and b.team
        }
        for b in blocks:
            if (
                b.metadata.get("sheet") not in {"Employees", "Training"}
                or not b.employee_id
            ):
                b.scope = ()
                b.classification = "unclassified"
                continue
            b.team = b.team or teams.get(b.employee_id)
            b.scope = tuple(policy["scope"] + ([f"team:{b.team}"] if b.team else []))
            b.classification = "restricted-personal"
        return blocks

    # Apply the appendix restriction before the document default so sensitive sections
    # stay private.
    for b in blocks:
        if policy.get("appendix_b_scope") and (
            b.heading.lower().startswith("appendix b")
            or b.heading.lower().startswith("appendix b.")
            or "Appendix B." in b.heading
        ):
            b.scope = tuple(policy["appendix_b_scope"])
            b.classification = policy["appendix_b_classification"]
        else:
            b.scope = tuple(policy["scope"])
            b.classification = policy["classification"]
    return blocks
