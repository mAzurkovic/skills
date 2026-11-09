---
name: verify
description: Black-box check that a feature does what its spec says. Writes expected inputs and outputs from the spec, deploys to a local or sandbox environment, calls the real thing (invoke a Lambda, send API requests, publish a message), and reports pass or fail per case. Changes no code. Use when user says "/verify", "verify this works", "test it for real", "deploy and check", or /implement-feature hands off a feature to check.
argument-hint: "[spec dir | feature name | what to verify]"
---

# /verify

Prove that the running system does what the spec says. You are not the builder. Do not trust the builder. Report results. Do not change code. You write only the suite in `verify/`.

## Rules

- Get the expected results from the spec. Write them before you look at the code.
- To learn how to run the system, read only: README, CLAUDE.md, deploy config (`template.yaml`, `serverless.yml`, CDK, Terraform), `docker-compose.yml`, `package.json` or `Makefile` scripts, route and handler names. Do not read the logic.
- Do not read the unit tests. Do not use their inputs. Use your own realistic values from the spec.
- Ignore notes and claims from the builder. Only the spec and the running system count.
- Never mark a case PASS if you did not run it.
- Never deploy to production or a shared environment.
- Open no visible windows. Use headless browsers. If a case needs a visible window or real input, do not run it. List it under `Not verified`, so that the user can do it.
- Call no paid or third-party service unless the spec needs it and you have approval. Use the smallest number of calls.
- Do not read or copy secrets files.
- Learn selectors, routes, and payload shapes from the running system (DOM, accessibility tree, HTTP responses), not from the source.

## Suite

The suite is the saved cases and the script that runs them. It lives in `verify/` next to tasks.md. You are the only one who writes it. It is not committed.

- `cases.md`: the spec hashes, how to start the environment, the run command, and the case table:
  ```
  # Verify cases: <feature>
  Spec: requirements.md <sha256, first 12 chars>, design.md <...>
  Env: <how to start it>
  Run: <one command>

  | # | Spec item | Case | Input | Expected |
  ```
  Get the hashes with `shasum -a 256`. Do not hash tasks.md. It changes when tasks are ticked.
- The run script: one file in the repo's language. It uses only installed dependencies. It starts the environment, runs the cases, cleans up, prints one line per case (`<#> PASS|FAIL <actual>`), and exits non-zero if a case fails. It takes case ids as arguments to run only those cases.
- Write run output (logs, screenshots) to a temp dir, never to `verify/`.

## Flow

1. **Read the spec.** Argument: spec dir, feature name, or a description. Default `./specs/<feature>/`: `requirements.md`, `design.md`, `tasks.md`. Feature of a milestone (`.../m<n>-<name>/f<k>-<name>/`): also its entry in `../../milestones.md`. Verify that feature, not the whole milestone. No spec, and the user runs you: write the expected behavior in one line and get approval.
   - `verify/cases.md` exists: do a **Rerun**. If not: continue at step 2.
2. **Find the surface.** List each deployable unit that the feature changes: Lambda, API route, service, worker, queue consumer, CLI command, UI page. None: verdict SKIP.
3. **Write the cases.** For each unit: the normal case, one invalid input, one error path, and each limit that the spec names (auth, empty, duplicate, retry, size). For each case write: input, expected status, expected body or fields, expected side effects (row, message, file, log line). Use exact values from the spec. Save them in `verify/cases.md` before you deploy.
4. **Select the environment.** Use what the repo has: `sam local`, LocalStack, `docker compose`, a dev server, a sandbox stack. Use local first. Use a sandbox cloud account only if local cannot run it.
5. **Get approval** before you deploy to a real cloud account, or do anything that costs money or sends real traffic (email, payments, SMS, third-party APIs).
   - The user runs you: ask once.
   - You are a subagent: do not deploy. Verdict BLOCKED, with what needs approval.
   - Your prompt already has the approval: continue.
6. **Deploy and call.** Lambda: deploy, then invoke it with a real event. API or service: send real requests (`curl`, `httpie`, the client SDK). Worker: publish a message, wait, check the result. UI: use it and check what it shows. Put each case in the run script as you make it work. At the end, run the full script once.
7. **Compare.** Compare each field. Read the logs for errors and warnings. Check the side effects in the store, queue, or bucket. A case passes only if all expected items match. The script checks the same items.
8. **Clean up.** Remove what you deployed or started, the test data that you wrote, and temp files your runs left. Check a path before you delete it, and delete only what this run made. Never delete `verify/`.

### Rerun

Do not derive the cases again. Do not explore again.

1. **Check the spec.** Compare the hashes in `cases.md` with the spec files. Changed: rewrite the cases for the changed spec items, update the script, and update the hashes.
2. **Add cases.** Your prompt can name spec items that a fix touched. If a case does not cover one, add a case to `cases.md` and the script.
3. **Run the script.** First the cases that failed last time (your prompt names them), then the full script. The approval rules of step 5 still apply.
4. **Script break.** If the script cannot find an element or route, look at the running system. The spec still holds with a different element: fix the script and list it under `Suite changes`. If not: the case is FAIL.
5. **Compare and clean up.** As in steps 7 and 8.

## Verdicts

| Verdict | When |
|---------|------|
| PASS | All cases ran and passed. |
| FAIL | One or more cases failed. |
| BLOCKED | You cannot run the cases: no environment, approval needed, or deploy fails for a reason outside the feature. |
| SKIP | No deployable unit changed. |

## Report

```
Verify: <feature>. Env: <local | sandbox name>. Suite: new, <n> cases | rerun, +<n> cases.

| # | Case | Request | Expected | Actual | Result |
|---|------|---------|----------|--------|--------|
| 1 | valid order | POST /orders {...} | 201, id set, row in orders | 201, id set, row in orders | PASS |
| 2 | no customer_id | POST /orders {} | 400, error names field | 500, stack trace | FAIL |

Failures:
2. No customer_id gives 500, not 400. Log: `TypeError: ... handler.py:42`. Spec: invalid input gives 400 with the field name.

Not verified:
- <case or unit not run, and why> | none

Spec gaps:
- <behavior that a case needs and the spec does not define> | none

Suite changes:
- <case added or script fixed, and why> | none

Verdict: PASS | FAIL (<n> of <m>) | BLOCKED (<reason>) | SKIP (<reason>)
```

For each failure, give the evidence: status, part of the body, log line, or missing side effect. Give one line about where it fails. Do not give a fix. The builder fixes it.
