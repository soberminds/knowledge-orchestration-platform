# 第二阶段：单 Agent 核心功能计划

## 1. 当前项目已经做到哪里

如果按“三个阶段”来划分：

```text
第一阶段：知识库 RAG
第二阶段：单 Agent 工具调用
第三阶段：多 Agent 协作系统
```

当前项目的状态是：

```text
第一阶段 RAG 知识库：已完成，并且已经工程化。
第二阶段单 Agent：核心底座已经有了，但还需要补工具标准化、工具展示、更多只读工具和确认机制。
第三阶段多 Agent：还没有正式开始。
```

也就是说，现在系统已经不是普通 RAG demo，而是：

```text
RAG 知识库 + 文档管理 + 用户体系 + 会话范围 + 多模型兼容 + 基础工具调用
```

第二阶段的目标不是重新做一套系统，而是在现有知识编排平台上继续升级，让它从“会回答”变成“会查、会用工具、会展示执行过程、会在风险操作前确认”。

## 2. 第二阶段核心目标

一句话目标：

```text
让模型不仅能回答，还能根据问题自动选择工具、执行工具、展示执行过程，并在高风险操作前让用户确认。
```

更具体地说，第二阶段完成后，用户提问时应该能走这样的链路：

```text
用户提问
  -> 后端判断是否进入 Agent 模式
  -> 模型根据工具说明决定是否调用工具
  -> 后端执行工具
  -> 前端展示工具调用过程
  -> 模型基于工具结果生成最终回答
  -> 如果工具有风险，先让用户确认再执行
```

## 3. 当前已经具备的 Agent 底座

当前系统已经完成了第二阶段的一部分底座：

- `ToolRegistry` 基础版
- `search_knowledge_base` 知识库搜索工具
- `search_web` 网页搜索工具按配置启用
- 非流式 tool calling 循环
- 流式 tool calling 循环
- `StreamingEvent` 统一流式事件
- `tool_call_delta` 工具调用流式事件
- 前端基础工具调用展示
- `model_diagnostics` 模型诊断信息
- Provider 能力识别
- `LLMProviderAdapter` 抽象
- OpenAI-compatible provider 调用层
- Qwen / DeepSeek / OpenAI 等模型能力映射
- 千问原生联网参数
- 千问 Responses API 基础 adapter
- 多模态 message part 基础协议
- 图片粘贴基础支持
- 会话绑定文件夹 / 知识库 / 工作区范围检索
- 用户体系和游客用户 `local-user`

所以第二阶段不是从 0 开始，而是要把“能调工具”升级成“好用、可控、可观察的 Agent”。

## 4. 第二阶段快速完成版范围

为了快速完成核心功能，不建议一开始就做复杂的多 Agent、插件市场、代码执行沙箱。

建议第二阶段快速版只做下面五块：

```text
2.1 工具标准化
2.2 工具调用过程可视化
2.3 增加文档库只读工具
2.4 增加 Agent 模式开关
2.5 增加高风险工具确认机制基础版
```

其中最优先的是：

```text
2.1 工具标准化
2.2 工具调用过程可视化
2.3 文档库只读工具
```

这三块做完，第二阶段的核心体验就会明显成型。

## 5. 2.1 工具标准化（已完成基础版）

### 5.1 目标

把现在内部能用的工具，整理成一套统一的工具描述结构。

每个工具都应该有：

- 工具名称
- 展示名称
- 工具描述
- 参数 schema
- 风险等级
- 是否需要用户确认
- 是否默认启用
- 执行函数

推荐结构：

```python
ToolSpec(
    name="search_knowledge_base",
    display_name="搜索知识库",
    description="在当前会话绑定的知识库、文件夹或工作区范围内搜索相关片段。",
    parameters={
        "query": {
            "type": "string",
            "description": "检索关键词或问题",
        },
        "top_k": {
            "type": "integer",
            "description": "返回结果数量",
        },
    },
    risk_level="read",
    requires_confirmation=False,
)
```

### 5.2 风险等级

建议先定义三类风险：

```text
read：只读工具，默认允许执行
write：会修改数据，需要用户确认
dangerous：高风险操作，必须确认，后续可以加二次确认
```

当前快速版先主要实现 `read`。

后续可写工具再逐步接入 `write` 和 `dangerous`。

### 5.3 为什么要先做这个

因为后面的能力都依赖工具标准化：

- 前端展示工具中文名
- 模型知道工具怎么用
- 后端判断工具是否危险
- 工具调用日志可以结构化保存
- 工具失败时可以给出明确错误
- 未来可以做工具中心
- 未来可以做权限控制

### 5.4 涉及文件

- `app/services/tools.py`
- `app/services/knowledge_base.py`
- `app/services/llm_streaming.py`
- `app/schemas.py`
- `frontend/src/api.ts`
- `frontend/src/types/chat.ts`
- `frontend/src/components/chat/MessageItem.vue`

### 5.5 验收标准

完成后，系统里每个工具都能被描述成：

```json
{
  "name": "search_knowledge_base",
  "display_name": "搜索知识库",
  "description": "在当前范围内搜索知识库片段",
  "risk_level": "read",
  "requires_confirmation": false
}
```

模型调用工具时，诊断信息里不再只有工具名，而是能带上展示名称、风险等级、执行状态。

### 5.6 当前落地情况

已完成基础版：

- `app/services/tools.py` 已从 `ToolDefinition` 升级为 `ToolSpec`
- 每个工具现在包含：
  - `name`
  - `display_name`
  - `description`
  - `parameters`
  - `risk_level`
  - `requires_confirmation`
  - `default_enabled`
  - `handler`
  - `summarize_result`
- 工具执行结果统一成 `ToolExecutionResult`
- `ToolExecutionResult` 会记录：
  - 工具名
  - 展示名
  - 参数
  - 状态
  - 摘要
  - 耗时
  - 风险等级
  - 是否需要确认
  - 错误信息
- `app/services/knowledge_base.py` 的非流式和流式工具调用都已经接入结构化诊断
- 前端 `MessageItem.vue` 的工具调用折叠区已展示：
  - 工具展示名
  - 成功 / 失败 / 待确认
  - 只读 / 写入 / 高风险
  - 耗时
  - 执行摘要
  - 参数 JSON

当前仍然保持工具本身只读：

```text
search_knowledge_base：只读，默认启用
search_web：只读，仅外部搜索可用且用户开启外部联网时启用
```

## 6. 2.2 工具调用过程可视化

### 6.1 目标

现在前端已经能看到“工具调用”，但还不够清楚。

第二阶段要让用户看懂：

```text
Agent 调了哪个工具
为什么调这个工具
传了什么参数
工具是否成功
工具返回了什么摘要
工具耗时多久
最终回答是否基于工具结果
```

### 6.2 推荐展示方式

在助手消息下面展示一个折叠区：

```text
工具调用（2）

1. 搜索知识库
   状态：成功
   查询：ONLYOFFICE 保存后索引更新
   返回：命中 4 条片段
   耗时：238ms

2. 查询文档元数据
   状态：成功
   文件：文档库文件夹化与用户关联设计.md
   返回：文件 ID、路径、所属文件夹、索引状态
   耗时：96ms
```

点开详情后再显示完整参数：

```json
{
  "query": "ONLYOFFICE 保存后索引更新",
  "top_k": 4
}
```

### 6.3 后端返回结构建议

推荐把 `tool_calls` 增强成：

```json
{
  "id": "call_xxx",
  "name": "search_knowledge_base",
  "display_name": "搜索知识库",
  "arguments": {
    "query": "ONLYOFFICE 保存后索引更新",
    "top_k": 4
  },
  "status": "success",
  "summary": "命中 4 条知识库片段",
  "duration_ms": 238,
  "risk_level": "read",
  "requires_confirmation": false,
  "error": null
}
```

失败时：

```json
{
  "name": "search_web",
  "display_name": "搜索网页",
  "status": "error",
  "summary": "网页搜索服务未配置",
  "error": "WEB_SEARCH_PROVIDER=none"
}
```

### 6.4 涉及文件

- `app/services/tools.py`
- `app/services/knowledge_base.py`
- `app/services/llm_streaming.py`
- `app/api/routes.py`
- `frontend/src/api.ts`
- `frontend/src/types/chat.ts`
- `frontend/src/composables/useChatWorkspace.ts`
- `frontend/src/components/chat/MessageItem.vue`
- `frontend/src/i18n/messages.ts`

### 6.5 验收标准

用户可以在每条助手回答下面看到清楚的工具轨迹：

- 调用了几个工具
- 工具中文名是什么
- 参数是什么
- 成功还是失败
- 返回摘要是什么
- 耗时多久

这一步做完后，用户不会再只看到“tool_call: search_knowledge_base”这种偏底层的信息。

## 7. 2.3 增加文档库只读工具（已完成基础版）

### 7.1 为什么要补工具

当前工具主要是：

```text
search_knowledge_base
search_web
```

这两个工具能解决“搜内容”的问题，但 Agent 还不太懂“文档库结构”。

比如用户问：

```text
我上传了哪些文档？
这个文件夹下面有什么？
这个文件有没有被索引？
这个文档主要讲了什么？
```

纯向量搜索不一定适合回答这些问题，所以需要补文档库只读工具。

### 7.2 工具一：list_documents

用途：

```text
查询当前用户、当前会话范围内有哪些文件和文件夹。
```

适合回答：

```text
我的知识库里有哪些文档？
这个文件夹下面有哪些文件？
我上传过哪些设计文档？
```

参数建议：

```json
{
  "folder_id": 12,
  "keyword": "设计",
  "limit": 20
}
```

返回摘要建议：

```json
{
  "folders": [
    {
      "folder_id": 3,
      "name": "业务逻辑解析",
      "path": "/业务逻辑解析"
    }
  ],
  "files": [
    {
      "file_id": 15,
      "name": "RAG全链路深度解析.md",
      "folder_path": "/业务逻辑解析",
      "indexed": true
    }
  ]
}
```

### 7.3 工具二：get_document_metadata

用途：

```text
根据 file_id 查询文件名、路径、所属文件夹、大小、更新时间、索引状态。
```

适合回答：

```text
这个文档有没有被索引？
这个文件属于哪个文件夹？
这个文件最后什么时候更新？
```

参数建议：

```json
{
  "file_id": 123
}
```

返回摘要建议：

```json
{
  "file_id": 123,
  "name": "文档库文件夹化与用户关联设计.md",
  "folder_path": "/业务逻辑解析",
  "size": 24886,
  "updated_at": "2026-06-28 01:25:00",
  "indexed": true,
  "chunk_count": 36
}
```

### 7.4 工具三：read_document_summary

用途：

```text
读取某个文档的摘要、前若干段文本，或索引片段摘要。
```

注意：不要一上来返回全文，容易塞爆上下文。

参数建议：

```json
{
  "file_id": 123,
  "max_chars": 2000
}
```

适合回答：

```text
帮我总结这个文档。
这个文档主要讲了什么？
这个设计文档有哪些关键点？
```

返回摘要建议：

```json
{
  "file_id": 123,
  "name": "文档库文件夹化与用户关联设计.md",
  "content_preview": "本文主要说明文档库从 path 管理升级到 file_id / folder_id 管理...",
  "truncated": true
}
```

### 7.5 涉及文件

- `app/services/document_library.py`
- `app/services/files.py`
- `app/services/tools.py`
- `app/services/knowledge_base.py`
- `app/schemas.py`

### 7.6 验收标准

用户问：

```text
我这个知识库里有哪些文档？
```

Agent 能调用 `list_documents`。

用户问：

```text
这个文档有没有被索引？
```

Agent 能调用 `get_document_metadata`。

用户问：

```text
文档库文件夹化这个设计文档主要讲了什么？
```

Agent 能先查文档，再读取摘要，最后组织回答。

### 7.7 当前落地情况

已完成基础版：

- `app/services/document_library.py` 新增只读 Agent 查询方法
  - `list_documents_for_agent(...)`
  - `get_document_metadata_for_agent(...)`
  - `read_document_summary_for_agent(...)`
- `app/services/tools.py` 新增三个只读工具
  - `list_documents`
  - `get_document_metadata`
  - `read_document_summary`
- `app/services/knowledge_base.py` 已把三个工具接入 `_build_tool_registry()`
- 三个工具都继承统一 `ToolSpec` 结构
  - `risk_level="read"`
  - `requires_confirmation=false`
  - `default_enabled=true`
- 前端工具调用折叠区可以直接展示它们的中文名、状态、风险等级、耗时、摘要和参数

当前三个工具的定位：

```text
list_documents：让模型知道当前用户文档库里有哪些文件/文件夹
get_document_metadata：让模型查询某个 file_id 的路径、大小、解析状态、索引状态等元数据
read_document_summary：让模型读取某个 file_id 的安全预览内容，默认最多 2000 字符
```

注意：

- 当前仍然是只读工具，不会修改文件或索引
- `read_document_summary` 读取的是安全预览，不会无节制返回全文，避免上下文被撑爆
- `chunk_count` 暂未作为强字段返回，因为当前主索引在 Chroma，MySQL `kop_document_chunk` 还不是稳定同步来源，后续可以在“索引持久化/统计增强”阶段补齐

## 8. 2.4 增加 Agent 模式开关

### 8.1 目标

产品上需要区分：

```text
普通聊天
知识库问答
Agent 模式
```

Agent 模式打开后，模型应该更积极地使用工具，并且前端明确展示工具轨迹。

### 8.2 请求字段建议

后端请求可以增加：

```json
{
  "agent_mode": true
}
```

或者更通用一点：

```json
{
  "run_mode": "agent"
}
```

推荐用 `run_mode`，以后可以扩展：

```text
chat：普通聊天
rag：知识库问答
agent：工具 Agent
```

### 8.3 Agent 模式系统提示词

Agent 模式下，系统提示词要明确告诉模型：

```text
你可以使用工具完成任务。
需要查资料时优先调用工具。
不要假装已经查询。
工具失败时说明失败原因。
高风险操作必须等待用户确认。
最终回答要说明基于哪些工具结果。
```

### 8.4 前端位置

建议在聊天输入区或设置区加一个开关：

```text
Agent 模式
```

可以用一个工具图标或闪电图标，不要做得太重。

### 8.5 涉及文件

- `app/schemas.py`
- `app/api/routes.py`
- `app/services/knowledge_base.py`
- `frontend/src/api.ts`
- `frontend/src/composables/useChatWorkspace.ts`
- `frontend/src/components/chat/ChatComposer.vue`
- `frontend/src/i18n/messages.ts`

### 8.6 验收标准

打开 Agent 模式后：

- 请求里带 `run_mode=agent`
- 系统 prompt 使用 Agent 版
- 模型更积极调用工具
- 前端展示“Agent 模式”状态
- 工具轨迹默认更清楚

## 9. 2.5 高风险工具确认机制基础版

### 9.1 为什么要做确认机制

只读工具可以直接执行。

但未来这些工具不能让模型直接执行：

```text
create_folder
rename_file
move_file
delete_file
rebuild_index
send_email
write_document
```

否则模型一旦误判，就可能修改或删除用户数据。

所以第二阶段至少要设计确认机制基础版。

### 9.2 执行逻辑

如果工具是：

```text
risk_level=read
requires_confirmation=false
```

则直接执行。

如果工具是：

```text
risk_level=write
requires_confirmation=true
```

则不立即执行，而是返回一个待确认动作：

```json
{
  "status": "pending_confirmation",
  "tool_name": "rebuild_file_index",
  "arguments": {
    "file_id": 123
  },
  "confirmation_id": "confirm_xxx",
  "message": "是否确认重新索引文件：RAG全链路深度解析.md？"
}
```

前端展示确认卡片：

```text
Agent 想执行：
重新索引文件：RAG全链路深度解析.md

[确认执行] [取消]
```

用户确认后，前端再调用：

```http
POST /api/agent/tool-confirmations/{confirmation_id}/confirm
```

### 9.3 第一个确认型工具建议

建议先接：

```text
rebuild_file_index
```

原因：

- 它确实会修改索引状态
- 但不会删除用户原始文件
- 风险比删除文件、移动文件低
- 很适合作为确认机制的第一版样例

### 9.4 是否需要新表

如果要支持页面刷新后继续确认，建议加表：

```text
agent_tool_confirmations
```

字段建议：

```sql
id
confirmation_id
user_id
conversation_id
message_id
tool_name
arguments_json
status
expires_at
created_at
confirmed_at
cancelled_at
```

如果只是快速版，也可以先用 Redis 或内存缓存。

考虑到你的系统已经有 MySQL 聊天记忆，建议后面正式版还是落 MySQL。

### 9.5 涉及文件

- `app/services/tools.py`
- `app/services/knowledge_base.py`
- `app/api/routes.py`
- `app/schemas.py`
- `app/db.py` 或数据库相关模块
- `frontend/src/api.ts`
- `frontend/src/types/chat.ts`
- `frontend/src/components/chat/MessageItem.vue`

### 9.6 验收标准

当模型试图调用确认型工具时：

- 后端不直接执行
- 前端出现确认卡片
- 用户确认后才执行
- 用户取消后工具不执行
- 工具结果会回写到会话
- 诊断信息里能看到确认状态

## 10. 第二阶段推荐实施顺序

为了快速完成核心功能，建议按下面顺序做：

```text
[x] 1. 标准化 ToolSpec：名称、描述、参数、风险等级、是否需要确认
[x] 2. 增强 tool_calls 诊断：状态、摘要、耗时、错误信息
[x] 3. 优化前端工具调用折叠区，让用户看懂 Agent 做了什么
[x] 4. 新增 list_documents 工具：查询当前用户/范围内的文档
[x] 5. 新增 get_document_metadata 工具：查询文件元信息和索引状态
[x] 6. 新增 read_document_summary 工具：读取文档摘要或前 N 个片段
[x] 7. 增加 Agent 模式开关
[x] 8. 根据 Agent 模式调整系统 prompt
[x] 9. 工具失败时返回结构化错误，不让模型假装成功
[x] 10. 增加 requires_confirmation 机制基础版
[x] 11. 前端展示工具确认卡片
[x] 12. 接入第一个确认型工具：rebuild_file_index
[x] 13. 接入发送邮件工具：send_email
[x] 14. 更新业务文档：模型能力思考.md 和 RAG全链路深度解析.md
```

### 10.1 本轮落地确认

本轮已经把第二阶段后半段补齐：

- 前端新增 `run_mode` 选择：普通聊天 / 知识库问答 / Agent。
- 后端 `ChatRequest`、`KnowledgeBaseService.answer()`、`stream_answer()` 都已经接收 `run_mode`。
- `chat` 模式跳过知识库检索，避免普通聊天时假装查过知识库。
- `rag` 模式保留原来的“先检索证据，再组织回答”链路。
- `agent` 模式会启用工具调用提示词，并在模型支持工具调用时注册 `ToolRegistry`。
- 工具调用诊断已经结构化返回 `status`、`summary`、`duration_ms`、`risk_level`、`requires_confirmation`、`default_enabled`、`error`。
- 新增内存版 `AgentToolConfirmationService`，作为确认型工具的快速版队列。
- `ToolSpec.requires_confirmation=true` 时，后端不会直接执行工具，而是返回 `pending_confirmation`。
- 前端助手消息的“工具调用”区域会展示确认卡片。
- 用户点击“确认执行”后，才会调用后端确认接口真正执行工具。
- 用户点击“取消”后，工具不会执行。
- 已接入第一个确认型工具 `rebuild_file_index`，用于按 `file_id` 重新索引单个文件。
- 已接入邮件发送工具 `send_email`，属于 `write` 风险工具。它只有在 `.env` 里启用 `EMAIL_TOOL_ENABLED=true` 且 SMTP 配置完整时才会暴露给模型；模型只能创建待确认请求，用户确认后才会真正通过 SMTP 发出邮件。
- 前端确认卡片会对 `send_email` 展示收件人、抄送、主题和正文预览，避免用户只看到底层 JSON 参数。
- 确认 / 取消后，后端会把对应工具调用状态回写到 `kop_chat_message.meta_json.model_diagnostics.tool_calls`。这样刷新页面重新读取会话消息时，不会把已经确认过的工具调用再次显示成“待确认”。
- 邮件工具新增兜底逻辑：如果模型没有主动调用 `send_email`，但用户原始问题明确包含“发送邮件/发邮箱”和收件邮箱地址，后端会把模型生成的正文整理成邮件草稿，并创建真正的 `send_email` 待确认卡片。这样不会出现模型只在自然语言里问“是否发送”，但前端没有确认按钮的问题。

当前确认队列本体仍然是**内存版快速实现**，后端重启后未处理的确认项会丢失。但已经执行过的确认结果会同步写回聊天消息元数据，保证刷新回显状态正确。后续正式版可以把确认队列换成 MySQL 表 `agent_tool_confirmations`，接口和前端交互形态可以保持不变。

### 10.2 邮件发送 Agent 工具补充

`send_email` 是第二阶段确认机制跑通后的第一个“真实外部动作”工具。

它和 `rebuild_file_index` 的区别是：

```text
rebuild_file_index
├─ 修改本系统内部索引
└─ 风险主要在本地数据状态

send_email
├─ 通过 SMTP 向外部收件人发送真实邮件
└─ 风险涉及外发内容、收件人、隐私和误发
```

所以 `send_email` 必须满足三层限制：

```text
1. 配置限制
   ├─ EMAIL_TOOL_ENABLED=true
   ├─ SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD 配置完整
   └─ 未配置时不注册工具，模型看不到 send_email

2. 参数限制
   ├─ 必须有 to / subject / body
   ├─ 支持 cc
   ├─ 限制单次收件人总数 EMAIL_TOOL_MAX_RECIPIENTS
   └─ 可选 EMAIL_TOOL_ALLOWED_DOMAINS 做收件域名白名单

3. 人工确认限制
   ├─ ToolSpec.risk_level=write
   ├─ ToolSpec.requires_confirmation=true
   ├─ 模型调用后只生成 pending_confirmation
   └─ 用户点击确认后才执行 SMTP 发送
```

涉及文件：

- `app/core/settings.py`：新增 SMTP 和邮件工具配置。
- `app/services/email_sender.py`：负责校验参数并通过 SMTP 发送邮件。
- `app/services/tools.py`：注册 `send_email` 工具 schema。
- `app/services/knowledge_base.py`：创建邮件确认请求，并注册 `confirmed_send_email(...)` executor。
- `app/services/knowledge_base.py`：当模型没有主动 tool_call，但用户明确要求发邮件时，兜底创建 `send_email` 确认项。
- `frontend/src/components/chat/MessageItem.vue`：在确认卡片里展示邮件预览。
- `frontend/src/i18n/messages.ts`：补充邮件预览文案。
- `.env.example`：补充 SMTP 配置模板。

## 11. 最短路径版本

如果只想最快看到第二阶段核心效果，先做这 6 个：

```text
1. ToolSpec 标准化
2. 工具调用 UI 优化
3. list_documents
4. get_document_metadata
5. read_document_summary
6. Agent 模式开关
```

这 6 个做完，系统就已经从“RAG 知识库问答”明显升级成：

```text
知识编排平台的单 Agent 核心版
```

之后再补：

```text
7. 高风险确认机制
8. rebuild_file_index 工具
```

## 12. 第二阶段不建议现在做的内容

为了快速完成核心功能，下面这些先不要做：

- 复杂多 Agent
- 完整 LangGraph 工作流
- 工具市场
- 插件系统
- 代码执行沙箱
- 自动发邮件
- 自动改文件
- 自动删文件
- 长期计划任务
- 复杂审批流

这些都很有价值，但会把第二阶段拉得太大。

当前最重要的是：

```text
只读工具 Agent + 可视化轨迹 + 简单确认机制
```

## 13. 第二阶段完成后的效果

第二阶段核心版完成后，系统应该具备：

```text
1. 模型能根据问题自动选择工具
2. 后端能安全执行只读工具
3. 工具调用过程能在前端清楚展示
4. 工具失败能被明确说明
5. 文档库结构可以被 Agent 查询
6. 单个文档的元数据和摘要可以被 Agent 读取
7. 用户可以主动打开 Agent 模式
8. 高风险操作不会被模型直接执行，而是先等待用户确认
```

这时你可以认为：

```text
第二阶段单 Agent 核心功能：完成。
```

再往后，才适合进入第三阶段：

```text
多 Agent 协作系统。
```
