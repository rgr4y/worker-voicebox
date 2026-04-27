#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Test 1: Creative writing ==="
"$DIR/rp" chat "Write a short story about a robot discovering music for the first time. 2-3 paragraphs."
echo ""

echo "=== Test 2: Technical explanation ==="
"$DIR/rp" chat "Explain how GPUs accelerate neural network training compared to CPUs. Be detailed, 2-3 paragraphs."
echo ""

echo "=== Test 3: Persuasive argument ==="
"$DIR/rp" chat "Make a compelling case for why humanity should prioritize deep ocean exploration over Mars colonization. 2-3 paragraphs."
echo ""
