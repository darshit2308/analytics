"""Tests for maintainer-pipeline aggregations."""

from datetime import UTC, datetime

import pandas as pd

from hiero_analytics.analysis.maintainer_pipeline import (
    activity_to_role_dataframe,
    build_maintainer_repo_pipeline,
    build_maintainer_yearly_pipeline,
    collapse_repo_pipeline_tail,
)
from hiero_analytics.data_sources.models import ContributorActivityRecord


def _record(
    activity_type: str,
    actor: str,
    repo: str,
    year: int,
    target_type: str = "pull_request",
) -> ContributorActivityRecord:
    return ContributorActivityRecord(
        repo=repo,
        activity_type=activity_type,
        actor=actor,
        occurred_at=datetime(year, 1, 1, tzinfo=UTC),
        target_type=target_type,
        target_number=1,
    )


def test_activity_to_role_dataframe_filters_unknown_types():
    """Only maintainer activity records should be classified into governance stages."""
    role_lookup = {"repo-a": {"alice": "maintainer", "bob": "triage", "dana": "committer"}}
    records = [
        _record("authored_issue", "dana", "org/repo-a", 2024, target_type="issue"),
        _record("authored_pull_request", "alice", "org/repo-a", 2024),
        _record("reviewed_pull_request", "bob", "org/repo-a", 2024),
        _record("merged_pull_request", "carol", "org/repo-a", 2024),
        _record("ignored_event", "dave", "org/repo-a", 2024),
    ]

    df = activity_to_role_dataframe(records, role_lookup)

    assert len(df) == 4
    assert set(df["repo"]) == {"repo-a"}
    # alice -> maintainer, bob -> triage, dana -> committer, carol has no entry -> general_user
    assert set(df["stage"]) == {"maintainer", "triage", "committer", "general_user"}


def test_activity_to_role_dataframe_defaults_unknown_actor_to_general_user():
    """Actors missing from the lookup should remain in the general-user stage."""
    records = [_record("authored_pull_request", "unknown_actor", "org/repo-a", 2024)]
    df = activity_to_role_dataframe(records, {})
    assert df.iloc[0]["stage"] == "general_user"


def test_activity_to_role_dataframe_matches_actor_case_insensitively():
    """Mixed-case GitHub logins should still match normalized governance roles."""
    records = [_record("authored_pull_request", "Alice", "org/repo-a", 2024)]

    df = activity_to_role_dataframe(records, {"repo-a": {"alice": "maintainer"}})

    assert df.iloc[0]["stage"] == "maintainer"


def test_build_maintainer_yearly_pipeline_counts_unique_actors_per_stage():
    """Yearly rollups should count unique actors once per stage."""
    role_lookup = {
        "repo-a": {"alice": "general_user", "bob": "triage", "carol": "committer", "dana": "maintainer"}
    }
    records = [
        _record("authored_issue", "dana", "org/repo-a", 2024, target_type="issue"),
        _record("authored_pull_request", "alice", "org/repo-a", 2024),
        _record("authored_pull_request", "alice", "org/repo-a", 2024),
        _record("reviewed_pull_request", "bob", "org/repo-a", 2024),
        _record("merged_pull_request", "carol", "org/repo-a", 2024),
    ]

    stage_df = activity_to_role_dataframe(records, role_lookup)
    yearly = build_maintainer_yearly_pipeline(stage_df)

    row = yearly.iloc[0]
    assert row["year"] == 2024
    assert row["general_user"] == 1
    assert row["triage"] == 1
    assert row["committer"] == 1
    assert row["maintainer"] == 1


def test_build_maintainer_repo_pipeline_sorts_by_total():
    """Repo rollups should sort repositories by total observed contributors."""
    role_lookup = {
        "repo-a": {"alice": "general_user", "bob": "triage", "carol": "committer"},
        "repo-b": {"dana": "general_user"},
    }
    records = [
        _record("authored_pull_request", "alice", "org/repo-a", 2024),
        _record("reviewed_pull_request", "bob", "org/repo-a", 2024),
        _record("merged_pull_request", "carol", "org/repo-a", 2024),
        _record("authored_pull_request", "dana", "org/repo-b", 2024),
    ]

    stage_df = activity_to_role_dataframe(records, role_lookup)
    by_repo = build_maintainer_repo_pipeline(stage_df)

    assert by_repo.iloc[0]["repo"] == "repo-a"
    assert by_repo.iloc[0]["general_user"] == 1
    assert by_repo.iloc[0]["triage"] == 1
    assert by_repo.iloc[0]["committer"] == 1


def test_collapse_repo_pipeline_tail_aggregates_remaining_rows():
    """Long repo tails should collapse into a single aggregated chart row."""
    repo_df = pd.DataFrame(
        [
            {"repo": "repo-a", "general_user": 10, "triage": 1, "committer": 2, "maintainer": 3},
            {"repo": "repo-b", "general_user": 8, "triage": 1, "committer": 2, "maintainer": 1},
            {"repo": "repo-c", "general_user": 6, "triage": 1, "committer": 1, "maintainer": 1},
            {"repo": "repo-d", "general_user": 4, "triage": 0, "committer": 1, "maintainer": 1},
        ]
    )

    collapsed = collapse_repo_pipeline_tail(repo_df, max_repos=3)

    assert len(collapsed) == 3
    assert collapsed.iloc[0]["repo"] == "repo-a"
    assert collapsed.iloc[1]["repo"] == "repo-b"
    assert collapsed.iloc[2]["repo"] == "Other Repos (2)"
    assert collapsed.iloc[2]["general_user"] == 10
    assert collapsed.iloc[2]["triage"] == 1
    assert collapsed.iloc[2]["committer"] == 2
    assert collapsed.iloc[2]["maintainer"] == 2


def test_collapse_repo_pipeline_tail_noop_when_below_limit():
    """Short repo tables should remain unchanged when under the chart limit."""
    repo_df = pd.DataFrame(
        [
            {"repo": "repo-a", "general_user": 1, "triage": 0, "committer": 0, "maintainer": 0},
            {"repo": "repo-b", "general_user": 1, "triage": 0, "committer": 0, "maintainer": 0},
        ]
    )

    collapsed = collapse_repo_pipeline_tail(repo_df, max_repos=5)

    assert collapsed.equals(repo_df)
