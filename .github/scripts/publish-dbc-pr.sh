#!/usr/bin/env bash
# Publish the staged, tested tree without rebasing it onto a moving base branch.
set -euo pipefail

repository_dir=$1
github_repository=$2
base_branch=$3
title=$4
body_file=$5
branch=automation/dbc-regeneration

if ! git -C "$repository_dir" diff --cached --quiet; then
  git -C "$repository_dir" -c user.name='github-actions[bot]' \
    -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    -c core.hooksPath=/dev/null commit -m "$title"
  # Lease the branch explicitly, including the case where it does not exist.
  previous_sha=$(git -C "$repository_dir" ls-remote --heads origin "refs/heads/$branch" | cut -f1)
  git -C "$repository_dir" push \
    "--force-with-lease=refs/heads/$branch:$previous_sha" origin "HEAD:refs/heads/$branch"
  number=$(gh pr list --repo "$github_repository" --head "$branch" --base "$base_branch" \
    --state open --json number --jq '.[0].number // empty')
  if [ -n "$number" ]; then
    url=$(gh pr edit "$number" --repo "$github_repository" --title "$title" --body-file "$body_file")
  else
    url=$(gh pr create --repo "$github_repository" --head "$branch" --base "$base_branch" \
      --title "$title" --body-file "$body_file")
  fi
  echo "url=$url" >> "$GITHUB_OUTPUT"
fi
echo "sha=$(git -C "$repository_dir" rev-parse HEAD)" >> "$GITHUB_OUTPUT"
