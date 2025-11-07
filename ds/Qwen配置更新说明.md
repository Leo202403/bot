# Qwen配置更新说明

**日期**: 2025-11-07  
**版本**: V8.3.14.1  
**用户反馈**: 同步脚本遗漏2处Qwen专属配置  

---

## 🔍 发现的问题

用户手动调整了Qwen配置，发现同步脚本有2处未处理：

### 1. 环境变量文件不同

**DeepSeek**: 使用 `.env`  
**Qwen**: 使用 `.env.qwen`

**影响**:
- Line 24-27: 环境变量文件路径检查
- Line 535: API Key 错误提示信息

### 2. 模型名称不同

**DeepSeek**: `deepseek-chat` / `deepseek-reasoner`  
**Qwen**: `qwen-plus` / `qwen3-max` (注意是 **qwen3-max** 而非 qwen-max)

**影响**: 约18处模型调用

---

## ✅ 已完成的修复

### 1. 更新同步脚本

**文件**: `完全同步deepseek到qwen.sh`

**新增 Step 3.8**: 替换.env文件路径
```bash
sed -i '' "s|'.env'|'.env.qwen'|g" qwen_多币种智能版.py
sed -i '' 's|"\.env"|".env.qwen"|g' qwen_多币种智能版.py
sed -i '' 's|找不到 \.env 文件|找不到 .env.qwen 文件|g' qwen_多币种智能版.py
sed -i '' 's|明确指定 \.env 文件路径|明确指定 .env.qwen 文件路径|g' qwen_多币种智能版.py
sed -i '' 's|请检查 \.env 文件|请检查 .env.qwen 文件|g' qwen_多币种智能版.py
```

**新增 Step 3.9**: 替换qwen-max为qwen3-max
```bash
sed -i '' 's/"qwen-max"/"qwen3-max"/g' qwen_多币种智能版.py
sed -i '' "s/'qwen-max'/'qwen3-max'/g" qwen_多币种智能版.py
```

---

### 2. 更新验证步骤

**修改前**:
```bash
echo "【验证2】qwen-plus/qwen-max数量:"
grep -c "qwen-plus\|qwen-max" qwen_多币种智能版.py
```

**修改后**:
```bash
echo "【验证2】qwen-plus/qwen3-max数量:"
echo "  qwen-plus: $(grep -c 'qwen-plus' qwen_多币种智能版.py)"
echo "  qwen3-max: $(grep -c 'qwen3-max' qwen_多币种智能版.py)"

echo "【验证5】.env.qwen配置:"
grep -c "\.env\.qwen" qwen_多币种智能版.py
```

---

### 3. 更新配置差异文档

**文件**: `Qwen_DeepSeek_配置差异说明.md`

**新增差异项**:

#### 环境变量文件（第2项）
| DeepSeek | Qwen |
|----------|------|
| `.env` | `.env.qwen` |

#### 模型名称（更新第3项）
| DeepSeek | Qwen |
|----------|------|
| `deepseek-chat` / `deepseek-reasoner` | `qwen-plus` / `qwen3-max` |

**总配置差异**: 9项 → **11项**

---

## 📊 配置差异完整列表（11项）

| # | 配置项 | DeepSeek | Qwen |
|---|--------|----------|------|
| 1 | API Client | `deepseek_client` | `qwen_client` |
| 2 | API Key | `DEEPSEEK_API_KEY` | `QWEN_API_KEY` |
| 3 | Base URL | `api.deepseek.com` | `dashscope.aliyuncs.com` |
| 4 | 模型名称 | `deepseek-chat` / `deepseek-reasoner` | `qwen-plus` / `qwen3-max` ⭐ |
| 5 | 环境文件 | `.env` | `.env.qwen` ⭐ |
| 6 | 配置路径 | `trading_data/deepseek/` | `trading_data/qwen/` |
| 7 | MODEL_NAME | `"deepseek"` | `"qwen"` |
| 8 | 邮件标识 | `[DeepSeek]` | `[通义千问]` |
| 9 | Bark分组 | `group=DeepSeek` | `group=Qwen` |
| 10 | 注释说明 | DeepSeek相关 | Qwen相关 |
| 11 | 错误提示 | 请检查.env | 请检查.env.qwen |

⭐ = 本次新增

---

## 🔧 使用更新后的同步脚本

```bash
cd ~/10-23-bot/ds

# 1. 修改deepseek
vim deepseek_多币种智能版.py

# 2. 运行更新后的同步脚本
bash 完全同步deepseek到qwen.sh

# 验证输出应包含：
# ✓ Step 3.8: 替换.env文件路径
# ✓ Step 3.9: 替换模型为qwen3-max
# ✓ 【验证2】qwen3-max: 18
# ✓ 【验证5】.env.qwen: 4
```

---

## 📝 注意事项

### 1. qwen3-max vs qwen-max

**重要**: Qwen使用的是 `qwen3-max` (带数字3)，不是 `qwen-max`

**原因**: qwen3-max是最新一代模型，性能更强

### 2. .env.qwen独立配置

**目的**: 避免API Key混用

**配置示例**:
```bash
# .env (DeepSeek)
DEEPSEEK_API_KEY=sk-xxx

# .env.qwen (Qwen)
QWEN_API_KEY=sk-xxx
DASHSCOPE_API_KEY=sk-xxx  # 别名
```

### 3. 手动调整vs自动同步

**当前情况**: 用户已手动调整qwen文件  
**未来建议**: 使用更新后的同步脚本，自动处理所有配置差异

---

## 🎯 预期效果

### 同步脚本输出

```bash
🔧 Step 3: 替换qwen专属配置...
  → 3.1 替换API初始化...
  → 3.2 替换client变量名...
  → 3.3 替换模型名称...
  → 3.4 替换配置路径...
  → 3.5 替换邮件标识...
  → 3.6 替换Bark标识...
  → 3.7 替换打印标识...
  → 3.8 替换.env文件路径...          ← 新增
  → 3.9 替换模型为qwen3-max...       ← 新增
✅ 配置替换完成

📊 Step 4: 验证替换结果...
【验证1】qwen_client数量: 19
【验证2】qwen-plus/qwen3-max数量:
  qwen-plus: 1                        ← 更新
  qwen3-max: 18                       ← 新增
【验证3】trading_data/qwen路径: 6
【验证4】通义千问标识: 27
【验证5】.env.qwen配置: 4            ← 新增
【验证6】检查残留的deepseek: 1
```

---

## 🚀 部署验证

### 检查qwen文件配置

```bash
cd ~/10-23-bot/ds

# 1. 验证环境变量文件
grep "\.env\.qwen" qwen_多币种智能版.py | head -3

# 2. 验证模型名称
grep "qwen3-max" qwen_多币种智能版.py | wc -l
# 应该输出: 18

# 3. 语法检查
python3 -m py_compile qwen_多币种智能版.py && echo "✅ OK"
```

### 运行测试

```bash
# 确保.env.qwen存在
ls -la .env.qwen

# 确保包含QWEN_API_KEY
grep QWEN_API_KEY .env.qwen

# 运行qwen
python3 qwen_多币种智能版.py
```

---

## 📈 改进总结

### 修复前

- ❌ 同步后qwen仍使用 `.env`
- ❌ 同步后qwen使用 `qwen-max` 而非 `qwen3-max`
- ⚠️ 需要手动调整这2处配置

### 修复后

- ✅ 自动替换为 `.env.qwen`
- ✅ 自动替换为 `qwen3-max`
- ✅ 完全自动化，无需手动调整

---

## 🎊 感谢

感谢用户的细心发现！这2处配置差异确实容易被忽略：

1. **.env.qwen**: 环境变量文件隔离很重要
2. **qwen3-max**: 模型版本号也是关键差异

现在同步脚本已完整处理**所有11项**配置差异，确保100%自动化。

---

**更新日期**: 2025-11-07  
**脚本版本**: V2.0（支持11项配置差异）  
**状态**: ✅ 已修复并测试  

---

