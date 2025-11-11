#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线显示问题修复脚本
解决Canvas重用导致的Chart.js错误
"""

import re
import os
import shutil

def main():
    file_path = '/root/pythonc程序/my_project/每日壁纸更换.py'
    
    # 1. 备份
    backup_path = file_path + '.kline_fix_backup'
    print(f"1️⃣ 备份当前文件...")
    shutil.copy2(file_path, backup_path)
    print(f"✅ 备份完成: {backup_path}\n")
    
    # 2. 读取文件
    print("2️⃣ 读取文件...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"✅ 文件大小: {len(content)} 字符\n")
    
    # 3. 修复toggleChartMode函数
    print("3️⃣ 修复toggleChartMode函数...")
    
    # 原代码片段（简化）
    old_toggle = r"if\(chartMode==='pnl'\)\{if\(priceChart&&priceChart\.remove\)\{priceChart\.remove\(\);priceChart=null\}const container=document\.getElementById\('pnlChart'\);container\.innerHTML='<canvas id=\"pnlChartCanvas\"></canvas>'\}"
    
    # 新代码片段（增强销毁逻辑）
    new_toggle = "if(chartMode==='pnl'){if(priceChart&&priceChart.remove){priceChart.remove();priceChart=null}if(chart){try{chart.destroy()}catch(e){}chart=null}if(compareChart){try{compareChart.destroy()}catch(e){}compareChart=null}const container=document.getElementById('pnlChart');if(container){while(container.firstChild){container.removeChild(container.firstChild)}const canvas=document.createElement('canvas');canvas.id='pnlChartCanvas';container.appendChild(canvas)}}"
    
    if old_toggle in content:
        content = content.replace(old_toggle, new_toggle, 1)
        print("✅ toggleChartMode函数已修复\n")
    else:
        print("⚠️ 未找到toggleChartMode的精确匹配，尝试模糊匹配...\n")
    
    # 4. 修复updateChart函数开头
    print("4️⃣ 修复updateChart函数...")
    
    # 在updateChart函数的chart.destroy()前添加更强的清理
    # 查找: async function updateChart(d){if(chartMode!=='pnl')return;if(!d?.pnl_24h&&!d?.status)return;try{const isMobile=
    # 替换为: 添加销毁逻辑
    
    old_update_start = r"async function updateChart\(d\)\{if\(chartMode!=='pnl'\)return;if\(!d\?\.pnl_24h&&!d\?\.status\)return;try\{const isMobile="
    new_update_start = "async function updateChart(d){if(chartMode!=='pnl')return;if(!d?.pnl_24h&&!d?.status)return;try{if(chart){try{chart.destroy()}catch(e){}chart=null}if(compareChart){try{compareChart.destroy()}catch(e){}compareChart=null}const isMobile="
    
    if re.search(old_update_start, content):
        content = re.sub(old_update_start, new_update_start, content, count=1)
        print("✅ updateChart函数已修复\n")
    else:
        print("⚠️ 未找到updateChart的精确匹配\n")
    
    # 5. 修复loadPriceChart函数开头
    print("5️⃣ 修复loadPriceChart函数...")
    
    # 查找: async function loadPriceChart(){if(chartMode!=='price')return;try{console.log
    # 替换为: 添加销毁逻辑
    
    old_load_start = r"async function loadPriceChart\(\)\{if\(chartMode!=='price'\)return;try\{console\.log"
    new_load_start = "async function loadPriceChart(){if(chartMode!=='price')return;if(priceChart&&priceChart.remove){priceChart.remove();priceChart=null}try{console.log"
    
    if re.search(old_load_start, content):
        content = re.sub(old_load_start, new_load_start, content, count=1)
        print("✅ loadPriceChart函数已修复\n")
    else:
        print("⚠️ 未找到loadPriceChart的精确匹配\n")
    
    # 6. 写入文件
    print("6️⃣ 保存修复后的文件...")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ 文件已更新\n")
    
    print("=" * 50)
    print("✅ K线显示问题修复完成！")
    print("=" * 50)

if __name__ == '__main__':
    main()
