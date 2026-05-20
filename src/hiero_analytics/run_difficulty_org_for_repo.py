"""
Run difficulty analytics for an org.

Produces:
- Difficulty distribution pie charts
- Difficulty distribution by repository (stacked bar)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from hiero_analytics.analysis.dataframe_utils import issues_to_dataframe
from hiero_analytics.config.charts import DIFFICULTY_COLORS
from hiero_analytics.config.paths import ORG, ensure_org_dirs
from hiero_analytics.data_sources.github_client import GitHubClient
from hiero_analytics.data_sources.github_ingest import (
    fetch_org_issues_graphql,
    fetch_repo_issue_events_for_issues_since,
)
from hiero_analytics.data_sources.models import IssueRecord, IssueTimelineEventRecord
from hiero_analytics.domain.labels import (
    DIFFICULTY_LEVELS,
    DIFFICULTY_ORDER,
    UNKNOWN_DIFFICULTY,
    LabelSpec,
)
from hiero_analytics.export.save import save_dataframe
from hiero_analytics.plotting.bars import plot_stacked_bar
from hiero_analytics.plotting.pie import plot_pie

TIMELINE_MAX_WORKERS = 3


def assign_difficulty(labels, specs):
    """Return the first matching difficulty label for an issue."""
    for spec in specs:
        if spec.matches(labels):
            return spec.name
    return UNKNOWN_DIFFICULTY


def _issues_labeled_since(
    issues: list[IssueRecord],
    timeline_events: list[IssueTimelineEventRecord],
    cutoff: datetime,
    difficulty_specs: tuple[LabelSpec, ...],
) -> set[tuple[str, int]]:
    """Return (repo, number) pairs for issues with an active difficulty label applied since cutoff.

    An issue qualifies when a difficulty label was added within the window
    and has not been subsequently removed.  Issues created after the cutoff
    that already carry a difficulty label are included as a fallback for
    cases where the label was applied at creation time (e.g. via an issue
    template) and no separate ``labeled`` event is recorded.
    """
    difficulty_label_names: set[str] = set()
    for spec in difficulty_specs:
        difficulty_label_names |= spec.labels

    # Track net label state per issue: add on "labeled", remove on "unlabeled".
    labeled: set[tuple[str, int]] = set()
    for event in timeline_events:
        if event.label is None or event.label not in difficulty_label_names:
            continue

        key = (event.repo, event.issue_number)
        if event.event_type == "labeled":
            labeled.add(key)
        elif event.event_type == "unlabeled":
            labeled.discard(key)

    # Fallback: include issues created after the cutoff whose current labels
    # match a difficulty spec but lack a corresponding timeline event.
    for issue in issues:
        key = (issue.repo, issue.number)
        if key in labeled:
            continue
        if issue.created_at >= cutoff:
            for spec in difficulty_specs:
                if spec.matches(set(issue.labels)):
                    labeled.add(key)
                    break

    return labeled


def main() -> None:
    """Run the difficulty analytics pipeline for the configured organization."""
    org_data_dir, org_charts_dir = ensure_org_dirs(ORG)

    print(f"Running difficulty analytics for org: {ORG}")

    client = GitHubClient()
    issues = fetch_org_issues_graphql(client, org=ORG, states=["OPEN"])

    print(f"Fetched {len(issues)} issues")

    df = issues_to_dataframe(issues)

    cutoff = datetime.now(UTC) - timedelta(days=30)

    # Fetch timeline events to determine when difficulty labels were applied.
    timeline_events = fetch_repo_issue_events_for_issues_since(
        client,
        issues,
        since=cutoff,
        max_workers=TIMELINE_MAX_WORKERS,
    )
    print(f"Fetched {len(timeline_events)} timeline events")

    # Identify issues that received a difficulty label within the window.
    labeled_issues = _issues_labeled_since(
        issues,
        timeline_events,
        cutoff,
        DIFFICULTY_LEVELS,
    )

    issue_keys = pd.MultiIndex.from_arrays([df["repo"], df["number"]])
    df = df[(df["state"] == "open") & issue_keys.isin(labeled_issues)].copy()

    # Remove org prefix from repo name
    df["repo"] = df["repo"].str.split("/").str[-1]

    # Assign difficulty
    df["difficulty"] = df["labels"].apply(lambda labels: assign_difficulty(labels, DIFFICULTY_LEVELS))

    # --------------------------------------------------
    # ORG LEVEL DIFFICULTY
    # --------------------------------------------------

    difficulty_counts = df.groupby("difficulty").size().reset_index(name="count")

    save_dataframe(
        difficulty_counts,
        org_data_dir / "difficulty_distribution_30_days.csv",
    )

    # Pies

    pie_variants = [
        (
            difficulty_counts,
            "Open Issues (Labeled Last 30 Days) by Difficulty Distribution (Including Unknown)",
            "difficulty_distribution_with_unknown_30_days.png",
        ),
        (
            difficulty_counts[difficulty_counts["difficulty"] != UNKNOWN_DIFFICULTY],
            "Open Issues (Labeled Last 30 Days) by Difficulty Distribution (Excluding Unknown)",
            "difficulty_distribution_without_unknown_30_days.png",
        ),
    ]

    for data, title, filename in pie_variants:
        plot_pie(
            data,
            label_col="difficulty",
            value_col="count",
            title=title,
            output_path=org_charts_dir / filename,
            colors=DIFFICULTY_COLORS,
            label_order=DIFFICULTY_ORDER,
            legend_title="Difficulty",
            center_label="Open issues",
        )

    # --------------------------------------------------
    # REPO DIFFICULTY STACKED BAR
    # --------------------------------------------------

    difficulty_cols = [
        UNKNOWN_DIFFICULTY,
        *[spec.name for spec in DIFFICULTY_LEVELS],
    ]

    pivot = (
        df.groupby(["repo", "difficulty"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=difficulty_cols, fill_value=0)
        .reset_index()
    )

    save_dataframe(
        pivot,
        org_data_dir / "difficulty_by_repo_30_days.csv",
    )

    plot_stacked_bar(
        pivot,
        x_col="repo",
        stack_cols=difficulty_cols,
        labels=difficulty_cols,
        title="Open Issues (Labeled Last 30 Days) by Difficulty Distribution in a Repository",
        output_path=org_charts_dir / "difficulty_by_repo_30_days.png",
        colors=DIFFICULTY_COLORS,
        rotate_x=45,
    )

    print("Difficulty analytics complete")


if __name__ == "__main__":
    main()
