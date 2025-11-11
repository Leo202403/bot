#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "紧急回滚前端文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/pythonc程序/my_project || exit 1

echo "=== 1. 查找备份文件 ==="
ls -lht 每日壁纸更换.py.backup.* 2>/dev/null | head -5

BACKUP_FILE=$(ls -t 每日壁纸更换.py.backup.* 2>/dev/null | head -1)

if [ ! -z "$BACKUP_FILE" ]; then
    echo ""
    echo "✅ 找到最近备份：$BACKUP_FILE"
    echo ""
    
    echo "=== 2. 恢复备份 ==="
    cp "$BACKUP_FILE" 每日壁纸更换.py
    echo "✅ 已恢复备份"
    echo ""
    
    echo "=== 3. 重启web服务 ==="
    supervisorctl restart web
    echo ""
    
    echo "等待5秒..."
    sleep 5
    echo ""
    
    echo "=== 4. 检查服务状态 ==="
    supervisorctl status web
    echo ""
    
    echo "=== 5. 检查端口 ==="
    netstat -tlnp | grep gunicorn || ss -tlnp | grep gunicorn
    echo ""
    
    echo "✅ 回滚完成！请刷新浏览器测试"
else
    echo ""
    echo "❌ 未找到备份文件"
    echo ""
    echo "=== 当前目录所有备份 ==="
    ls -lh /root/pythonc程序/my_project/*.backup.* 2>/dev/null || echo "无备份"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
