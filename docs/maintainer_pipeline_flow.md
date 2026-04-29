# Maintainer Pipeline Flow

## Purpose

The maintainer pipeline estimates **active governance participation** across the `hiero-ledger` organization.

It does this by combining:

- the **governance source of truth** for repository roles
- the **observed GitHub issue and pull request activity** of contributors

The final production outputs are charts and CSVs that show how many unique active contributors were observed as:

- `general_user`
- `triage`
- `committer`
- `maintainer`

This document explains the full flow and how those final outputs are derived.

## High-Level Flow

The maintainer pipeline runs in this order:

1. Fetch the Hiero governance configuration.
2. Build a repo-level lookup of contributor roles from governance.
3. Fetch contributor activity from GitHub across the organization.
4. Keep only issue creation and PR lifecycle signals relevant to this pipeline.
5. Assign each activity record a repo-scoped governance role.
6. Aggregate unique contributors by year and by repository.
7. Save CSV outputs and render charts.
8. Optionally compare the activity-based counts with governance truth tables for validation.

The main runner is:

- `src/hiero_analytics/run_maintainer_pipeline_org.py`

## Inputs

### 1. Governance Input

The governance source is fetched from:

- `https://raw.githubusercontent.com/hiero-ledger/governance/main/config.yaml`

This is configured in:

- `src/hiero_analytics/data_sources/governance_config.py`

The governance file provides:

- repository names
- team assignments per repository
- team members and maintainers
- permission levels such as `triage`, `write`, `maintain`, and `admin`

### 2. GitHub Activity Input

Contributor activity is fetched from the GitHub GraphQL API using:

- `src/hiero_analytics/data_sources/queries/`
- `src/hiero_analytics/data_sources/github_ingest.py`

The maintainer pipeline uses issue creation and PR lifecycle data:

- issue author
- PR author
- PR reviewer
- PR merger

Specifically, the current pipeline emits these activity types:

- `authored_issue`
- `authored_pull_request`
- `reviewed_pull_request`
- `merged_pull_request`

The default lookback window is:

- `183` days

So the pipeline measures **recent active participation**, not lifetime membership.

## Cache Layer

All GitHub fetches are cached on disk under:

- `outputs/cache/github/`

The cache layer is implemented in:

- `src/hiero_analytics/data_sources/cache.py`

Each cache filename includes:

- a cache kind such as `repo_contributor_activity` or `org_contributor_activity`
- a scope such as `hiero-ledger_awesome-contributions`
- a stable fingerprint derived from request parameters

Examples:

- `outputs/cache/github/repo_contributor_activity_hiero-ledger_awesome-contributions_d18f5b53d9d3.json`
- `outputs/cache/github/org_contributor_activity_hiero-ledger_c5618652d7df.json`

Each cache file stores:

- `kind`
- `scope`
- `parameters`
- `record_type`
- `cached_at`
- `records`

By default:

- cache is enabled
- TTL is 24 hours

Important note:

- The current maintainer pipeline still works correctly because the classification step explicitly filters to the issue creation and PR lifecycle types listed above.

## Step 1: Build Governance Role Lookup

The role mapping logic lives in:

- `src/hiero_analytics/data_sources/governance_config.py`

### Team-to-Repo Affinity

The governance file contains teams, but teams are not used globally for every repository.

Instead, the pipeline:

- tokenizes the repository name
- tokenizes the team name
- matches a team to the **most specific repository name prefix**

This creates a repo-scoped team affinity before any contributor is assigned a role.

### Permission-to-Role Mapping

Governance permissions are normalized to pipeline stages as follows:

- `triage` -> `triage`
- `write` -> `committer`
- `maintain` -> `maintainer`
- `admin` -> `maintainer`

### Member Extraction

For each matched team, the pipeline combines users from:

- `maintainers`
- `members`

Usernames are normalized case-insensitively.

### Highest Role Wins

If the same user appears more than once for the same repository, the highest role is kept:

- `general_user < triage < committer < maintainer`

The output of this step is effectively:

- `repo -> user -> highest governance role`

## Step 2: Fetch Contributor Activity

The contributor activity ingestion logic lives in:

- `src/hiero_analytics/data_sources/github_ingest.py`

### Org-Level Fetch

The org runner calls:

- `fetch_org_contributor_activity_graphql(client, org=ORG)`

That function:

1. fetches all repositories in the organization
2. scans repositories in parallel
3. calls the repo-level contributor activity fetcher for each repo
4. combines all normalized records into one org-level list

### Repo-Level Fetch

For each repository, the pipeline fetches pull requests ordered by `UPDATED_AT DESC` and issues ordered by `CREATED_AT DESC`.

For each issue or PR, it emits contributor activity records for:

- the issue author
- the PR author
- each reviewer
- the user who merged the PR

Each emitted record is normalized into a `ContributorActivityRecord`.

### Lookback Filtering

The repo fetcher applies the `183`-day cutoff at record creation time:

- issue authors are kept only if `createdAt >= cutoff`
- PR authors are kept only if `createdAt >= cutoff`
- reviewers are kept only if `submittedAt >= cutoff`
- mergers are kept only if `mergedAt >= cutoff`

Issue pagination stops early once a page contains issues created before the cutoff.

## Step 3: Convert Activity to Role-Labeled Events

This transformation lives in:

- `src/hiero_analytics/analysis/maintainer_pipeline.py`

For each activity record:

1. Keep only these activity types:
   - `authored_issue`
   - `authored_pull_request`
   - `reviewed_pull_request`
   - `merged_pull_request`
2. Extract the short repo name from `owner/repo`.
3. Normalize the actor login to lowercase.
4. Look up that actor in the repo-level governance role mapping.
5. If the actor is not found in governance for that repo, assign:
   - `general_user`

This produces the base fact table with columns:

- `repo`
- `actor`
- `year`
- `stage`

The saved output is:

- `outputs/data/org/<org>/maintainer_activity_events.csv`

This is the most important intermediate production artifact, because all final maintainer-pipeline outputs are derived from it.

## Step 4: Aggregate the Final Production Tables

The final production tables are built from `maintainer_activity_events.csv`.

### Yearly Pipeline

The yearly table groups by:

- `year`
- `stage`

Then it counts:

- unique `actor`

This means one person is counted once per year per stage, even if they performed many PR actions.

The saved output is:

- `outputs/data/org/<org>/maintainer_pipeline_yearly.csv`

### Repository Pipeline

The repository table groups by:

- `repo`
- `stage`

Then it counts:

- unique `actor`

This means one person is counted once per repository per stage.

The saved output is:

- `outputs/data/org/<org>/maintainer_pipeline_by_repo.csv`

### Important Counting Behavior

These are **unique contributor counts**, not event counts.

So:

- multiple PRs by the same person in the same repo and stage count once
- multiple reviews by the same person in the same repo and stage count once
- the same person can still appear in multiple repositories
- the same person can also appear in multiple stages if they hold different repo-scoped roles across repositories

Because of that:

- repo-level totals summed across repositories will usually be larger than org-level distinct-user totals

## Step 5: Render Charts

Charts are direct visualizations of the aggregated CSVs.

They are written to:

- `outputs/charts/org/<org>/maintainer_pipeline_yearly.png`
- `outputs/charts/org/<org>/maintainer_pipeline_by_repo.png`

The plotting code lives in:

- `src/hiero_analytics/plotting/bars.py`

There is no extra role logic in the chart step. The charts are visual renderings of the saved aggregated tables.

## Final Production Artifacts

For the maintainer pipeline, the final production outputs are:

- `outputs/data/org/<org>/maintainer_activity_events.csv`
- `outputs/data/org/<org>/maintainer_pipeline_yearly.csv`
- `outputs/data/org/<org>/maintainer_pipeline_by_repo.csv`
- `outputs/charts/org/<org>/maintainer_pipeline_yearly.png`
- `outputs/charts/org/<org>/maintainer_pipeline_by_repo.png`

### What Each Output Means

`maintainer_activity_events.csv`

- one row per normalized activity record after role assignment
- base dataset for the final pipeline outputs

`maintainer_pipeline_yearly.csv`

- unique active contributors by year and role stage

`maintainer_pipeline_by_repo.csv`

- unique active contributors by repository and role stage

The PNGs are simply charts derived from those CSVs.

## How Validation Was Derived

The validation artifacts compare the activity-based pipeline against governance-based truth counts.

Relevant output files include:

- `outputs/data/org/<org>/maintainer_pipeline_truth_by_repo.csv`
- `outputs/data/org/<org>/maintainer_pipeline_validation_comparison.csv`
- `outputs/data/org/<org>/maintainer_pipeline_validation_difference.csv`
- `outputs/data/org/<org>/maintainer_pipeline_validation_error.csv`
- `outputs/data/org/<org>/maintainer_pipeline_validation_summary.csv`

### Governance Truth Table

The truth table represents:

- the number of configured governance role holders per repository

This is derived from the same repo-level governance lookup by counting how many users hold:

- `triage`
- `committer`
- `maintainer`

for each repository.

### Predicted Table

The predicted table comes from:

- `maintainer_pipeline_by_repo.csv`

Those counts represent:

- how many unique people with qualifying PR activity were observed in each repo and stage during the lookback window

### Differences and Error

Validation then computes:

- predicted minus actual differences for each role
- squared error across the three roles per repository
- RMSE per repository

### Why Governance Counts Differ

This is expected.

The governance counts answer:

- who holds the role in config

The activity pipeline answers:

- who both holds the role and was recently active through issue creation or PR lifecycle events

So the governance count is usually larger, especially for:

- committers
- repositories with many configured role holders
- repos where not all role holders opened issues or authored, reviewed, or merged PRs in the lookback window

## Why This Methodology Was Chosen

This methodology was chosen because it is:

- **auditable**: every stage is backed by code and saved artifacts
- **repo-scoped**: roles are assigned per repository, not globally guessed
- **activity-aware**: it captures recent participation, not only nominal membership
- **reproducible**: identical parameters produce stable cached inputs and deterministic outputs
- **interpretable**: the final tables are simple unique-contributor counts by role stage

It is especially useful when the goal is to measure:

- active maintainership
- active governance participation
- contributor movement from general participation into governance roles

It is less suitable if the goal is to measure:

- total formal role holders regardless of recent activity

For that question, the governance truth table is the better metric.

## Practical Reading Guide

If you want to understand the maintainer pipeline quickly, read the artifacts in this order:

1. `outputs/data/org/<org>/maintainer_activity_events.csv`
2. `outputs/data/org/<org>/maintainer_pipeline_by_repo.csv`
3. `outputs/data/org/<org>/maintainer_pipeline_yearly.csv`
4. `outputs/data/org/<org>/maintainer_pipeline_truth_by_repo.csv`
5. `outputs/data/org/<org>/maintainer_pipeline_validation_comparison.csv`
6. `outputs/data/org/<org>/maintainer_pipeline_validation_summary.csv`

That order shows:

- the raw classified activity events
- the production rollups
- the governance truth baseline
- the comparison between the two

## Code References

- `src/hiero_analytics/run_maintainer_pipeline_org.py`
- `src/hiero_analytics/analysis/maintainer_pipeline.py`
- `src/hiero_analytics/data_sources/governance_config.py`
- `src/hiero_analytics/data_sources/github_ingest.py`
- `src/hiero_analytics/data_sources/queries/`
- `src/hiero_analytics/data_sources/cache.py`
- `src/hiero_analytics/export/save.py`
- `src/hiero_analytics/plotting/bars.py`
