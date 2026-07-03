#!/usr/bin/env bash
# 兼容入口；与 apply_test_gemini_vertex.sh 相同
exec "$(dirname "$0")/apply_test_gemini_vertex.sh" "$@"
