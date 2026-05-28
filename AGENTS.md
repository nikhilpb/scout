# Scout

A personal news agent (or team of agents) that collects information from the web and other sources on the user's behalf and summarizes it into a consumable format.

## Pull requests

When opening a PR, always check that CI passes before considering the work done. After pushing, watch the checks (e.g. `gh pr checks <n> --watch`) and fix any failures. Note that CI runs against a merge with the latest `main`, so a PR can fail even when tests pass locally if `main` has moved on — rebase onto `origin/main` and re-verify when that happens.
