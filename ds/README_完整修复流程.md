# 完整修复流程

## 问题症状

1. **前端不显示 DeepSeek 订单**（Qwen 正常）
2. **API 返回 500 错误**
3. **后端启动失败**：`ModuleNotFoundError: No module named 'flask'`

## 根本原因

### 1. 后端依赖缺失
- 虚拟环境中缺少 Flask 等必需模块
- 导致后端无法启动

### 2. 配置文件字段不匹配
- `system_status.json` 只有中文字段（`总资产`）
- 后端 API 需要英文字段（`total_assets`）
- 导致 API 读取失败

## 完整修复步骤

### 步骤 1：更新代码

```bash
cd /root/10-23-bot && git pull
```

### 步骤 2：修复后端依赖

```bash
cd ds
chmod +x fix_backend_deps.sh
./fix_backend_deps.sh
```

**这个脚本会：**
- 检查虚拟环境是否存在
- 检查并安装 Flask、ccxt、python-dotenv 等依赖
- 验证所有必需模块

### 步骤 3：同步配置文件字段

```bash
python3 sync_status_fields.py
```

**这个脚本会：**
- 从中文字段（`总资产`）同步到英文字段（`total_assets`）
- 确保两套字段数据一致
- 补充缺失的必需字段

### 步骤 4：重启后端服务

```bash
./restart_backend.sh
```

### 步骤 5：测试 API

```bash
./test_api.sh
```

**期望结果：**
```
✓ 后端进程运行中
✓ DeepSeek API: 200 OK
✓ Qwen API: 200 OK
```

### 步骤 6：刷新前端页面

在浏览器中刷新页面，DeepSeek 订单应该正常显示。

## 字段说明

### 为什么需要两套字段？

1. **中文字段**（`总资产`、`USDT余额` 等）
   - 由交易机器人（`deepseek_多币种智能版.py`）写入
   - 用于机器人内部逻辑

2. **英文字段**（`total_assets`、`available_balance` 等）
   - 由后端 API（`每日壁纸更换.py`）读取
   - 用于前端展示

3. **同步机制**
   - `sync_status_fields.py` 确保两套字段数据一致
   - 机器人更新中文字段后，需手动运行同步脚本
   - 或在机器人代码中同时写入两套字段

### 字段映射表

| 中文字段 | 英文字段 | 说明 |
|---------|---------|------|
| 总资产 | total_assets | 账户总资产（USDT） |
| USDT余额 | available_balance | 可用余额 |
| 总仓位价值 | position_margin | 保证金占用 |
| - | initial_capital | 初始资金 |
| - | total_realized_pnl | 已实现盈亏 |
| - | unrealized_pnl | 未实现盈亏 |

## 常见问题

### Q1: 修复后前端仍不显示订单？

**检查点：**
```bash
# 1. 查看后端日志
tail -50 /root/pythonc程序/my_project/nohup.out

# 2. 测试 API
./test_api.sh

# 3. 检查配置文件
./check_system_status.sh
```

### Q2: 后端启动后立即退出？

**可能原因：**
- Python 语法错误
- 依赖版本不兼容
- 端口被占用

**诊断：**
```bash
# 查看详细错误
cat /root/pythonc程序/my_project/nohup.out

# 手动测试启动
cd /root/pythonc程序/my_project
source venv/bin/activate
python3 每日壁纸更换.py
```

### Q3: Qwen 显示正常，DeepSeek 不显示？

**对比检查：**
```bash
# 检查文件是否存在
ls -la /root/10-23-bot/ds/trading_data/deepseek/
ls -la /root/10-23-bot/ds/trading_data/qwen/

# 对比字段
python3 << 'EOF'
import json

# DeepSeek
with open('/root/10-23-bot/ds/trading_data/deepseek/system_status.json', 'r') as f:
    ds_data = json.load(f)
    print("DeepSeek 字段:", list(ds_data.keys()))

# Qwen
with open('/root/10-23-bot/ds/trading_data/qwen/system_status.json', 'r') as f:
    qw_data = json.load(f)
    print("Qwen 字段:", list(qw_data.keys()))
EOF
```

## 预防措施

### 1. 定期备份

```bash
# 每次修改前自动备份
cp trading_data/deepseek/system_status.json \
   trading_data/deepseek/system_status_$(date +%Y%m%d_%H%M%S).json
```

### 2. 监控脚本

创建定时任务，每小时同步字段：

```bash
# 添加到 crontab
0 * * * * cd /root/10-23-bot/ds && python3 sync_status_fields.py >> /tmp/sync.log 2>&1
```

### 3. 统一字段名

**长期方案：** 修改交易机器人和后端 API，统一使用英文字段名。

## 维护建议

1. **每次从币安恢复数据后**
   ```bash
   ./一键从币安恢复.sh
   python3 sync_status_fields.py
   ./restart_backend.sh
   ```

2. **每次手动修改配置后**
   ```bash
   python3 sync_status_fields.py
   ./restart_backend.sh
   ```

3. **定期检查**
   ```bash
   ./test_api.sh
   ```

## 技术细节

### system_status.json 结构示例

```json
{
  "更新时间": "2025-11-21 03:18:00",
  "USDT余额": 1050.23,
  "总资产": 1050.23,
  "总仓位价值": 0,
  "最大仓位限制": 800,
  "当前持仓数": 0,
  "total_assets": 1050.23,
  "initial_capital": 1000.0,
  "total_realized_pnl": 50.23,
  "unrealized_pnl": 0,
  "available_balance": 1050.23,
  "position_margin": 0,
  "持仓详情": [],
  "市场概况": {},
  "AI分析": "",
  "风险评估": ""
}
```

### 后端 API 读取逻辑

```python
# 每日壁纸更换.py
def generate_trading_summary(model):
    status_file = f"trading_data/{model}/system_status.json"
    with open(status_file, 'r') as f:
        status = json.load(f)
    
    # 后端需要这些英文字段
    total_assets = status['total_assets']  # 如果缺失，会抛出 KeyError
    initial_capital = status['initial_capital']
    # ...
```

## 相关文档

- [从币安恢复数据](README_从币安恢复数据.md)
- [订单格式问题修复](README_订单格式问题修复.md)
- [数据修正说明](数据修正说明.md)
- [账户配置说明](账户配置说明.md)

