---
name: cerebras
description: 调用 OpenRouter 的 openai/gpt-oss-120b 模型（强制使用 Cerebras 作为推理 provider）来快速生成或修改代码。当用户明确说"用 cerebras"、"用 gpt-oss"、"走 Cerebras 推理"，或需要批量生成模板/脚手架代码（速度比深度推理重要）时调用。需要环境变量 OPENROUTER_API_KEY。
---

# Cerebras (via OpenRouter) — 快速代码生成

## 何时使用

触发条件：
- 用户明确提到 "cerebras"、"gpt-oss" 或要求路由到 Cerebras
- 需要快速生成大段代码（脚手架、样板、类型定义、测试桩等），追求速度而非细致推理
- 批量代码生成任务，本地 Claude 推理速度不够

**不要使用**：
- 任务需要深度推理、复杂调试、关键架构设计 → 由 Claude 直接处理
- 涉及密钥、PII 或不应离开本机的代码
- 只是小修小改 → 直接 Edit 更快

## 前置条件

- 环境变量 `OPENROUTER_API_KEY` 必须已设置；未设置则停下来让用户配置，不要尝试调用
- 网络可访问 `https://openrouter.ai`

## Provider 强制路由原理

OpenRouter 默认会自动选 provider。要**保证**走 Cerebras，使用 `provider.only: ["cerebras"]`。如果 Cerebras 不可用，请求会立即失败（避免悄悄回落到 Groq/Fireworks 等其他 provider，影响一致性）。

文档：https://openrouter.ai/docs/guides/routing/provider-selection

## 调用方式

### Bash / curl（Claude Code 一次性调用首选）

```bash
curl -sS https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-120b",
    "provider": { "only": ["cerebras"] },
    "temperature": 0.2,
    "messages": [
      {"role": "system", "content": "You are a senior software engineer. Output only code, no prose, no markdown fences."},
      {"role": "user", "content": "<PROMPT>"}
    ]
  }' | jq -r '.choices[0].message.content'
```

### Python（需要集成到脚本时）

```python
import os
from openai import OpenAI  # OpenRouter 兼容 OpenAI SDK

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

resp = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "system", "content": "You are a senior software engineer. Output only code."},
        {"role": "user", "content": prompt},
    ],
    temperature=0.2,
    extra_body={"provider": {"only": ["cerebras"]}},
)
code = resp.choices[0].message.content
```

## 校验本次确实走了 Cerebras

响应里有 `provider` 字段。调用后确认：

```bash
... | jq -r '.provider'   # 期望输出: "Cerebras"
```

如果不是 Cerebras，明确告诉用户路由约束失败，**不要**继续使用结果。

## 推荐参数

| 参数           | 值     | 原因 |
|---------------|--------|------|
| `temperature` | `0.2`  | 代码生成要确定性 |
| `max_tokens`  | 不设或 4096 | 大文件给足空间 |
| `top_p`       | 不设   | 用默认即可 |
| system 提示    | "Output only code, no explanation, no markdown fences" | 返回内容可直接落盘 |

## 调用后的处理

1. 用 Write/Edit 工具把生成的代码**写入对应文件**，不要只打印
2. 简短告诉用户写到了哪个文件、内容是什么
3. 如果生成结果有问题，**不要盲目重试**——审查、改进 prompt，或回退由 Claude 自己写

## 成本与速率

- gpt-oss-120b 走 Cerebras 价格便宜（参考：https://openrouter.ai/openai/gpt-oss-120b ）
- Cerebras 免费额度速率限制较严，遇到 429 直接报给用户，**不要循环重试**
