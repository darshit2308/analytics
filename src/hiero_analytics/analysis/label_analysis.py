"""Module for analyzing and counting repository labels."""
from __future__ import annotations

from hiero_analytics.data_sources.models import IssueRecord
from hiero_analytics.domain.labels import LabelSpec


def _count_issues(
    issues: list[IssueRecord],
    specs: tuple[LabelSpec, ...],
    *,
    closed_only: bool = False,
) -> dict[str, int]:
    """Count issues matching a collection of LabelSpec rules.

    Each LabelSpec represents a classification rule defined by a set of
    labels and a name. An issue is counted for a spec if its labels satisfy
    the spec's `matches()` condition.

    Parameters
    ----------
    issues
        List of IssueRecord objects to analyze.
    specs
        Tuple of LabelSpec definitions describing the classification groups.
    closed_only
        If True, only issues with state "closed" are included.

    Returns:
    -------
    dict[str, int]
        Mapping of spec name → number of matching issues.
    """
    results = {spec.name: 0 for spec in specs}

    for issue in issues:

        if closed_only and issue.state.lower() != "closed":
            continue

        labels = set(issue.labels)

        for spec in specs:
            if spec.matches(labels):
                results[spec.name] += 1

    return results


def count_issues_by_label_specs(
    issues: list[IssueRecord],
    specs: tuple[LabelSpec, ...],
) -> dict[str, int]:
    """Count issues matching each LabelSpec classification.

    This function aggregates issue counts for each label specification,
    allowing datasets to be grouped by predefined label categories
    (e.g. difficulty levels or onboarding labels).

    Parameters
    ----------
    issues
        List of IssueRecord objects.
    specs
        Tuple of LabelSpec definitions used for classification.

    Returns:
    -------
    dict[str, int]
        Mapping of spec name → total issue count.
    """
    return _count_issues(issues, specs)


def count_closed_issues_by_label_specs(
    issues: list[IssueRecord],
    specs: tuple[LabelSpec, ...],
) -> dict[str, int]:
    """Count closed issues matching each LabelSpec classification.

    This function behaves the same as `count_issues_by_label_specs`,
    but only includes issues whose state is "closed".

    Parameters
    ----------
    issues
        List of IssueRecord objects.
    specs
        Tuple of LabelSpec definitions used for classification.

    Returns:
    -------
    dict[str, int]
        Mapping of spec name → number of closed issues matching the spec.
    """
    return _count_issues(issues, specs, closed_only=True)