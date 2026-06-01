# /implement-task

Full task implementation cycle: branch → implement → PR → review → merge.

## Usage

```
/implement-task <issueNumber>
```

Example: `/implement-task 42`

## Steps

Execute the following steps in strict order.

---

### Step 1 — Create branch from origin/main

Read the issue and save its content to pass to the coder agent:

```bash
gh issue view $ARGUMENTS
```

Derive a slug from the issue title (3–5 words, kebab-case, Latin only).
Create and switch to the branch:

```bash
git fetch origin
git checkout -b feat/<slug>-$ARGUMENTS origin/main
```

Use `fix/` prefix instead of `feat/` for bug fixes.

---

### Step 2 — Implement via coder agent

Invoke the `coder` agent to implement issue #$ARGUMENTS on the current branch.

Include in the agent prompt:
- The branch is already created — do not create a new one
- Implement the task fully: code + tests + documentation
- Create a PR with a Conventional Commits title and `closes #$ARGUMENTS` in the description
- **Do not merge the PR** — return the PR URL
- **Full issue text (include inline — coder must not re-fetch it via gh):**

```
<paste gh issue view output from Step 1>
```

---

### Step 3 — Code review via pr-reviewer agent

Get the PR diff to pass to the reviewer:

```bash
gh pr diff <PR_NUMBER>
```

Invoke the `pr-reviewer` agent.

Include in the agent prompt:
- PR URL
- Run every step in the checklist: ruff check, ruff format --check, pytest --cov, full checklist
- After review, post the verdict as a PR comment:
  - On approve: `gh pr review <PR_NUMBER> --approve --body "<review text>"`
  - On changes: `gh pr review <PR_NUMBER> --request-changes --body "<review text with issues>"`
- Return verdict: **APPROVED** or **CHANGES_REQUESTED** with list of issues
- **PR diff (include inline — reviewer must not read files via Read/Glob):**

```diff
<paste gh pr diff output>
```

---

### Step 4 — Iterate until APPROVED

If pr-reviewer returned **CHANGES_REQUESTED**:

1. Invoke the `coder` agent to fix all blocking issues in the same branch and push.
2. Return to Step 3.

Repeat until **APPROVED** from pr-reviewer.

---

### Step 5 — Check if docs/user_guide.md was changed

```bash
gh pr diff <PR_NUMBER> -- docs/user_guide.md
```

If output is **non-empty** (file changed) → go to Step 6.
If output is **empty** → go to Step 7.

---

### Step 6 — Product acceptance via product-manager agent

Get the user_guide diff to pass to the agent:

```bash
gh pr diff <PR_NUMBER> -- docs/user_guide.md
```

Invoke the `product-manager` agent.

Include in the agent prompt:
- Issue number: $ARGUMENTS
- PR URL
- Run product acceptance review: read issue #$ARGUMENTS via gh, compare agreed requirements against user_guide.md changes
- After review, post the verdict as a PR comment:
  - On approve: `gh pr review <PR_NUMBER> --approve --body "<review text>"`
  - On changes: `gh pr review <PR_NUMBER> --request-changes --body "<review text with gaps>"`
- Return verdict: **PRODUCT APPROVED** or **PRODUCT CHANGES REQUESTED** with list of gaps
- **Diff of `docs/user_guide.md` (include inline):**

```diff
<paste gh pr diff -- docs/user_guide.md output>
```

If product-manager returned **PRODUCT CHANGES REQUESTED**:

1. Invoke the `coder` agent to fix all product-manager issues and push.
2. Return to Step 3 (full review cycle: pr-reviewer → product-manager).

Repeat until **PRODUCT APPROVED**.

---

### Step 7 — Merge

After receiving all required approvals:
- **APPROVED** from pr-reviewer (mandatory)
- **PRODUCT APPROVED** from product-manager (only if `docs/user_guide.md` was changed)

```bash
gh pr merge <PR_NUMBER> --squash --delete-branch
```

If the issue was not closed automatically (via `closes #N` in the PR):

```bash
gh issue close $ARGUMENTS --comment "Implemented in PR #<PR_NUMBER>."
```

Report to the user: task #$ARGUMENTS is implemented and merged.
