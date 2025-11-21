#!/usr/bin/env python3
"""
同步 system_status.json 的中英文字段
确保后端 API 和交易机器人都能正常读写
"""

import json
import os
from datetime import datetime

# 字段映射：中文 -> 英文
FIELD_MAPPING = {
    '总资产': 'total_assets',
    'USDT余额': 'available_balance',
    '总仓位价值': 'position_margin'
}

def sync_status_file(file_path: str, model_name: str) -> bool:
    """同步单个 system_status.json 文件的字段"""
    print(f"\n{'='*50}")
    print(f"同步 {model_name} 配置文件")
    print(f"{'='*50}\n")
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    # 读取数据
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON格式错误: {e}")
        return False
    
    print(f"当前字段: {list(data.keys())}")
    
    # 同步中文 -> 英文
    updated = False
    for cn_field, en_field in FIELD_MAPPING.items():
        if cn_field in data and en_field not in data:
            data[en_field] = data[cn_field]
            print(f"✓ 同步: {cn_field} -> {en_field} = {data[en_field]}")
            updated = True
        elif cn_field in data and en_field in data:
            # 确保一致
            if data[en_field] != data[cn_field]:
                print(f"⚠️  字段不一致: {cn_field}={data[cn_field]}, {en_field}={data[en_field]}")
                data[en_field] = data[cn_field]
                print(f"   已更新为: {data[en_field]}")
                updated = True
    
    # 检查必需英文字段
    required_en_fields = {
        'total_assets': 1000.0,
        'initial_capital': 1000.0,
        'total_realized_pnl': 0.0,
        'unrealized_pnl': 0.0,
        'available_balance': 1000.0,
        'position_margin': 0.0
    }
    
    for field, default_value in required_en_fields.items():
        if field not in data:
            # 尝试从中文字段获取
            corresponding_cn_field: str | None = {v: k for k, v in FIELD_MAPPING.items()}.get(field)
            if corresponding_cn_field is not None and corresponding_cn_field in data:
                data[field] = data[corresponding_cn_field]
                print(f"✓ 从 {corresponding_cn_field} 获取: {field} = {data[field]}")
            else:
                data[field] = default_value
                print(f"⚠️  缺少字段 '{field}'，设为默认值: {default_value}")
            updated = True
    
    if updated:
        # 创建备份
        backup_path = file_path.replace('.json', f'_backup_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        with open(file_path, 'r', encoding='utf-8') as f:
            original = f.read()
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(original)
        print(f"\n✓ 已备份至: {backup_path}")
        
        # 保存更新
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("✓ 已保存更新")
        return True
    else:
        print("\n✓ 字段已同步，无需更新")
        return True

def main() -> None:
    print("="*50)
    print("🔄 同步 system_status.json 中英文字段")
    print("="*50)
    
    base_dir = "/root/10-23-bot/ds/trading_data"
    
    # 同步 DeepSeek
    deepseek_path = os.path.join(base_dir, "deepseek", "system_status.json")
    deepseek_ok = sync_status_file(deepseek_path, "DeepSeek")
    
    # 同步 Qwen
    qwen_path = os.path.join(base_dir, "qwen", "system_status.json")
    qwen_ok = sync_status_file(qwen_path, "Qwen")
    
    print("\n" + "="*50)
    print("📊 同步结果")
    print("="*50)
    
    if deepseek_ok and qwen_ok:
        print("✓ 所有文件同步完成")
        print("\n说明：")
        print("  - 中文字段：供交易机器人使用")
        print("  - 英文字段：供后端 API 使用")
        print("  - 两套字段会自动保持同步")
    else:
        print("❌ 部分文件同步失败")
    
    print("\n" + "="*50)

if __name__ == "__main__":
    main()

