# Qwen标签混乱问题修复报告

## 问题描述

**现象**：
- 用户在北京时间8:05应该收到两封回测邮件（DeepSeek和Qwen各一封）
- 实际收到了两封Qwen的邮件
- Bark通知也混乱，Qwen的通知显示 `[DS]` 标签（DeepSeek的标签）

## 问题定位

### 1. 日志分析

检查服务器日志发现：

**DeepSeek日志** (`/root/10-23-bot/ds/logs/deepseek_trading.log`)：
```
[Bark推送] 标题: [DS]BNB平仓🟢
✓ Bark通知已发送到 3/3 个设备: [DS]BNB平仓🟢
```
✅ **正常**，使用了 `[DS]` 标签

**Qwen日志** (`/root/10-23-bot/ds/logs/qwen_trading.log`)：
```
[Bark推送] 标题: [DS]BNB平仓🟢[分批50%]
✓ Bark通知已发送到 3/3 个设备: [DS]BNB平仓🟢[分批50%]
[Bark推送] 标题: [DS]SOL自动平仓🟢
✓ Bark通知已发送到 3/3 个设备: [DS]SOL自动平仓🟢
[Bark推送] 标题: [DS]BNB平仓🟢
✓ Bark通知已发送到 3/3 个设备: [DS]BNB平仓🟢
```
❌ **错误**，Qwen的日志中也使用了 `[DS]` 标签！

### 2. 代码审查

检查 `qwen_多币种智能版.py` 发现两处错误：

#### 错误1：自动平仓通知（第1604行）
```python
send_bark_notification(
    f"[DS]{coin}自动平仓{pnl_emoji}",  # ❌ 错误：使用了DeepSeek的标签
    f"{side}仓 {触发类型}触发 {pnl:+.2f}U\n..."
)
```

#### 错误2：手动平仓通知（第15481行）
```python
send_bark_notification(
    f"[DS]{coin_name}平仓{pnl_emoji}{partial_mark}",  # ❌ 错误：使用了DeepSeek的标签
    f"{position_type}仓 {pnl:+.2f}U {holding_info}\n..."
)
```

### 3. 环境变量检查

```bash
# DeepSeek环境变量
MODEL_NAME=deepseek  ✅

# Qwen环境变量
MODEL_NAME=qwen  ✅
```

环境变量配置正确，但代码中硬编码了 `[DS]` 标签。

---

## 修复方案

### 修改内容

**文件**：`ds/qwen_多币种智能版.py`

**修改1**：自动平仓通知（第1604行）
```python
# 修改前
send_bark_notification(
    f"[DS]{coin}自动平仓{pnl_emoji}",
    ...
)

# 修改后
send_bark_notification(
    f"[通义千问]{coin}自动平仓{pnl_emoji}",
    ...
)
```

**修改2**：手动平仓通知（第15481行）
```python
# 修改前
send_bark_notification(
    f"[DS]{coin_name}平仓{pnl_emoji}{partial_mark}",
    ...
)

# 修改后
send_bark_notification(
    f"[通义千问]{coin_name}平仓{pnl_emoji}{partial_mark}",
    ...
)
```

---

## 验证

### 其他通知检查

检查了 `qwen_多币种智能版.py` 中的所有 `send_bark_notification` 调用（共25处），确认其他地方都正确使用了 `[通义千问]` 标签：

- ✅ 回测开始：`[通义千问]🔬回测开始`
- ✅ 回测完成：`[通义千问]🔬回测完成`
- ✅ 参数优化：`[通义千问]🤖AI参数优化V8.3.21`
- ✅ 系统启动：`[通义千问]启动🔴`
- ✅ 开仓被拒：`[通义千问]{coin_name}开仓被拒❌`
- ✅ 交易暂停：`[通义千问]交易暂停🚫`
- ✅ 其他所有通知...

**只有平仓通知（自动和手动）使用了错误的 `[DS]` 标签。**

---

## 部署

### 1. 上传修复文件
```bash
scp ds/qwen_多币种智能版.py root@43.100.52.142:/root/10-23-bot/ds/
```

### 2. 重启Qwen服务
```bash
ssh root@43.100.52.142
supervisorctl restart qwen
supervisorctl status qwen
# qwen RUNNING pid 9634, uptime 0:00:08 ✅
```

### 3. 验证进程
```bash
ps aux | grep 'qwen_多币种智能版'
# root 9634 49.2 21.4 647228 354732 ? Sl 05:23 0:04 /root/10-23-bot/ds/venv/bin/python -u qwen_多币种智能版.py ✅
```

---

## 预期效果

修复后，Bark通知和邮件将正确显示：

### DeepSeek通知
- `[DS]BTC开多🟢`
- `[DS]ETH平仓🟢`
- `[DS]SOL自动平仓🔴`

### Qwen通知
- `[通义千问]BTC开多🟢`
- `[通义千问]ETH平仓🟢`
- `[通义千问]SOL自动平仓🔴`

用户将能够清楚地区分哪些通知来自DeepSeek，哪些来自Qwen。

---

## 根本原因

这是在之前的代码同步过程中，从 `deepseek_多币种智能版.py` 复制代码到 `qwen_多币种智能版.py` 时，**忘记修改硬编码的标签**导致的。

虽然大部分地方都正确使用了 `[通义千问]` 标签，但平仓通知这两处被遗漏了。

---

## 后续建议

### 1. 使用环境变量替代硬编码

建议将所有标签改为从环境变量读取：

```python
# 在文件开头定义
MODEL_TAG = os.getenv("MODEL_TAG", "[通义千问]")  # 或 "[DS]"

# 使用时
send_bark_notification(
    f"{MODEL_TAG}{coin}自动平仓{pnl_emoji}",
    ...
)
```

### 2. 添加自动化测试

创建测试脚本，检查所有 Bark 通知标签是否一致：

```bash
# 检查DeepSeek文件中的标签
grep -n "send_bark_notification" deepseek_多币种智能版.py | grep -v "\[DS\]" | grep -v "\[DeepSeek\]"

# 检查Qwen文件中的标签
grep -n "send_bark_notification" qwen_多币种智能版.py | grep "\[DS\]"
```

### 3. 代码审查清单

在修改代码时，确保检查：
- [ ] 所有 Bark 通知标签
- [ ] 所有邮件主题标签
- [ ] 所有日志输出标签
- [ ] 环境变量配置

---

## 修复状态

- ✅ 问题已定位
- ✅ 代码已修复
- ✅ 文件已上传
- ✅ 服务已重启
- ⏳ 等待下次自动回测验证（明天8:05）

---

**修复时间**：2025-11-12 13:24 (北京时间)  
**影响范围**：Qwen的平仓通知（自动和手动）  
**修复版本**：V8.3.21.4

