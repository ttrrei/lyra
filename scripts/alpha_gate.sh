#!/usr/bin/env bash
# alpha-in-git gate (lyra / B1 裁决 2026-11-14)
# ---------------------------------------------------------------
# 规则：lyra 的 git 里 strategies/ 只允许含 examples/（公开示例）。
# 一切真实 alpha —— directions/<family>/（vNN + hypothesis/lessons）与
# temp/（nova_campaign 等候选池）—— 一律只进 OCI、不进 git。
#
# 用途（同一逻辑，两条防线）：
#   * GitHub Actions CI（ci.yml "Alpha-in-git gate"）—— push/PR 时强制；
#   * 本地 pre-commit hook（scripts/git-hooks/pre-commit 调用本脚本）——
#     提交前拦截，防止 alpha 被误提交。
#
# 说明：这是"尽力拦网"，不是硬闸门。真正不可绕过的最后一道是 GitHub
# 的 branch protection（main 强制本检查为 required status check）——那
# 是仓库设置，需人工在 GitHub Settings → Branches 配置，见
# docs/review/overall-qwen-local-git-oci-边界对抗检查.md §F3。
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

# 只放行 examples/；其余 strategies/ 下的被跟踪文件都算违规。
bad="$(git ls-files 'strategies/' | grep -vE '^strategies/examples/' || true)"

if [ -n "$bad" ]; then
  echo "::error::alpha-gate FAIL — alpha strategy files tracked in git (must live in OCI only):"
  echo "$bad"
  echo "修复：git rm --cached <上面列出的文件>（留本地盘），并确认 .gitignore 不反包含。"
  exit 1
fi
echo "alpha-gate: OK — strategies/ in git contains only examples/"
