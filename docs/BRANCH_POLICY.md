# Nexus branch policy

`main` is the released line. `develop` is the integration line and starts from
the current released commit. The company-system implementation is on
`feat/company-foundation`; it has not been merged or released.

| Branch | Purpose | Pull request target |
| --- | --- | --- |
| `feat/<name>` | Product or capability work | `develop` |
| `fix/<name>` | Bug fixes | `develop` |
| `docs/<name>` | Documentation | `develop` |
| `chore/<name>` | Maintenance and tooling | `develop` |
| `refactor/<name>` | Behavior-preserving restructuring | `develop` |
| `test/<name>` | Tests and qualification | `develop` |
| `perf/<name>` | Measured performance work | `develop` |
| `ci/<name>` | Build and workflow configuration | `develop` |
| `build/<name>` | Dependencies and packaging | `develop` |
| `hotfix/<name>` | Urgent corrections, integrated before release | `develop` |
| `release/<version>` | Release preparation | `develop` |
| `develop` | Reviewed integrated changes | `main` |

Names use lowercase letters/numbers with hyphen-separated words. Use Conventional
Commits. New work starts from current `develop`; keep a feature branch until its
PR is merged. Existing historical branches are not renamed solely for appearance.

Both long-lived branches require PRs, block deletion and block force pushes.
`main` requires one approving review, dismisses stale approvals, and requires
conversation resolution. `develop` requires conversation resolution without a
mandatory reviewer count. Both rulesets require the `Branch policy` status check.
A release PR into `main` comes only from `develop`.
GitHub's Branch policy check enforces PR source/target routing once its workflow
is present on the target branch; platform rulesets must be active separately.

CI and security checks run for PRs targeting either long-lived branch and pushes
to those branches. Publishing/deployment workflows retain their release triggers.
No branch operation itself approves a deployment, runtime activation or release.

Delete a merged branch after checking open PRs, worktrees and unique commits.
For squash merges, inspect the merged PR and patch correspondence before deleting;
ancestry alone is insufficient. Preserve unmerged/uncertain work. Record old names
and commit IDs; a Git bundle can preserve intentionally retired refs.

The owner's2026-10-15 policy authorizes remote publication of current development
commits. It does not authorize merging into `main`, release tags or deployment.

## Verified cleanup on2026-10-15

- Renamed active local/remote `feature/company-foundation` to
  `feat/company-foundation`, preserving commit654cd5c and all implementation history.
- Deleted local `chore/nexus-company-sdd`, which exactly matched released main.
- Deleted remote `claude/project-redesign-kafka-eval-oynl4a`, also exactly at main.
- Retained the54 other historical branches with commits outside main, including
  the branch for open draft PR27. An old date or prefix is not proof of disuse.
- Saved retired refs in a verified Git bundle under
  `/home/santapong/.codex/nexus-branch-cleanup-20261015/`.

Active GitHub rulesets: `main-release-policy`25138592 and
`develop-integration-policy`25138630. Both have empty bypass lists and target one
exact branch. `main` remains the repository's default and released branch.
