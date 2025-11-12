#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终Canvas修复脚本 - 确保Chart.js和LightweightCharts完全销毁
"""

import re
import sys

def fix_canvas_issue(file_path):
    """修复Canvas重用问题"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 备份
    backup_path = file_path + '.canvas_final_backup'
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ 已备份到: {backup_path}")
    
    # 1. 修复updateChart函数 - 在销毁chart后，强制清空并重新创建canvas
    # 查找: if(chart){try{chart.destroy()}catch(e){console.warn('销毁chart失败:',e)}chart=null}
    # 之后紧接着: if(compareChart){try{compareChart.destroy()}...
    # 在两者之间插入canvas清理代码
    
    old_pattern1 = r"(if\(chart\)\{try\{chart\.destroy\(\)\}catch\(e\)\{console\.warn\('销毁chart失败:',e\)\}chart=null\})(if\(compareChart\))"
    new_replacement1 = r"\1const canvas=document.getElementById('pnlChartCanvas');if(canvas){const parent=canvas.parentElement;const newCanvas=document.createElement('canvas');newCanvas.id='pnlChartCanvas';parent.removeChild(canvas);parent.appendChild(newCanvas)}\2"
    
    content = re.sub(old_pattern1, new_replacement1, content)
    
    # 2. 修复loadPriceChart函数 - 确保在创建priceChart前完全清理
    # 查找: if(priceChart&&priceChart.remove){try{priceChart.remove()}catch(e){console.warn('销毁priceChart失败:',e)}priceChart=null}
    # 之后添加: const container=document.getElementById('pnlChart');if(container){const children=container.querySelectorAll('*');children.forEach(c=>c.remove())}
    
    old_pattern2 = r"(if\(priceChart&&priceChart\.remove\)\{try\{priceChart\.remove\(\)\}catch\(e\)\{console\.warn\('销毁priceChart失败:',e\)\}priceChart=null\})(try\{)"
    new_replacement2 = r"\1const tempContainer=document.getElementById('pnlChart');if(tempContainer){while(tempContainer.firstChild){tempContainer.removeChild(tempContainer.firstChild)}}\2"
    
    content = re.sub(old_pattern2, new_replacement2, content)
    
    # 写入修改后的内容
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ Canvas修复完成！")
    print("\n修改内容：")
    print("1. updateChart: 在销毁Chart.js后，物理删除并重新创建canvas元素")
    print("2. loadPriceChart: 在创建LightweightCharts前，完全清空容器")
    
    return True

if __name__ == '__main__':
    file_path = '/Users/mac-bauyu/Downloads/10-23-bot/每日壁纸更换.py'
    
    try:
        fix_canvas_issue(file_path)
        print("\n✅ 所有修复已完成！")
        print("\n📋 后续步骤：")
        print("1. 上传文件到服务器")
        print("2. 重启web服务: supervisorctl restart web")
        print("3. 清除浏览器缓存并刷新页面")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

