#!/bin/bash
# 服务器Git问题诊断脚本

echo "==================== Git状态检查 ===================="
cd /root/10-23-bot
git status

echo ""
echo "==================== 当前分支和提交 ===================="
git log --oneline -3

echo ""
echo "==================== 远程仓库配置 ===================="
git remote -v

echo ""
echo "==================== 尝试拉取更新 ===================="
git fetch origin
git pull origin main

echo ""
echo "==================== 如果有冲突，查看冲突文件 ===================="
git diff --name-only --diff-filter=U

echo ""
echo "==================== Python缓存清理 ===================="
rm -rf ds/__pycache__
echo "✅ Python缓存已清理"

echo ""
echo "==================== 诊断完成 ===================="


