# LLM 多供应商能力映射架构设计与面试表达

## 1. 问题背景

在企业级 RAG/Agent 系统里，模型调用通常会遇到三个现实问题：

1. 同样是“深度思考”，不同供应商参数完全不同  
2. 同一供应商内，不同模型能力也不同  
3. 供应商接口变化频繁，业务层不能直接耦合厂商参数

典型例子：

1. DeepSeek 侧常见参数是 `thinking + reasoning_effort`  
2. Qwen 侧常见参数是 `enable_thinking + thinking_budget`

如果前端直接传厂商参数，会导致：

1. 页面逻辑复杂且难维护  
2. 新增模型要改多处代码  
3. 模型切换时行为不可预测

---

## 2. 设计目标

1. 统一用户语义：前端只认 `Quick / Deep / WebSearch`  
2. 低耦合：业务层不直接依赖厂商参数名  
3. 可扩展：新增供应商/模型时最小改动  
4. 鲁棒：参数不兼容时自动降级，不影响服务可用性  
5. 可观测：可以看见每个模型的能力与映射策略

---

## 3. 核心架构（四层）

### 3.1 Canonical Layer（统一语义层）

统一定义与业务相关、与供应商无关的调用意图：

1. `thinking_mode: quick | deep`
2. `native_web_search: bool`
3. `stream: bool`
4. `temperature / max_tokens`

在代码中对应：

1. `CanonicalCompletionOptions`  
路径：[app/services/llm_provider_mapping.py](/E:/00-我的AI Agent/RGA知识库/app/services/llm_provider_mapping.py)

### 3.2 Capability Registry（能力目录层）

职责：回答“这个模型到底支持什么”。

能力项示例：

1. 是否支持 native web search  
2. thinking 参数风格：`deepseek | qwen | none`  
3. 是否支持 `reasoning_effort`  
4. 是否支持 `thinking_budget`

支持两级配置：

1. Provider 默认能力（如 `deepseek`、`qwen`）  
2. Model/前缀覆盖（`MODEL_CAPABILITIES_JSON`）

在代码中对应：

1. `CapabilityRegistry`  
路径：[app/services/llm_provider_mapping.py](/E:/00-我的AI Agent/RGA知识库/app/services/llm_provider_mapping.py)

### 3.3 Provider Adapter（供应商适配层）

职责：把统一语义翻译成厂商参数。

当前已实现：

1. `DeepSeekOptionsAdapter`
2. `QwenOptionsAdapter`
3. `ProviderOptionsAdapter`（默认通用兜底）

映射策略：

1. DeepSeek `Deep` -> `thinking.enabled + reasoning_effort`
2. Qwen `Deep` -> `enable_thinking + thinking_budget`
3. `Quick` 默认走低成本路径（禁思考/低推理）

在代码中对应：

1. `build_provider_options(...)`  
路径：[app/services/llm_provider_mapping.py](/E:/00-我的AI Agent/RGA知识库/app/services/llm_provider_mapping.py)

### 3.4 Orchestrator（执行编排层）

职责：串联 Provider 选择、能力解析、映射、调用和降级。

在本项目中由 `KnowledgeBaseService` 统一编排：

1. `_resolve_provider_name` 选供应商
2. `_resolve_model_capability` 取能力
3. `_completion_options` 构建最终参数
4. `_chat_completion` 发请求 + 异常降级

核心路径：

1. [app/services/knowledge_base.py](/E:/00-我的AI Agent/RGA知识库/app/services/knowledge_base.py)

---

## 4. Quick / Deep 映射规则（当前实现）

| Provider | Quick | Deep |
|---|---|---|
| DeepSeek | `thinking=disabled` | `thinking=enabled` + `reasoning_effort=high(可配)` |
| Qwen | `enable_thinking=false` | `enable_thinking=true` + `thinking_budget=2048(可配)` |
| Others | 常规参数（temperature/max_tokens） | 深度模式放宽 token（不强行注入未知参数） |

可配置项：

1. `DEEPSEEK_DEEP_REASONING_EFFORT=high|max`
2. `QWEN_DEEP_THINKING_BUDGET=2048`
3. `MODEL_CAPABILITIES_JSON={...}`（模型级覆盖）

---

## 5. 扩展新供应商/模型的流程（低耦合）

新增一个商家时，不需要改业务主流程，只需要：

1. 在 `ProviderRuntimeConfig` 增加 key/base_url 来源  
2. 在 `CapabilityRegistry` 增加 provider 默认能力  
3. 新增一个 `XxxOptionsAdapter`（如参数风格特殊）  
4. 在 `build_provider_options` 里注册选择规则  
5. 在 `.env` 增加对应配置项

新增某个模型特殊能力时：

1. 直接写 `MODEL_CAPABILITIES_JSON` 覆盖，不改代码主流程

---

## 6. 鲁棒性策略

### 6.1 参数不兼容自动降级

调用失败时自动回退到基础参数，保证“能答”优先。

路径：

1. [app/services/knowledge_base.py](/E:/00-我的AI Agent/RGA知识库/app/services/knowledge_base.py)

### 6.2 能力判定以“模型级”为准

避免“同供应商下全部模型一刀切”的误判。

### 6.3 配置容错

1. JSON 覆盖解析失败不阻塞主链路  
2. 未知字段忽略，避免配置漂移导致崩溃

---

## 7. 可观测性落地

模型健康面板可查看：

1. Provider / 可用性 / API Key / Base URL  
2. `thinking_style`  
3. `deep_reasoning_effort` 或 `deep_thinking_budget`

相关路径：

1. [frontend/src/components/chat/ModelHealthPanel.vue](/E:/00-我的AI Agent/RGA知识库/frontend/src/components/chat/ModelHealthPanel.vue)
2. [frontend/src/components/chat/ChatWorkspace.vue](/E:/00-我的AI Agent/RGA知识库/frontend/src/components/chat/ChatWorkspace.vue)

---

## 8. 面试怎么写（项目经历）

可直接放在简历中的版本（3-4 条）：

1. 设计并实现多供应商 LLM 适配架构，建立“统一语义层 + 能力目录 + 参数映射适配器”，将前端与厂商参数解耦。  
2. 支持 DeepSeek/Qwen 差异化深度思考映射（`thinking/reasoning_effort` vs `enable_thinking/thinking_budget`），模型切换行为一致性显著提升。  
3. 引入模型级能力覆盖机制（`MODEL_CAPABILITIES_JSON`），新增模型无需改主流程代码，扩展改动面最小化。  
4. 增加健康面板与降级重试机制，提升可观测性与线上鲁棒性，降低参数不兼容导致的故障率。

---

## 9. 面试怎么说（口述模板）

### 9.1 30 秒版本

“我把多模型调用抽象成统一语义，比如 Quick/Deep，后端通过能力目录识别模型支持项，再由 Provider Adapter 翻译成厂商参数。这样新增供应商只要加 Adapter 和能力配置，不改主业务链路，并且有失败降级和健康面板保证稳定性。”

### 9.2 2 分钟版本

“核心是把业务意图和供应商细节解耦。  
第一层是 Canonical Request，只表达 Quick/Deep/WebSearch。  
第二层 Capability Registry 管模型能力差异，支持 provider 默认和 model 覆盖。  
第三层 Provider Adapter 做参数翻译，比如 DeepSeek 走 `thinking+reasoning_effort`，Qwen 走 `enable_thinking+thinking_budget`。  
第四层 Orchestrator 统一调用和降级重试。  
收益是新增模型低成本、切换行为稳定、排障效率高。健康面板还能直接看到当前模型映射策略和配置缺失项。”

### 9.3 深挖问答要点

1. 为什么不用前端直接传厂商参数？  
答：会把 UI 和厂商强耦合，新增模型要改前后端多处，维护成本高。

2. 同供应商不同模型能力不同怎么办？  
答：模型级能力覆盖优先，provider 默认只是兜底。

3. 参数不支持导致 400 怎么办？  
答：统一异常分层，自动剔除高阶参数回退基础调用，保证可用性。

---

## 10. 简历怎么写（STAR 结构）

### S（场景）

多供应商接入后，参数差异大、行为不一致、维护成本高。

### T（任务）

设计可扩展的多模型调用架构，降低耦合，保证模型切换稳定。

### A（行动）

1. 定义统一语义层（Quick/Deep/WebSearch）  
2. 建能力目录（provider 默认 + model 覆盖）  
3. 建适配器层（DeepSeek/Qwen）  
4. 做失败降级与健康面板可观测

### R（结果）

1. 新增模型改动从“多模块修改”降到“新增配置 + 适配器”  
2. 模型切换行为一致性明显提升  
3. 故障排查从日志猜测变为面板直观诊断

---

## 11. 难点、亮点、遇到问题

### 难点

1. 同名能力语义不一致（思考能力有多种参数表达）  
2. 同供应商模型能力异构（不能只按 provider 判定）  
3. OpenAI 兼容接口并不等于参数兼容

### 亮点

1. 统一语义驱动，降低产品层复杂度  
2. 能力目录 + 适配器，支持平滑扩展  
3. 可观测面板对工程实践和面试展示都很加分

### 遇到问题与解决

1. `.env` BOM 导致 key 读取失败：在 loader 中自动去 BOM，并清理文件编码。  
2. 厂商参数不兼容：加调用回退路径，保证主流程可用。  
3. 模型可见但不可用：健康面板显示 `api_key/base_url` 缺失原因。

---

## 12. 后续演进建议

1. 增加参数映射审计日志（记录每次实际下发参数）  
2. 引入供应商异常码分类（超时、限流、参数错误分开统计）  
3. 增加灰度策略（按租户/用户切模型）  
4. 引入契约测试（每个 Adapter 一组稳定回归样例）

---

## 13. 参考文档

1. DeepSeek Thinking Mode: <https://api-docs.deepseek.com/guides/thinking_mode>  
2. DeepSeek Chat Completion API: <https://api-docs.deepseek.com/api/create-chat-completion>  
3. Alibaba Cloud Model Studio Deep Thinking: <https://www.alibabacloud.com/help/en/model-studio/deep-thinking>  
4. Qwen OpenAI-Compatible Chat API: <https://docs.qwencloud.com/api-reference/chat/openai-chat>

