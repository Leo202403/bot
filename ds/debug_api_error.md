# 前端500错误排查指南

## 问题分析

前端日志显示：
```
/trading-summary?model=qwen&range=week  Failed to load resource: the server responded with a status of 500 ()
/trading-summary?model=deepseek&range=week  Failed to load resource: the server responded with a status of 500 ()
```

**原因**: 后端API处理数据时发生异常，很可能是恢复订单后数据格式不完整导致。

## 排查步骤

### 步骤1: 查看后端日志

在服务器上执行：

```bash
# 查看Flask应用的日志
cd /root/10-23-bot
tail -100 nohup.out  # 或者你的日志文件

# 或者查看系统日志
journalctl -u trading-bot -n 100  # 如果配置了systemd服务

# 实时监控日志
tail -f nohup.out
```

### 步骤2: 手动测试API

```bash
# 测试API是否正常
curl http://localhost:5000/trading-summary?model=qwen&range=week

# 或者从外部测试
curl https://bitechain.site/trading-summary?model=qwen&range=week
```

### 步骤3: 检查恢复的订单数据

```bash
cd /root/10-23-bot/ds/trading_data/qwen

# 查看恢复的订单（最后一行）
tail -5 trades_history.csv

# 检查字段是否完整
head -1 trades_history.csv  # 查看表头
tail -1 trades_history.csv  # 查看最后一条数据
```

## 常见错误原因

### 1. 字段值为空或格式错误

**问题**: 恢复的订单中某些必需字段为空

**解决**: 删除有问题的订单记录

```bash
cd /root/10-23-bot/ds/trading_data/qwen

# 备份
cp trades_history.csv trades_history.csv.bak2

# 删除最后一行（恢复的订单）
sed -i '$d' trades_history.csv

# 重启后端
# (根据你的启动方式重启)
```

### 2. 字段数量不匹配

**问题**: 恢复的订单字段数与CSV表头不一致

**检查**:
```bash
# 统计表头字段数
head -1 trades_history.csv | awk -F',' '{print NF}'

# 统计最后一条记录字段数
tail -1 trades_history.csv | awk -F',' '{print NF}'

# 如果不一致，说明字段不匹配
```

**解决**: 同方法1，删除有问题的记录

### 3. 数值字段包含非数字

**问题**: 开仓价格、数量、杠杆等字段应为数字但包含文本

**检查**:
```bash
cd /root/10-23-bot/ds/trading_data/qwen
tail -1 trades_history.csv
```

查看恢复的记录中：
- `开仓价格` 是否为数字
- `数量` 是否为数字
- `杠杆` 是否为数字
- `盈亏(U)` 是否为空或数字

## 快速修复方案

### 方案1: 删除恢复的订单（推荐）

如果恢复的订单有问题且不重要（因为已经在 system_status.json 中）：

```bash
cd /root/10-23-bot/ds

# 从备份恢复
cp data_backup/20251120_160156/trades_history.csv trading_data/qwen/

# 只修正总资产，不恢复订单
python3 << 'EOF'
import json

# 修正qwen总资产
with open('trading_data/qwen/system_status.json', 'r', encoding='utf-8') as f:
    status = json.load(f)

status['总资产'] = 107.56
status['total_assets'] = 107.56

with open('trading_data/qwen/system_status.json', 'w', encoding='utf-8') as f:
    json.dump(status, f, ensure_ascii=False, indent=2)

print("✅ qwen总资产已更新为 107.56 U")

# 修正deepseek总资产
with open('trading_data/deepseek/system_status.json', 'r', encoding='utf-8') as f:
    status = json.load(f)

status['总资产'] = 101.93
status['total_assets'] = 101.93

with open('trading_data/deepseek/system_status.json', 'w', encoding='utf-8') as f:
    json.dump(status, f, ensure_ascii=False, indent=2)

print("✅ deepseek总资产已更新为 101.93 U")
EOF

# 重启后端服务
# (根据实际情况)
```

### 方案2: 手动修正恢复的订单

如果需要保留恢复的订单：

```bash
cd /root/10-23-bot/ds/trading_data/qwen

# 1. 查看恢复的订单内容
tail -1 trades_history.csv

# 2. 编辑最后一行，确保所有字段格式正确
vim trades_history.csv  # 或用其他编辑器

# 需要确保：
# - 所有字段与表头对应
# - 数值字段是数字格式
# - 时间字段格式正确
# - 空字段保持为空（不要填"null"或其他文本）
```

## 验证修复

修复后，重启后端并测试：

```bash
# 测试API
curl http://localhost:5000/trading-summary?model=qwen&range=week

# 检查响应
# 应该返回JSON数据，而不是500错误
```

## 获取详细错误信息

如果仍然无法解决，添加调试输出：

```bash
# 进入Python交互式环境测试
cd /root/10-23-bot/ds
python3 << 'EOF'
import csv
import json

# 测试读取qwen的数据
model = 'qwen'
data_dir = f'trading_data/{model}'

try:
    # 读取trades_history.csv
    with open(f'{data_dir}/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    
    print(f"✅ 成功读取 {len(trades)} 条交易记录")
    
    # 检查最后一条
    if trades:
        last_trade = trades[-1]
        print(f"\n最后一条记录:")
        for key, value in last_trade.items():
            print(f"  {key}: {value!r}")
        
        # 尝试转换数值字段
        try:
            pnl = float(last_trade.get('盈亏(U)', '0') or '0')
            print(f"\n✅ 盈亏字段可转换: {pnl}")
        except Exception as e:
            print(f"\n❌ 盈亏字段转换失败: {e}")
    
    # 读取system_status.json
    with open(f'{data_dir}/system_status.json', 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    print(f"\n✅ system_status.json:")
    print(f"  总资产: {status.get('总资产')}")
    print(f"  持仓数: {len(status.get('持仓详情', []))}")

except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
EOF
```

## 预防措施

1. **暂时跳过订单恢复**: 修改 `fix_data_integrity.py`，注释掉订单恢复部分
2. **仅修正总资产**: 总资产修正是安全的，订单恢复可以手动处理
3. **增强错误处理**: 后端API需要添加更好的异常捕获和日志

## 联系支持

如问题依然存在，提供以下信息：
1. 后端完整日志（最后100行）
2. `tail -5 trading_data/qwen/trades_history.csv` 输出
3. `trading_data/qwen/system_status.json` 内容

