#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

"$DIR/rp" run "What is the capital of France?"
"$DIR/rp" run "Explain quantum computing in one sentence."
"$DIR/rp" run "Write a haiku about GPUs."
