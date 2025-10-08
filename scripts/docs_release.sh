#!/usr/bin/env bash
set -euo pipefail

git diff --quiet
version="${VERSION#v}"
mike deploy --update-aliases "$version" latest --push
if [[ "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  mike alias --update-aliases "$version" stable --push
fi
mike set-default latest --push
