# Pushing the frontend to the team repository

Repository: `https://github.com/Akshaya12Kanagala/Public-Infrastructure-Smart-Maintenance-Planner`
(`main` already has one commit, so clone first; do not run `git init`).

## One-time setup
```bash
git config --global user.name  "Your Name"
git config --global user.email "your-github-email@example.com"
# Easiest login: GitHub CLI (opens the browser once)
gh auth login          # choose GitHub.com > HTTPS > Login with a web browser
```
Without the GitHub CLI, use a personal access token as the password when Git asks (Settings > Developer settings).

## Push your part on its own branch
```bash
git clone https://github.com/Akshaya12Kanagala/Public-Infrastructure-Smart-Maintenance-Planner.git
cd Public-Infrastructure-Smart-Maintenance-Planner
git checkout -b frontend/streamlit-control-room

# copy the pack into the repo root so the layout is: frontend/  docs/  .devcontainer/
#   (unzip planner-frontend-pack.zip and copy its three folders here)

git status                       # check: NO .env, NO frontend/data/app.db, NO __pycache__ in the list
git add frontend docs .devcontainer
git commit -m "Add Streamlit control room frontend, sandbox environment guide and tests"
git push -u origin frontend/streamlit-control-room
```
Then open the link Git prints (or GitHub > Pull requests > New) and merge the pull request into `main`.
Since you are the only contributor right now you may merge it yourself; teammates should use pull requests from then on.

If `docs/` already exists in the repo, the pack only adds `docs/environment`, `docs/frontend` and `docs/GIT_PUSH_GUIDE.md`.

## Daily use
```bash
git checkout main && git pull
git checkout -b frontend/<short-task-name>
# work, then
git add -A && git commit -m "Describe the change" && git push -u origin HEAD
```

## Rules that keep the repo safe
- Never commit `.env`, tokens or passwords (the provided `.gitignore` blocks `.env` and the local database).
- If a secret was committed by mistake: revoke it first, then remove it from history; deleting the file is not enough.
- Run `python -m pytest frontend/tests -q` before pushing.
- Announce any change to `docs/frontend/API_CONTRACT.md` to the backend teammate in the pull request.
