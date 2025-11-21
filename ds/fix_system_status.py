#!/usr/bin/env python3
"""
修复 system_status.json 文件，确保包含所有必需字段
"""

import json
import os
from datetime import datetime

def fix_status_file(file_path, model_name):
    """修复单个 system_status.json 文件"""
    print(f"\n{'='*50}")
    print(f"修复 {model_name} 配置文件")
    print(f"{'='*50}\n")
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    # 创建备份
    backup_path = file_path.replace('.json', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    with open(file_path, 'r', encoding='utf-8') as f:
        original_data = f.read()
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(original_data)
    print(f"✓ 已备份至: {backup_path}")
    
    # 读取当前数据
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON格式错误: {e}")
        return False
    
    print(f"当前字段: {list(data.keys())}")
    
    # 定义必需字段及默认值
    required_fields = {
        'total_assets': 0.0,
        'initial_capital': 1000.0,
        'total_realized_pnl': 0.0,
        'unrealized_pnl': 0.0,
        'available_balance': 0.0,
        'position_margin': 0.0
    }
    
    # 检查并补充缺失字段
    updated = False
    for field, default_value in required_fields.items():
        if field not in data:
            print(f"⚠️  缺少字段 '{field}'，将设为默认值: {default_value}")
            data[field] = default_value
            updated = True
        else:
            print(f"✓ 字段 '{field}' 存在，值为: {data[field]}")
    
    # 特殊处理：如果 total_assets 为 0，尝试从其他字段计算
    if data['total_assets'] == 0 and (data['total_realized_pnl'] != 0 or data['unrealized_pnl'] != 0):
        calculated_assets = data['initial_capital'] + data['total_realized_pnl'] + data['unrealized_pnl']
        print("\n⚠️  total_assets 为 0，根据其他字段计算:")
        print(f"   初始资金: {data['initial_capital']}")
        print(f"   已实现盈亏: {data['total_realized_pnl']}")
        print(f"   未实现盈亏: {data['unrealized_pnl']}")
        print(f"   计算结果: {calculated_assets}")
        
        response = input(f"\n是否使用计算值 {calculated_assets} 作为 total_assets? (y/n): ")
        if response.lower() == 'y':
            data['total_assets'] = calculated_assets
            updated = True
    
    if updated:
        # 保存修复后的数据
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("\n✓ 已保存修复后的文件")
        return True
    else:
        print("\n✓ 文件无需修复")
        return True

def main():
    print("="*50)
    print("🔧 修复 system_status.json 文件")
    print("="*50)
    
    base_dir = "/root/10-23-bot/ds/trading_data"
    
    # 修复 DeepSeek
    deepseek_path = os.path.join(base_dir, "deepseek", "system_status.json")
    deepseek_ok = fix_status_file(deepseek_path, "DeepSeek")
    
    # 修复 Qwen
    qwen_path = os.path.join(base_dir, "qwen", "system_status.json")
    qwen_ok = fix_status_file(qwen_path, "Qwen")
    
    print("\n" + "="*50)
    print("📊 修复结果")
    print("="*50)
    
    if deepseek_ok and qwen_ok:
        print("✓ 所有文件修复完成")
        print("\n建议操作：")
        print("  1. 重启后端服务: cd /root/10-23-bot/ds && ./restart_backend.sh")
        print("  2. 再次测试API: ./test_api.sh")
    else:
        print("❌ 部分文件修复失败，请检查错误信息")

if __name__ == "__main__":
    main()

