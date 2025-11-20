# 从币安API恢复数据指南

## 概述

`restore_from_binance_papi.py` 工具可从币安**统一账户模式(Portfolio Margin API)**直接获取真实数据并恢复到本地。

### 优势

✅ **数据准确**: 直接从币安获取，避免本地计算错误  
✅ **自动匹配**: 自动匹配trades_history.csv的字段格式  
✅ **安全备份**: 恢复前自动备份原数据  
✅ **选择性恢复**: 可单独恢复DeepSeek或Qwen，或两者同时恢复

## 前提条件

### 1. 确认使用统一账户模式

在币安账户中确认已开通**统一账户(Portfolio Margin)**模式。

### 2. 环境变量配置

确保`.env.deepseek`文件中已配置币安API密钥：

```bash
# 币安API配置
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here

# 统一账户模式
USE_PORTFOLIO_MARGIN=true
```

### 3. 安装依赖

```bash
pip install ccxt python-dotenv
```

## 使用方法

### 快速开始

```bash
cd /root/10-23-bot/ds
python3 restore_from_binance_papi.py
```

### 执行流程

#### 步骤1: 获取账户数据

工具会自动获取：
- 总资产（包括未实现盈亏）
- 可用余额
- 钱包余额

示例输出：
```
📌 账户余额信息:
  总权益: 210.50 USDT
  可用余额: 98.23 USDT
  冻结余额: 112.27 USDT

💰 总资产详情:
  钱包余额: 207.45 USDT
  未实现盈亏: +3.05 USDT
  总资产: 210.50 USDT
```

#### 步骤2: 获取当前持仓

显示所有开仓持仓：
```
📋 当前持仓: 3 个

  BTC/USDT 多
    数量: 0.001
    开仓价: $92,000.00
    标记价: $93,500.00
    未实现盈亏: +1.50 USDT
    杠杆: 5x
    仓位价值: $93.50
```

#### 步骤3: 获取订单历史

获取所有支持的交易对的历史订单：
```
📜 获取订单历史...
  BTC/USDT:USDT: 150 笔订单
  ETH/USDT:USDT: 89 笔订单
  SOL/USDT:USDT: 64 笔订单
  ...
总计: 468 笔订单
```

#### 步骤4: 选择恢复模式

```
请选择恢复模式:
  1) 恢复 DeepSeek
  2) 恢复 Qwen
  3) 恢复两者（DeepSeek + Qwen）
  4) 仅查看数据，不恢复

请选择 [1-4]: 
```

#### 步骤5: 自动恢复

工具会：
1. **自动备份**原数据到`data_backup/before_binance_restore_YYYYMMDD_HHMMSS/`
2. **更新`system_status.json`**: 
   - 总资产
   - 可用余额
   - 未实现盈亏
   - 持仓详情
3. **更新`trades_history.csv`**:
   - 只添加缺失的持仓开仓记录
   - 不影响已有的历史交易记录

## 恢复内容

### system_status.json

更新字段：
```json
{
  "总资产": 210.50,
  "total_assets": 210.50,
  "USDT余额": 98.23,
  "usdt_balance": 98.23,
  "未实现盈亏": 3.05,
  "持仓详情": [
    {
      "币种": "BTC",
      "方向": "多",
      "数量": 0.001,
      "开仓价格": 92000.00,
      "当前价格": 93500.00,
      "杠杆": 5,
      "盈亏": 1.50,
      "仓位(U)": 93.50
    }
  ],
  "timestamp": "2025-11-20 18:00:00"
}
```

### trades_history.csv

只添加缺失的持仓开仓记录：

| 开仓时间 | 平仓时间 | 币种 | 方向 | 数量 | 开仓价格 | ... |
|---------|---------|------|------|------|----------|-----|
| 2025-11-20 15:30:00 | | BTC | 多 | 0.001 | 92000.00 | ... |

**注意**: 
- 已有的历史交易记录**不会被修改或删除**
- 只添加`system_status.json`中存在但`trades_history.csv`中缺失的持仓

## 字段映射

| 币安API字段 | system_status.json | trades_history.csv |
|------------|-------------------|-------------------|
| symbol | 币种 | 币种 |
| side (long/short) | 方向 (多/空) | 方向 (多/空) |
| contracts | 数量 | 数量 |
| entryPrice | 开仓价格 | 开仓价格 |
| leverage | 杠杆 / 杠杆率 | 杠杆率 |
| unrealizedPnl | 盈亏 | - |
| notional | 仓位(U) | 仓位(U) |

## 验证恢复结果

恢复后，验证数据：

```bash
# 1. 检查总资产
cd /root/10-23-bot/ds

python3 << 'EOF'
import json

for model in ['deepseek', 'qwen']:
    with open(f'trading_data/{model}/system_status.json', 'r') as f:
        status = json.load(f)
    print(f"{model}: 总资产 = {status.get('总资产', 0):.2f} USDT")
EOF

# 2. 检查持仓数
tail -5 trading_data/qwen/trades_history.csv

# 3. 测试前端API
curl http://localhost:5000/trading-summary?model=qwen&range=week
```

## 常见问题

### Q1: API返回错误

**可能原因**:
- API密钥配置错误
- 未开通统一账户模式
- API权限不足

**解决**: 
```bash
# 检查API配置
cat /root/10-23-bot/.env.deepseek | grep BINANCE

# 测试API连接
python3 << 'EOF'
import ccxt, os
from dotenv import load_dotenv

load_dotenv('/root/10-23-bot/.env.deepseek')
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
})
balance = exchange.fetch_balance()
print(f"连接成功! 总资产: {balance['total']['USDT']} USDT")
EOF
```

### Q2: 持仓数量不匹配

**正常情况**: 工具获取的是**当前实际持仓**，与本地记录可能有差异。

**处理**: 以币安API数据为准，这是最真实的数据。

### Q3: 订单历史不完整

**原因**: API默认只返回最近500笔订单。

**解决**: 修改脚本中的`limit`参数：
```python
orders = get_order_history(limit=1000)  # 增加限制
```

### Q4: 统一账户模式vs普通合约

本工具专为**统一账户模式**设计。如果使用普通合约账户，需修改：

```python
USE_PORTFOLIO_MARGIN = False  # 改为False
```

## 与原修正工具对比

| 特性 | fix_data_integrity.py | restore_from_binance_papi.py |
|-----|----------------------|------------------------------|
| 数据来源 | 本地CSV计算 | 币安API直接获取 |
| 准确性 | 依赖本地数据完整性 | ✅ 100%准确 |
| 订单恢复 | 从system_status推测 | ✅ 从币安订单历史获取 |
| 适用场景 | 本地数据轻微错误 | ✅ 数据严重丢失或不一致 |
| 网络要求 | 无 | 需要网络连接币安 |

## 安全注意事项

1. **API密钥安全**: 确保`.env.deepseek`文件权限为`600`
   ```bash
   chmod 600 /root/10-23-bot/.env.deepseek
   ```

2. **备份验证**: 恢复前检查备份是否成功
   ```bash
   ls -lh data_backup/before_binance_restore_*/
   ```

3. **只读操作**: 工具只**读取**币安数据，不会执行任何交易

## 高级用法

### 仅获取特定交易对

修改脚本中的`symbols`列表：

```python
symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']  # 只获取BTC和ETH
```

### 调试模式

查看详细API响应：

```bash
python3 restore_from_binance_papi.py 2>&1 | tee restore_debug.log
```

### 自动化恢复（跳过确认）

创建自动脚本：

```bash
#!/bin/bash
# auto_restore.sh
cd /root/10-23-bot/ds
echo "3" | python3 restore_from_binance_papi.py  # 选项3: 恢复两者
```

## 完整示例

```bash
# 1. 停止交易系统
killall python3

# 2. 运行恢复工具
cd /root/10-23-bot/ds
python3 restore_from_binance_papi.py

# 选择: 3 (恢复两者)

# 3. 验证结果
python3 << 'EOF'
import json
for model in ['deepseek', 'qwen']:
    with open(f'trading_data/{model}/system_status.json', 'r') as f:
        s = json.load(f)
    print(f"{model}: {s['总资产']:.2f} USDT, {len(s['持仓详情'])} 持仓")
EOF

# 4. 重启系统
cd /root/10-23-bot
nohup python3 每日壁纸更换.py > nohup.out 2>&1 &

# 5. 检查前端
curl http://localhost:5000/trading-summary?model=qwen&range=week | head -c 200
```

## 技术细节

### 币安统一账户API端点

工具使用的主要端点：
- `GET /papi/v1/balance` - 获取余额
- `GET /papi/v1/um/positionRisk` - 获取U本位持仓
- `GET /fapi/v1/allOrders` - 获取U本位合约订单历史

### CCXT库支持

使用`ccxt.binance`自动处理统一账户的API路由：
```python
exchange = ccxt.binance({
    "options": {
        "portfolioMargin": True  # 自动切换到papi端点
    }
})
```

## 故障排除

如果遇到问题：

1. **查看详细错误**:
   ```bash
   python3 restore_from_binance_papi.py 2>&1 | tee error.log
   ```

2. **手动测试API**:
   ```bash
   python3 -c "import ccxt; print(ccxt.binance().fetch_balance())"
   ```

3. **检查网络**:
   ```bash
   curl -I https://fapi.binance.com
   ```

4. **联系支持**: 提供`error.log`和账户配置(隐藏密钥)

## 总结

`restore_from_binance_papi.py` 是从币安直接恢复数据的最可靠方法，特别适用于：
- ✅ 本地数据严重不一致
- ✅ 订单记录大量丢失
- ✅ 需要100%准确的总资产
- ✅ 想以币安实际数据为准

