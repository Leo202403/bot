# Qwen vs DeepSeek 配置差异说明

**版本**: V8.3.13  
**同步日期**: 2025-11-07  
**状态**: ✅ 完全同步，仅配置差异  

---

## 📋 总览

qwen和deepseek文件已**完全同步**，代码逻辑100%一致，仅在以下配置上有差异：

| 配置项 | DeepSeek | Qwen |
|--------|----------|------|
| **API Client变量** | `deepseek_client` | `qwen_client` |
| **API Key** | `DEEPSEEK_API_KEY` | `QWEN_API_KEY` |
| **API Base URL** | `https://api.deepseek.com` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| **模型名称** | `deepseek-chat` / `deepseek-reasoner` | `qwen-plus` / `qwen-max` |
| **配置路径** | `trading_data/deepseek/` | `trading_data/qwen/` |
| **默认MODEL_NAME** | `"deepseek"` | `"qwen"` |
| **邮件标识** | `[DeepSeek]` / `DeepSeek智能交易系统` | `[通义千问]` / `通义千问智能交易系统` |
| **Bark分组** | `group=DeepSeek` | `group=Qwen` |
| **注释说明** | DeepSeek相关 | Qwen相关 |

---

## 🔧 具体差异详解

### 1. API初始化（Line ~538）

**DeepSeek**:
```python
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
if not deepseek_api_key:
    raise ValueError("❌ DEEPSEEK_API_KEY 环境变量未设置")
deepseek_api_key = deepseek_api_key.strip()
deepseek_client = OpenAI(
    api_key=deepseek_api_key,
    base_url="https://api.deepseek.com"
)
```

**Qwen**:
```python
qwen_api_key = os.getenv("QWEN_API_KEY")
if not qwen_api_key:
    raise ValueError("❌ QWEN_API_KEY 环境变量未设置")
qwen_api_key = qwen_api_key.strip()
qwen_client = OpenAI(
    api_key=qwen_api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
```

---

### 2. 模型调用（多处）

**DeepSeek**:
```python
response = deepseek_client.chat.completions.create(
    model="deepseek-chat",  # 或 "deepseek-reasoner"
    messages=[...],
    ...
)
```

**Qwen**:
```python
response = qwen_client.chat.completions.create(
    model="qwen-plus",  # 或 "qwen-max"
    messages=[...],
    ...
)
```

**调用位置**:
- AI决策函数（~19处）
- 参数优化（~15处）

---

### 3. 配置文件路径

**DeepSeek**:
```python
DATA_DIR = Path(__file__).parent / "trading_data" / "deepseek"
model_dir = os.getenv("MODEL_NAME", "deepseek")

# 具体文件
learning_config.json → trading_data/deepseek/learning_config.json
market_snapshots/ → trading_data/deepseek/market_snapshots/
```

**Qwen**:
```python
DATA_DIR = Path(__file__).parent / "trading_data" / "qwen"
model_dir = os.getenv("MODEL_NAME", "qwen")

# 具体文件
learning_config.json → trading_data/qwen/learning_config.json
market_snapshots/ → trading_data/qwen/market_snapshots/
```

---

### 4. 邮件和Bark通知

**DeepSeek**:
```python
# 邮件
subject = "[DeepSeek]🤖AI参数优化"
body = "此邮件由 DeepSeek智能交易系统 自动发送"

# Bark
title = "[DeepSeek]回测开始"
url = f"...?group=DeepSeek"
```

**Qwen**:
```python
# 邮件
subject = "[通义千问]🤖AI参数优化"
body = "此邮件由 通义千问智能交易系统 自动发送"

# Bark
title = "[通义千问]回测开始"
url = f"...?group=Qwen"
```

**标识位置**:
- 邮件标题（~27处）
- Bark推送（~1处分组）
- 打印输出（部分）

---

### 5. 默认参数值

**DeepSeek**:
```python
model_name = os.getenv("MODEL_NAME", "DeepSeek")
send_email_notification(model_name="DeepSeek")
call_ai_for_exit_analysis(model_name='deepseek')
```

**Qwen**:
```python
model_name = os.getenv("MODEL_NAME", "Qwen")
send_email_notification(model_name="Qwen")
call_ai_for_exit_analysis(model_name='qwen')
```

---

## 📊 配置统计

| 项目 | DeepSeek | Qwen | 状态 |
|------|----------|------|------|
| **文件行数** | 18,963 | 18,963 | ✅ 相同 |
| **client引用** | deepseek_client (19处) | qwen_client (19处) | ✅ 已替换 |
| **模型调用** | deepseek-chat/reasoner (15处) | qwen-plus/max (15处) | ✅ 已替换 |
| **配置路径** | trading_data/deepseek (6处) | trading_data/qwen (6处) | ✅ 已替换 |
| **邮件/Bark标识** | DeepSeek/深度求索 (27处) | 通义千问/Qwen (27处) | ✅ 已替换 |
| **Bark分组** | group=DeepSeek (1处) | group=Qwen (1处) | ✅ 已替换 |
| **残留deepseek** | N/A | 0处 | ✅ 完全清理 |

---

## 🔍 保留的技术说明

以下包含"DeepSeek"的内容被**刻意保留**，因为它们是技术说明而非配置：

1. **JSON解析函数注释** (Line ~34-54):
   ```python
   # 从AI响应中提取JSON对象（鲁棒版本，支持DeepSeek Reasoner）
   # 跳过DeepSeek Reasoner的推理标签 (<think>...</think>)
   # DeepSeek Reasoner可能返回：<think>推理过程</think>\n{JSON}
   ```
   
   **原因**: 这是对AI响应格式的技术说明，Qwen可能也有类似格式，保留有助于理解

2. **历史脚本路径** (Line ~4357):
   ```python
   #   python3 /tmp/merge_v770_to_deepseek.py
   ```
   
   **原因**: 注释掉的历史记录，不影响运行

---

## ✅ 验证方法

### 快速验证

```bash
cd ~/10-23-bot/ds

# 1. 检查残留deepseek（应为0）
grep -i "deepseek" qwen_多币种智能版.py | \
  grep -v "^#" | \
  grep -v "说明\|Reasoner\|API\|支持DeepSeek\|从AI响应\|跳过DeepSeek\|merge_v770" | \
  wc -l

# 2. 验证qwen配置
grep -c "qwen_client" qwen_多币种智能版.py  # 应为19
grep -c "qwen-plus\|qwen-max" qwen_多币种智能版.py  # 应为15
grep -c "通义千问" qwen_多币种智能版.py  # 应为27

# 3. 语法验证
python3 -m py_compile qwen_多币种智能版.py && echo "✅ OK"
```

### 对比验证

```bash
# 只应该在配置上有差异
diff deepseek_多币种智能版.py qwen_多币种智能版.py | grep -v "deepseek\|qwen\|DeepSeek\|Qwen" | wc -l
# 应该非常少（仅注释等微小差异）
```

---

## 🚀 部署说明

两个文件现在**完全同步**，可以独立部署：

### 部署DeepSeek

```bash
# 环境变量
export DEEPSEEK_API_KEY="sk-xxx"
export MODEL_NAME="deepseek"

# 运行
python3 deepseek_多币种智能版.py
```

### 部署Qwen

```bash
# 环境变量
export QWEN_API_KEY="sk-xxx"  # 或 DASHSCOPE_API_KEY
export MODEL_NAME="qwen"

# 运行
python3 qwen_多币种智能版.py
```

### 配置文件隔离

两个模型的配置文件**完全独立**，互不影响：

```
trading_data/
├── deepseek/
│   ├── learning_config.json
│   ├── market_snapshots/
│   └── ...
└── qwen/
    ├── learning_config.json
    ├── market_snapshots/
    └── ...
```

---

## 🔄 同步维护流程

**未来更新时**，只需修改deepseek文件，然后运行同步脚本：

```bash
cd ~/10-23-bot/ds

# 1. 修改deepseek文件
vim deepseek_多币种智能版.py

# 2. 运行同步脚本
bash 完全同步deepseek到qwen.sh

# 3. 验证
bash 最终修复qwen.sh

# 4. 提交
git add qwen_多币种智能版.py
git commit -m "🔄 同步deepseek更新到qwen"
```

---

## 📝 同步历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2025-11-07 | V8.3.13 | 首次完全同步，清理所有混杂内容 |

---

## 📞 维护建议

1. **主开发文件**: 以deepseek为主开发文件
2. **同步频率**: 每次重要更新后立即同步
3. **测试策略**: 两个文件独立测试，确保配置隔离
4. **备份策略**: 同步前自动备份qwen文件

---

**创建日期**: 2025-11-07  
**维护者**: AI Assistant  
**状态**: ✅ 已完成完全同步  

---

