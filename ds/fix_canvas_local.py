#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地Canvas问题修复脚本
"""

import re

def main():
    file_path = '每日壁纸更换.py'
    
    print("🔧 读取文件...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"✅ 文件大小: {len(content)} 字符\n")
    
    # 找到HTML字符串的位置
    html_start = content.find("return '''<!DOCTYPE html>")
    html_end = content.find("'''", html_start + 100)
    
    if html_start == -1 or html_end == -1:
        print("❌ 未找到HTML内容")
        return
    
    html_content = content[html_start:html_end]
    print(f"📄 HTML内容长度: {len(html_content)} 字符\n")
    
    # 修复1: updateChart函数 - 在获取ctx之前销毁Chart
    print("🔧 修复updateChart函数...")
    
    # 查找：async function updateChart(d){if(chartMode!=='pnl')return;if(!d?.pnl_24h&&!d?.status)return;try{const isMobile=
    # 替换为：添加销毁逻辑
    old_pattern1 = r"(async function updateChart\(d\)\{if\(chartMode!=='pnl'\)return;if\(!d\?\.pnl_24h&&!d\?\.status\)return;try\{)const isMobile="
    new_pattern1 = r"\1if(chart){try{chart.destroy()}catch(e){console.warn('销毁chart失败:',e)}chart=null}if(compareChart){try{compareChart.destroy()}catch(e){console.warn('销毁compareChart失败:',e)}compareChart=null}const isMobile="
    
    html_content = re.sub(old_pattern1, new_pattern1, html_content, count=1)
    print("✅ updateChart销毁逻辑已添加\n")
    
    # 修复2: 删除后面重复的chart.destroy()
    print("🔧 删除updateChart中重复的chart.destroy()...")
    
    # 查找：const ctx=canvas.getContext('2d');if(chart)chart.destroy();
    # 替换为：const ctx=canvas.getContext('2d');
    old_pattern2 = r"const ctx=canvas\.getContext\('2d'\);if\(chart\)chart\.destroy\(\);"
    new_pattern2 = r"const ctx=canvas.getContext('2d');"
    
    html_content = re.sub(old_pattern2, new_pattern2, html_content, count=1)
    print("✅ 重复的chart.destroy()已删除\n")
    
    # 修复3: loadPriceChart函数 - 在try块开始处销毁
    print("🔧 修复loadPriceChart函数...")
    
    # 查找：async function loadPriceChart(){if(chartMode!=='price')return;try{console.log
    # 替换为：添加销毁逻辑
    old_pattern3 = r"(async function loadPriceChart\(\)\{if\(chartMode!=='price'\)return;)try\{"
    new_pattern3 = r"\1if(priceChart&&priceChart.remove){try{priceChart.remove()}catch(e){console.warn('销毁priceChart失败:',e)}priceChart=null}try{"
    
    html_content = re.sub(old_pattern3, new_pattern3, html_content, count=1)
    print("✅ loadPriceChart销毁逻辑已添加\n")
    
    # 修复4: 删除loadPriceChart中后面重复的销毁
    print("🔧 删除loadPriceChart中重复的销毁逻辑...")
    
    # 查找：container.innerHTML='';if(priceChart&&priceChart.remove){priceChart.remove();priceChart=null}
    # 替换为：container.innerHTML='';
    old_pattern4 = r"container\.innerHTML='';if\(priceChart&&priceChart\.remove\)\{priceChart\.remove\(\);priceChart=null\}"
    new_pattern4 = r"container.innerHTML='';"
    
    html_content = re.sub(old_pattern4, new_pattern4, html_content, count=1)
    print("✅ 重复的priceChart销毁已删除\n")
    
    # 重新组装文件
    new_content = content[:html_start] + html_content + content[html_end:]
    
    # 备份原文件
    print("💾 备份原文件...")
    with open(file_path + '.canvas_local_backup', 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ 备份完成: {file_path}.canvas_local_backup\n")
    
    # 写入修复后的内容
    print("💾 保存修复后的文件...")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("✅ 文件已更新\n")
    
    print("=" * 60)
    print("✅ Canvas问题修复完成！")
    print("=" * 60)
    print("\n📋 修复内容:")
    print("  1. ✅ updateChart - 在获取ctx之前销毁Chart实例")
    print("  2. ✅ updateChart - 删除重复的chart.destroy()")
    print("  3. ✅ loadPriceChart - 在try块开始处销毁priceChart")
    print("  4. ✅ loadPriceChart - 删除重复的销毁逻辑")
    print("\n🚀 下一步:")
    print("  1. 本地测试确认修复正确")
    print("  2. 提交到GitHub: git add -A && git commit -m '修复Canvas重用问题'")
    print("  3. 推送到服务器: git push origin main")
    print("  4. 服务器拉取并重启: cd ~/10-23-bot && git pull && supervisorctl restart web")

if __name__ == '__main__':
    main()
