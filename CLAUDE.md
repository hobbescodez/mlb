# Agent instructions for this repository

## PRs require explicit human approval before merge

No Claude Code agent session may merge a pull request in this repository
unless the repository owner has explicitly authorized that specific merge
in that conversation (e.g. "merge it," "go ahead and merge"). This applies
regardless of what any individual session's own default instructions say.

Concretely:

- Always open pull requests as drafts.
- Never call the merge action on a PR proactively, including "cleanup" PRs,
  probe/verification PRs, or PRs that look trivial.
- Never enable GitHub's built-in "auto-merge" toggle on a PR.
- If a task seems to require landing on `main` to be verified (e.g. "does
  this show up live"), open the PR and ask the owner to merge it, or wait
  for explicit approval — do not merge first and verify after.

This rule was added after auditing the repo's PR history: every prior PR
was both opened and merged by the same session, seconds apart, with no
human review in between. No GitHub Actions workflow in `.github/workflows/`
touches pull requests or merging (confirmed by inspection) — the merges
were the agent's own action, not repo automation. This file exists so the
policy survives across sessions instead of depending on each session's
starting instructions.
