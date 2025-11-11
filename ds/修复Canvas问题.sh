#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Canvas重用问题修复"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd /root/pythonc程序/my_project/

# 1. 备份
echo "1️⃣ 备份当前文件..."
cp 每日壁纸更换.py 每日壁纸更换.py.canvas_fix_backup
echo "✅ 备份完成: 每日壁纸更换.py.canvas_fix_backup"
echo ""

# 2. 修复Chart销毁逻辑
echo "2️⃣ 修复Chart销毁逻辑..."

# 找到并替换updateChart函数中的chart销毁部分
# 原代码：if(chart)chart.destroy();
# 新代码：if(chart){try{chart.destroy()}catch(e){}chart=null}if(compareChart){try{compareChart.destroy()}catch(e){}compareChart=null}const container=document.getElementById('pnlChart');if(container){while(container.firstChild){container.removeChild(container.firstChild)}const newCanvas=document.createElement('canvas');newCanvas.id='pnlChartCanvas';container.appendChild(newCanvas)}

sed -i 's/if(chart)chart\.destroy();/if(chart){try{chart.destroy()}catch(e){}chart=null}if(compareChart){try{compareChart.destroy()}catch(e){}compareChart=null}const container=document.getElementById('\''pnlChart'\'');if(container){while(container.firstChild){container.removeChild(container.firstChild)}const newCanvas=document.createElement('\''canvas'\'');newCanvas.id='\''pnlChartCanvas'\'';container.appendChild(newCanvas)}/g' 每日壁纸更换.py

echo "✅ Chart销毁逻辑已修复"
echo ""

# 3. 重启web服务
echo "3️⃣ 重启web服务..."
supervisorctl restart web

sleep 3
echo ""

# 4. 验证
echo "4️⃣ 验证服务状态..."
supervisorctl status web

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 修复完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 现在可以："
echo "   1. 清除浏览器缓存（Ctrl+Shift+R）"
echo "   2. 刷新页面"
echo "   3. 切换到价格图表测试"
echo ""
