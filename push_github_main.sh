#!/bin/bash
# S.K. Sharma & Co. — Push latest workspace code to GitHub `main` (for Live)
# Run ON THE VPS (or any machine with git). It downloads the freshest code
# bundle from the Emergent workspace, commits it and pushes to GitHub main.
#
# ── ONE-TIME SETUP ────────────────────────────────────────────────────
# 1. Create a GitHub repo (e.g. github.com/<you>/sksharma-portal)
# 2. Create a Personal Access Token: GitHub → Settings → Developer settings
#    → Personal access tokens → Fine-grained → repo "Contents: Read & write"
# 3. Fill the two variables below (or export them before running).
set -e

GITHUB_REPO="${GITHUB_REPO:-github.com/YOUR_USERNAME/YOUR_REPO}"   # <-- EDIT
GITHUB_TOKEN="${GITHUB_TOKEN:-ghp_XXXXXXXXXXXXXXXXXXXX}"           # <-- EDIT
GIT_NAME="SK Sharma Deploy Bot"
GIT_EMAIL="deploy@sksharma.local"

BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
WORK=/tmp/sks-git-push

echo "==> 1/5 Downloading latest code bundle from workspace..."
rm -rf "$WORK" && mkdir -p "$WORK/repo"
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/5 Cloning GitHub main..."
git clone --depth 1 --branch main "https://${GITHUB_TOKEN}@${GITHUB_REPO}.git" "$WORK/repo" 2>/dev/null \
  || (cd "$WORK/repo" && git init -b main && git remote add origin "https://${GITHUB_TOKEN}@${GITHUB_REPO}.git")

echo "==> 3/5 Replacing code (keeping .git, excluding secrets/heavy dirs)..."
cd "$WORK/repo"
find . -mindepth 1 -maxdepth 1 ! -name ".git" -exec rm -rf {} +
tar -xf /tmp/sks-latest.tar -C "$WORK/repo"
# never publish secrets or junk
rm -f backend/.env frontend/.env 2>/dev/null || true
rm -rf frontend/node_modules backend/__pycache__ test_reports 2>/dev/null || true
cat > .gitignore << 'GI'
node_modules/
__pycache__/
*.pyc
.env
.expo/
dist/
GI

echo "==> 4/5 Committing..."
git config user.name  "$GIT_NAME"
git config user.email "$GIT_EMAIL"
git add -A
git commit -m "Deploy $(date '+%Y-%m-%d %H:%M') — latest from Emergent workspace" || {
  echo "Nothing new to commit."; exit 0; }

echo "==> 5/5 Pushing to main..."
git push origin main
echo "✅ Pushed to https://${GITHUB_REPO} (main). Your live pipeline can now pull it."
