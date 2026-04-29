"""Analytics helpers for maintainer-pipeline role classification.

This module classifies contributor activity records, including both
pull request and issue activity, into governance roles and builds
aggregated pipeline tables for yearly and repository-level views.
"""

from __future__ import annotations

import pandas as pd

from hiero_analytics.data_sources.models import ContributorActivityRecord

STAGE_COLUMNS = ["general_user", "triage", "committer", "maintainer"]

_MAINTAINER_ACTIVITY_TYPES = {
    "authored_issue",
    "authored_pull_request",
    "reviewed_pull_request",
    "merged_pull_request",
}


def activity_to_role_dataframe(
    records: list[ContributorActivityRecord],
    repo_role_lookup: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """Classify each contributor activity record by governance role."""
    rows = []

    for record in records:
        if record.activity_type not in _MAINTAINER_ACTIVITY_TYPES:
            continue

        repo_name = record.repo.split("/")[-1]
        actor_key = record.actor.strip().lower()
        role = repo_role_lookup.get(repo_name, {}).get(actor_key, "general_user")

        rows.append(
            {
                "repo": repo_name,
                "actor": record.actor,
                "year": record.occurred_at.year,
                "stage": role,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["repo", "actor", "year", "stage"])

    return pd.DataFrame(rows)


def build_maintainer_yearly_pipeline(stage_df: pd.DataFrame) -> pd.DataFrame:
    """Build yearly contributor counts for each observed PR and issue activity stage."""
    if stage_df.empty:
        return pd.DataFrame(columns=["year", *STAGE_COLUMNS])

    yearly = (
        stage_df.groupby(["year", "stage"])["actor"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=STAGE_COLUMNS, fill_value=0)
        .reset_index()
        .sort_values("year")
    )

    return yearly.astype({column: int for column in STAGE_COLUMNS})


def build_maintainer_repo_pipeline(stage_df: pd.DataFrame) -> pd.DataFrame:
    """Build repository-level contributor counts for each observed PR and issue activity stage."""
    if stage_df.empty:
        return pd.DataFrame(columns=["repo", *STAGE_COLUMNS])

    by_repo = (
        stage_df.groupby(["repo", "stage"])["actor"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=STAGE_COLUMNS, fill_value=0)
        .reset_index()
    )

    by_repo["total"] = by_repo[STAGE_COLUMNS].sum(axis=1)
    by_repo = by_repo.sort_values("total", ascending=False).drop(columns=["total"])

    return by_repo.astype({column: int for column in STAGE_COLUMNS})


def collapse_repo_pipeline_tail(repo_df: pd.DataFrame, max_repos: int) -> pd.DataFrame:
    """Return a chart-friendly repo table with the long tail aggregated."""
    if repo_df.empty or max_repos <= 0 or len(repo_df) <= max_repos:
        return repo_df.copy()

    head_count = max_repos - 1
    if head_count <= 0:
        return repo_df.copy()

    head = repo_df.head(head_count).copy()
    tail = repo_df.iloc[head_count:]

    other_totals = {column: int(tail[column].sum()) for column in STAGE_COLUMNS}
    other_row = pd.DataFrame(
        [
            {
                "repo": f"Other Repos ({len(tail)})",
                **other_totals,
            }
        ]
    )

    return pd.concat([head, other_row], ignore_index=True)
