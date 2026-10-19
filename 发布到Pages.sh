#!/bin/bash
# 把最新页面同步到 docs/ 并推送到 GitHub Pages
# 用法：改完 榜单生成/output/ 里的页面后，双击或在终端运行本脚本
set -e
cd "$(dirname "$0")"

echo "同步 output -> docs ..."
rsync -a --delete --exclude 'images' 榜单生成/output/ docs/

echo "提交并推送 ..."
git add -A
if git diff --cached --quiet; then
  echo "没有变更，跳过提交"
else
  git commit -m "publish: 同步页面到 docs（$(date '+%Y-%m-%d %H:%M')）"
fi

git push origin main
echo "完成：https://vbncxm.github.io/dianping-jianzhen/"
