# Chat 生产配置说明（多模型自动路由 + 联网搜索 + 成本估算）

本文对应这三项能力：

1. 前端选模型后，后端自动按模型走对应 `API_KEY/BASE_URL`
2. 未配置 Key 的模型在前端显示“暂未配置”，不可发送
3. 每次回答显示 token 使用量和成本估算

## 1) 快速开始

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 填入你已申请的 Key（没申请的留空即可）：

```env
DEEPSEEK_API_KEY=...
QWEN_API_KEY=...
ZAI_API_KEY=...
KIMI_API_KEY=...
HUNYUAN_API_KEY=...
SILICONFLOW_API_KEY=...
QIANFAN_API_KEY=...
OPENAI_API_KEY=...
```

## 2) 自动路由规则

后端按模型名前缀自动识别供应商：

- `deepseek*` -> `deepseek`
- `qwen*` / `qwq*` -> `qwen`
- `glm*` / `chatglm*` -> `zai`
- `kimi*` / `moonshot*` -> `kimi`
- `hunyuan*` -> `hunyuan`
- `ernie*` / `wenxin*` -> `qianfan`
- `gpt*` / `o1*` / `o3*` / `o4*` -> `openai`
- 含 `/` 的模型名（如 `Qwen/Qwen2.5-7B-Instruct`）默认按 `siliconflow`

如果某个模型前缀不标准，可用显式映射覆盖：

```env
MODEL_PROVIDER_OVERRIDES_JSON={"hunyuan-lite":"hunyuan","gpt-4o-mini":"openai"}
```

## 3) 自定义额外网关（可选）

如果你有自己的 OpenAI 兼容网关，可以加：

```env
EXTRA_PROVIDER_CONFIGS_JSON={"my_gateway":{"base_url":"https://your-gateway/v1","api_key_env":"MY_GATEWAY_API_KEY"}}
MY_GATEWAY_API_KEY=...
```

再通过 `MODEL_PROVIDER_OVERRIDES_JSON` 把模型指到这个 provider。

## 4) 模型可用状态与前端行为

- `/api/chat/options` 会返回每个模型的：
  - provider
  - available（是否可用）
  - unavailable_reason（不可用原因）
- 前端会自动：
  - 置灰不可用模型
  - 标签显示“暂未配置”
  - 发送前再次校验并提示原因

## 5) 联网搜索配置

```env
WEB_SEARCH_PROVIDER=tavily   # none | serper | tavily
WEB_SEARCH_API_KEY=...
WEB_SEARCH_TOP_K=5
```

未配置 `WEB_SEARCH_API_KEY` 时，前端会自动隐藏联网开关。

## 6) 成本估算配置

```env
COST_CURRENCY=USD
MODEL_PRICING_JSON={"deepseek-v4-flash":{"input_per_1m_tokens":0.14,"output_per_1m_tokens":0.28},"deepseek-v4-pro":{"input_per_1m_tokens":0.435,"output_per_1m_tokens":0.87}}
```

估算公式：

```text
input_cost  = prompt_tokens     * input_per_1m_tokens  / 1_000_000
output_cost = completion_tokens * output_per_1m_tokens / 1_000_000
total_cost  = input_cost + output_cost
```

说明：估算值用于运营监控，最终对账请以供应商账单为准。

## 7) 推荐官方文档

- DeepSeek: https://api-docs.deepseek.com/
- DashScope (Qwen OpenAI 兼容): https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
- Z.AI OpenAI SDK: https://docs.z.ai/guides/develop/openai/python
- Kimi API 概览: https://platform.kimi.com/docs/api/overview
- Tavily Quickstart: https://docs.tavily.com/documentation/quickstart
- Serper: https://serper.dev/
