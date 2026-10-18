What we're building: A GitHub Action that monitors a codebase, detects when code changes make documentation inaccurate, identifies the specific stale sections, and either auto-generates a PR with corrected docs or flags the discrepancies for human review.

Tech Stack: Python, GitHub Actions, with the ability to integrate with LLMs (e.g. OpenAI API) to generate documentation suggestions, and the GitHub API to create PRs.

Data Sources:git diff, git log, git blame, and LLMs to understand code changes and generate improved documentation.
