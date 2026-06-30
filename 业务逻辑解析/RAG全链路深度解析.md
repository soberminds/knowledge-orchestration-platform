# RAG 全链路深度解析

这份文档的目标不是只告诉你“切片 -> 向量化 -> 向量检索”这三个词，
而是把当前项目里真正发生的完整业务流程全部摊开，让你知道：

- 谁在做切片
- 谁在做 embedding
- Chroma 到底是什么角色
- DeepSeek 在哪一步进入
- 上传、重建索引、聊天、ONLYOFFICE 保存后更新索引分别走什么路径
- 中间有哪些优化、兜底和失败点

---

## 1. 阅读前先认识这些前置知识

你这个判断是对的。

这类“全链路深度解析”文档，如果一上来就直接看主流程，阅读体验通常会变成：

- 流程在往前走
- 但脑子还在回头补概念
- 一边看流程，一边查名词
- 最后容易知道“它大概这么跑”，但不够扎实

所以这份文档更适合按下面的顺序读：

1. 先认识核心数据结构
2. 再认识核心对象 / 服务 / 方法
3. 再认识关键名词、库和功能
4. 最后再进入完整主流程图

### 1.1 先记住这几个核心数据结构

#### A. `Path`
它表示一个文件路径。

在当前项目里，很多入口都是先拿到 `Path`，例如：

- `iter_source_files()` 返回 `Path` 列表
- `load_documents_from_file(path)` 接收一个 `Path`
- `reindex_source_file(path)` 也是按 `Path` 重建索引

你可以把它理解成：

- “某个真实文件在磁盘上的位置”

#### B. `Document`
这是 LangChain 的文档对象，也是当前项目里最重要的中间标准结构之一。

`Document` 通常是在**文件解析阶段**生成的，入口就是：

- `app/services/files.py::load_documents_from_file(path)`

它做的事情是：

- 先把一个原始文件解析出来
- 再把解析结果包装成一个或多个 `Document`
- 然后交给后面的切片、embedding、入库流程

一个 `Document` 主要有两部分：

1. `page_content`
   - 真正的文本正文
2. `metadata`
   - 这段文本来自哪里、属于哪个文件、哪一页、哪个 sheet、哪个 slide

它的意义是：

- 把各种格式的原始文件统一变成“后续链路都能吃”的结构

#### 一个文件会变成几个 `Document`？

这个**不是固定 1 个**，要看文件类型和它天然的结构边界。

```text
load_documents_from_file(path)
├─ 纯文本 / 代码 / 配置 / JSON / YAML / SQL / Markdown
│  └─ 通常 1 个文件 -> 1 个 Document
├─ CSV / TSV
│  └─ 通常 1 个文件 -> 1 个 Document
├─ PDF
│  └─ 通常 1 页 -> 1 个 Document
├─ DOCX
│  └─ 通常 1 个文件 -> 1 个 Document
├─ DOC
│  └─ 通常 1 个文件 -> 1 个 Document
├─ XLSX / XLS / XLSM
│  └─ 通常 1 个 sheet -> 1 个 Document
└─ PPTX / PPT
   └─ 通常 1 个 slide -> 1 个 Document
```

#### 这些“页 / sheet / slide”分别是什么意思？

- `page`：PDF 的页码，或者为了统一链路给 sheet / slide 也用的“页号字段”
- `sheet_name`：Excel 工作表名
- `slide_name`：PowerPoint 幻灯片名或标题

所以你可以这样理解：

- **PDF** 是按页来拆 `Document`
- **Excel** 是按 sheet 来拆 `Document`
- **PPT** 是按 slide 来拆 `Document`
- **文本类文件** 通常整个文件就是 1 个 `Document`

#### 为什么要先按这些结构拆，而不是直接切片？

因为 `Document` 这一步是在保留“原始文件结构边界”。

先按文件天然结构拆好，再交给后面的 `split_documents()` 去细切，会更稳：

- PDF 的页信息不会丢
- Excel 的 sheet 信息不会丢
- PPT 的 slide 信息不会丢
- 后面检索命中后，也更容易知道来源位置

#### `Document` 和 chunk 的关系是什么？

- `Document` 是文件解析后的标准文本单元
- chunk 是 `split_documents()` 再切出来的小块
- 一个 `Document` 可能被切成多个 chunk
- 每个 chunk 后面才会进入 embedding 和 Chroma

#### 它的意义是：

- 把各种格式的原始文件统一变成“后续链路都能吃”的结构

#### C. chunk
chunk 不是一个单独的新类名，而是“切片后的 `Document` 单元”的业务叫法。

也就是说：

- 原始 `Document` 经过 `split_documents()` 后
- 会变成很多更小的 `Document`
- 这些切片后的 `Document`，我们业务上习惯叫它 chunk

#### D. vector / embedding 向量
这是文本被 embedding 模型编码后的数值表示。

你可以先把它理解成：

- 文本的“语义坐标”
- 后面 Chroma 就是拿这个坐标去做相似度检索

#### E. `SearchHit`
这是项目里定义的检索命中结果结构。

位置：

- `app/services/knowledge_base.py`

它表示“某次检索命中的一个结果”，常见字段有：

- `source` 命中的 chunk 来自哪个源文件路径
- `chunk_index` 这是这个 chunk 在切片结果里的编号
- `page` 页码或统一位置字段，PDF 是页，Excel/PPT 也是统一用这个字段表示位置
- `score` Chroma 算出来的相关度分数
- `preview` 为了展示用的摘要文本，通常是截断后的短文本
- `content` 这个 chunk 的完整文本内容

你可以把它理解成：

- “一个已经可以拿去展示或继续组织上下文的检索结果对象”

#### F. `IngestStats`
这也是项目里的数据结构，用来表示一次建索引 / 重建索引的统计结果。

常见内容包括：

- 加载了多少个 Document
- 建了多少个 chunk
- 涉及了哪些 source file

它的用途是：

- 给建索引接口、增量重建接口返回统计信息

#### G. `ChatHistoryItem`
这是聊天历史里单条消息的标准结构。

位置：

- `app/schemas.py`

它主要包含：

- `role`
  - 消息角色，只允许 `system` / `user` / `assistant`
- `content`
  - 消息正文

它的用途是：

- 前端把最近聊天历史传给后端时使用
- 后端从 MySQL / Redis 回读最近窗口后，也会重新包装成这个结构
- `KnowledgeBaseService.answer(...)` 和 `stream_answer(...)` 接收的 `history` 就是 `list[ChatHistoryItem]`

所以你可以把它理解成：

- “进入 RAG 问答链路前，聊天历史的统一消息格式”

#### H. `conversation_id`
这是新增的“后端会话 ID”。

位置：

- 后端请求 / 响应：`app/schemas.py::ChatRequest`、`ChatResponse`
- 前端 API 类型：`frontend/src/api.ts`
- 前端会话状态：`frontend/src/types/chat.ts::ChatSession.backendConversationId`

它解决的问题是：

- 前端本地会话 `id` 只是浏览器里的临时 ID
- 后端 MySQL 里的会话需要一个真正的数据库主键
- 同一个前端聊天窗口后续继续提问时，要能告诉后端“我还是这条会话”

当前流程是：

```text
第一次提问
├─ 前端没有 conversation_id
├─ 后端先解析当前有效用户
│  ├─ 已登录：用 session 对应的 user_id
│  └─ 未登录：回落到默认游客用户 local-user
├─ 后端创建 kop_chat_conversation
│  ├─ 绑定 user_id
│  ├─ 绑定 scope_type / scope_id / workspace_key
│  └─ 计算 scope_name 供前端展示
├─ 后端返回 conversation_id
└─ 前端保存为 ChatSession.backendConversationId

后续继续提问
├─ 前端带上 conversation_id
├─ 后端按 conversation_id 回读最近消息
├─ 如果会话范围发生变化，后端会同步更新对应 scope 字段
└─ 回答结束后继续把本轮消息写入同一条会话
```

#### I. `scope_type` / `scope_id` / `workspace_key` / `scope_name`
这几个字段是现在会话“作用域”的核心补充。

- `scope_type`
  - 这条会话当前绑定的是 `all` / `folder` / `kb` / `workspace`
- `scope_id`
  - 当作用域是文件夹或知识库时，对应的目标 ID；`all` 通常是 0 / null
- `workspace_key`
  - 当前工作区的稳定标识，常用于“工作区级会话”
- `scope_name`
  - 给前端展示用的可读名称，例如“全部知识库 / 某个文件夹 / 某个工作区”

它解决的问题是：

- 让同一个 `conversation_id` 不只是“某次聊天”
- 还明确这次聊天到底是在全量知识库里问，还是在某个文件夹 / 知识库 / 工作区里问
- 前端会话列表现在也能直接把范围标签显示出来

当前前端不是让用户手输这些字段，而是用可选控件生成：

- `ChatComposer.vue`
  - `scope_type` 用分段选项选择：全部 / 文件夹 / 知识库 / 工作区
  - 文件夹范围用 `el-tree-select` 从文档库树里选
  - 知识库范围用 `el-select` 从 `/api/chat/options` 返回的 `knowledge_bases` 里选
  - 工作区范围用 `el-select` 从 `/api/chat/options` 返回的 `workspaces` 里选
- `DocumentsWorkspace.vue`
  - 当前文件夹可以一键设为聊天检索范围
- `LeftSidebar.vue`
  - 最近会话列表会展示范围标签，方便区分这条会话问的是全部、文件夹、知识库还是工作区

#### J. `ChatMessagePart`
这是当前聊天多模态输入的结构化消息片段。

位置：

- 后端 schema：`app/schemas.py::ChatMessagePart`
- 前端类型：`frontend/src/api.ts::ChatMessagePart`
- 前端输入：`frontend/src/components/chat/ChatComposer.vue`

它解决的问题是：

- 以前一条用户消息基本只有 `question: str`
- 现在一条用户消息可以同时带文字、图片引用、文档引用

当前支持的 part 是：

```text
ChatMessagePart
├─ text
├─ image_url
└─ file_ref
   ├─ file_id
   ├─ file_name
   └─ mime_type
```

这里的 `image_url` 是 OpenAI-compatible 多模态协议里的字段名，不代表用户必须手动输入公网 URL。
前端现在支持两种图片来源：

- 用户输入图片 URL
- 用户在聊天输入框直接粘贴图片，前端转成 `data:image/...;base64,...`

后端会根据当前模型能力决定：

- 支持图片输入：把 `image_url` 原样传给 provider
- 不支持图片输入：只把图片降级成文本摘要，并写入 `model_diagnostics.warnings`

#### K. `ModelCapability`
这是当前模型能力判断的核心结构。

位置：

- `app/services/llm_provider_mapping.py::ModelCapability`
- `app/services/llm_provider_mapping.py::CapabilityRegistry`

它表示“某个模型这次运行时被系统认为支持什么能力”。

核心字段包括：

- `supports_native_web_search`
- `supports_tool_calling`
- `supports_multimodal_input`
- `supports_responses_api`
- `supports_responses_streaming`
- `thinking_style`
- `supports_reasoning_effort`
- `supports_thinking_budget`

它解决的问题是：

- 不是所有模型都支持图片
- 不是所有模型都支持工具调用
- 不是所有模型都支持 Responses API
- 同一个“深度思考”开关，在 DeepSeek 和 Qwen 里参数名也不一样

当前策略是：

- Qwen 默认支持原生联网和工具调用，但不是所有 Qwen 模型都默认支持图片、Responses API 或原生 thinking budget
- `qwen-vl*`、`qwen-omni*`、`qwen3.7-plus`、`qwen3.7-max` 等会自动标记为支持图片输入
- `qwen3.7-plus`、`qwen3.7-max`、`qwen3.6*`、`qwen3.5*`、`qwen3-max` 等会按能力标记 Responses API
- `qwen3*`、`qwq*`、`qvq*` 会按千问深度思考模型处理；`qwen-max` 当前只按通用文本模型处理，不承诺返回可展示的思考片段
- `gpt-4o*`、`gpt-4.1*`、`gpt-5*`、`o3*`、`o4*` 会自动标记为支持图片输入
- 具体模型能力可以通过 `.env` 的 `MODEL_CAPABILITIES_JSON` 覆盖

#### L. `StreamingEvent`
这是当前后端内部的统一流式事件结构。

位置：

- `app/services/llm_streaming.py`

以前流式回答主要就是一段段正文 delta。
现在模型流式返回里可能有很多不同类型的内容：

- 正文增量
- reasoning / 思考增量
- tool call 增量
- usage
- diagnostics
- done
- error

所以现在后端内部先统一成：

```text
StreamingEvent
├─ content_delta
├─ reasoning_delta
├─ tool_call_delta
├─ usage
├─ diagnostics
├─ done
└─ error
```

然后 `routes.py` 再把它转换成前端能消费的 SSE payload。

#### M. `model_diagnostics`
这是每次模型调用返回给前端和落库的诊断信息。

位置：

- `app/schemas.py::ModelDiagnostics`
- `app/services/knowledge_base.py::_build_model_diagnostics(...)`
- `frontend/src/components/chat/MessageItem.vue`
- `frontend/src/components/chat/ModelHealthPanel.vue`

它包含：

- 实际 provider
- 请求模型和最终模型
- 是否使用原生联网
- 是否使用外部联网
- thinking mode
- provider API，例如 `chat_completions` / `qwen_responses` / `qwen_responses_stream`
- 是否发生参数降级
- warnings
- tool calls
- capabilities 快照

它的意义是：

- 不再只靠模型正文判断“它到底用了哪个模型 / 哪个能力”
- 前端和后端都能看到这次调用是否发生了降级
- 排查“为什么图片没生效 / 工具没生效 / Responses 没生效”时有据可查

### 1.2 再记住这几个核心对象 / 服务

#### A. `KnowledgeBaseService`
位置：

- `app/services/knowledge_base.py`

这是整个 RAG 主流程的总调度器。

它负责的事情非常多，包括：

- 扫描文件
- 读取文档
- 切片
- 初始化 Chroma
- 建索引
- 检索
- 组织上下文
- 调大模型生成回答

它现在还会顺手把“当前有效用户 + 当前作用域”一起带进检索：

- 先按当前用户过滤
- 再按 `scope_type` / `scope_id` / `workspace_key` 限定范围
- `folder` 作用域会自动包含子文件夹
- 最终在回答结果里回传 `model_diagnostics`
- 如果供应商扩展参数失败，会退回一次再试，但会保留 warning，不会静默换模型

这一层现在和文档库数据库元数据强绑定：

- 建索引时先从 `DocumentLibraryService.get_index_metadata_by_storage_path(...)` 取文件元数据
- 然后把 `user_id` / `file_id` / `folder_id` / `kb_id` / `workspace_key` 等写入 Chroma metadata
- 检索时再用这些 metadata 做用户隔离和范围过滤

这里面几个词可以再翻译成更具体的动作：

#### 扫描文件是干什么？
意思是：

- 去看 `data/user_docs` 里现在有哪些受支持的源文件
- 也就是先确定“这次知识库里有哪些文件要参与建索引”

对应动作主要是：

- `iter_source_files()`
- `load_corpus()`

所以“扫描文件”还不是读文件正文，它更像是：

- 先列出候选文件清单

#### 读取文档是干什么？
这里不是指“前端打开文档看一下”，而是指：

- 把原始文件内容解析出来
- 再包装成标准的 `Document` 数据结构

也就是说，你的理解是对的：

- **读取文档，基本就可以理解成在建立 `Document` 数据结构**

对应入口是：

- `load_documents_from_file(path)`

比如：

- txt / md 通常整个文件生成 1 个 `Document`
- PDF 通常按页生成多个 `Document`
- Excel 通常按 sheet 生成多个 `Document`
- PPT 通常按 slide 生成多个 `Document`

#### 切片是干什么？
意思是：

- 把上一步生成的原始 `Document` 再切成更小的 chunk
- 让后面的向量检索粒度更合适

对应方法是：

- `split_documents(documents)`

所以这里的关系是：

- 扫描文件 -> 找到有哪些源文件
- 读取文档 -> 把文件解析成 `Document`
- 切片 -> 把 `Document` 再切成 chunk

#### 初始化 Chroma 是干什么？
意思是：

- 准备好向量库存储对象
- 并把 embedding 能力挂进去

对应方法是：

- `_build_vector_store()`

最关键的点是：

- `embedding_function=self.embedder`

这里最容易误解的一点正是你刚才问的这个：

- 看起来前面已经有“向量化”这一步了
- 为什么 Chroma 这里还要知道 embedder 是谁？

答案是：

- **从业务流程概念上说，建索引当然包含“把 chunk 转成向量”这一步**
- **但从当前项目的代码实现上说，这一步不是我们自己先手工算完再传给 Chroma 的**

也就是说，当前项目里实际发生的是：

1. `files.py` 把文件解析成 `Document`
2. `split_documents()` 把 `Document` 切成 chunk
3. `_upsert_chunks()` 并没有自己先写 `vectors = ...`
4. 它是直接调用：
   - `self.vector_store.add_documents(documents=normalized_docs, ids=ids)`
5. 因为 `self.vector_store` 在初始化时已经带了：
   - `embedding_function=self.embedder`
6. 所以 Chroma 会在内部调用这个 embedder，把 chunk 文本转成向量后再入库

#### 也就是说，当前项目的真实代码路径是：

```text
chunk Document
-> add_documents(...)
-> Chroma 内部调用 embedding_function
-> 生成向量
-> 连同文本和 metadata 一起写入向量库
```

所以不是：

```text
chunk Document
-> 我们自己先手工算好向量
-> 再把纯向量塞给 Chroma
```

#### 为什么还要把“向量化”写在建索引流程里？
因为从业务逻辑角度看，这一步确实存在。

只是要区分两层：

- **业务流程层面**：建索引包含“chunk -> 向量”
- **代码执行层面**：这个转换动作是由 Chroma 通过 `embedding_function` 在内部触发的

所以更准确的说法应该是：

- 不是“我们先转好向量，再交给 Chroma”
- 而是“我们把 chunk 文本交给 Chroma，由它调用指定的 embedder 去完成向量化并入库”

这也正是为什么初始化 Chroma 时，必须知道：

- 该用哪个 embedder
- 因为后面 `add_documents()` 和检索 query 时，都要靠它来现算向量

#### 建索引到底是什么意思？
这个词在当前项目里，不只是“向量化”或者“切片”单独某一步，而是一个组合动作。

更完整地说，建索引通常包含：

1. 扫描源文件
2. 读取文件并生成 `Document`
3. 把 `Document` 切成 chunk
4. 把 chunk 变成向量
5. 把 chunk 原文、metadata、向量一起写进 Chroma

所以你的理解也基本是对的，但如果说得更严谨一点，应该是：

- **建索引 = 文件解析成 `Document` + 切片 + 向量化 + 写入 Chroma**

而不是只等于“切片和向量化”两个词。

#### 检索是干什么？
意思是：

- 用户提问后
- 把问题转成向量
- 先按当前用户和会话 scope 过滤 Chroma metadata
- 再去 Chroma 里找最相近的 chunk
- 再把结果包装成 `SearchHit`

对应方法是：

- `retrieve(query, top_k, scope_type, scope_id, workspace_key)`
- `_retrieve_candidates(...)`
- `_similarity_search_for_current_user(...)`

#### 组织上下文是干什么？
意思是：

- 命中的 chunk 结果不会原样全部塞给大模型
- 而是会先做去重、分组、裁剪、加引用标签
- 最后才变成真正给大模型的上下文

对应方法是：

- `_build_context(...)`
- 以及它前面的 `_select_hits_for_answer(...)`、`_group_hits_for_context(...)`

#### 调大模型生成回答是干什么？
意思是：

- 把整理好的上下文和用户问题交给 DeepSeek / Qwen / OpenAI-compatible LLM
- 再由大模型生成最终回答

所以 `KnowledgeBaseService` 不是只做“向量库”这一段，
而是把：

- 文件侧
- 检索侧
- 生成侧

这三部分串起来的总调度器。

你可以把它理解成：

- 当前项目里 RAG 主链路的“总导演”

#### 补充：`ChatMemoryService`
位置：

- `app/services/chat_memory.py`

这是最近新增的“聊天记忆 / 会话持久化”服务。

它不负责文件解析、切片、向量化、Chroma 检索，也不负责调用 LLM。

它负责的是：

- 创建 / 读取当前有效用户；未登录时默认回落到游客用户 `local-user`
- 创建 / 读取聊天会话，并绑定 `scope_type` / `scope_id` / `workspace_key`
- 列出会话列表，支持分页回显和范围标签
- 列出消息列表，支持按页回读
- 从 Redis 或 MySQL 回读最近消息窗口
- 把本轮用户消息写入 MySQL
- 把本轮助手回复写入 MySQL
- 保存 `usage` / `citations` / `model_diagnostics`
- 保存后刷新 Redis 最近消息缓存

它和 `KnowledgeBaseService` 的关系是：

```text
ChatMemoryService
├─ 负责“这是谁的哪条会话、最近聊了什么、这次会话属于哪个范围”
└─ 输出最近 history / 会话列表 / 消息列表

KnowledgeBaseService
├─ 负责“拿 history + 当前问题 + 知识库证据去生成回答”
└─ 输出 answer / sources / citations / usage / model_diagnostics
```

所以它们的边界很清楚：

- `ChatMemoryService` 管“对话状态”
- `KnowledgeBaseService` 管“RAG 问答链路”

#### 补充：`DocumentLibraryService`
位置：

- `app/services/document_library.py`

这是第三阶段后文档库的核心元数据服务。

它负责的是：

- 解析当前有效用户；未登录时回落到游客用户 `local-user`
- 创建 / 查询文档文件夹：`kop_document_folder`
- 创建 / 查询文档文件：`kop_document_file`
- 上传文件时把真实文件放到 `data/user_docs/{user_id}/{folder_id}/...`
- 给前端返回文件夹树和文件列表
- 按 `file_id` 做文件查看、编辑、删除、移动、重命名
- 移动 / 重命名文件或文件夹后，返回需要重建索引的 `file_ids` 和 `source_files`
- 给 `KnowledgeBaseService` 提供写入 Chroma 所需的索引 metadata

它和 `files.py` 的关系是：

```text
DocumentLibraryService
├─ 管数据库元数据、用户、文件夹、文件 ID、真实存储路径
└─ 输出文件路径和索引 metadata

files.py::load_documents_from_file(path)
├─ 只负责把某个真实文件解析成 list[Document]
└─ 不负责用户、文件夹、权限和数据库状态
```

所以现在“文档库”不是简单扫目录列表了，而是：

```text
MySQL 元数据
  +
data/user_docs/{user_id}/{folder_id}/真实文件
  +
Chroma metadata
```

三者一起组成完整文档库。

#### 补充：`UserAuthService`
位置：

- `app/services/auth.py`

这是现在登录 / 注册 / 游客回落的核心服务。

它负责的是：

- `/api/auth/me` 读取当前用户
- `/api/auth/login` 登录并写入 `kop_session` cookie
- `/api/auth/register` 注册用户并自动登录
- `/api/auth/logout` 删除 Redis session
- 没有登录态时自动解析或创建默认游客用户 `local-user`

它和 `CurrentUserContextMiddleware` 配合工作：

```text
每个请求进来
├─ CurrentUserContextMiddleware
│  ├─ 调用 UserAuthService.resolve_effective_user_id_from_request(...)
│  └─ 把 user_id 写入 request_context
├─ DocumentLibraryService / ChatMemoryService / KnowledgeBaseService
│  └─ 从 request_context 读取当前 user_id
└─ 如果没有登录态，就统一落到游客用户 local-user
```

这就是现在“未登录也能用，登录后按自己的数据隔离”的基础。

#### 补充：`database.py` 和 `redis_client.py`
新增位置：

- `app/core/database.py`
- `app/core/redis_client.py`

`database.py` 负责：

- 根据 `.env` 拼 MySQL 连接地址
- 创建 SQLAlchemy engine
- 提供 `session_scope()` 管理事务提交和回滚

`redis_client.py` 负责：

- 根据 `.env` 创建 Redis 客户端
- 给 `ChatMemoryService` 做最近消息缓存

这两个文件属于基础设施层，不直接参与 RAG 检索。

#### B. `LocalSentenceTransformerEmbeddings`
位置：

- `app/services/embeddings.py`

它负责把本地 `sentence-transformers` 模型包装成 LangChain `Embeddings` 接口。

你可以把它理解成：

- “向量化能力的适配器”

#### 这个 `embedder` 到底是什么？
在当前项目里，`embedder` 说的就是：

- `LocalSentenceTransformerEmbeddings` 这个对象

它不是一个单独的“新模型”，而是一个**会真正去执行向量化的对象**。

这个对象内部最关键的两个方法是：

- `embed_documents(texts)`
- `embed_query(text)`

#### `embed_documents(texts)` 是干什么的？
它负责：

- 接收一批文本
- 批量调用底层 `sentence-transformers` 的 `encode(...)`
- 返回一批向量

在你的代码里，这个方法本身就是“真正做文本转向量”的地方之一。

#### `embed_query(text)` 是干什么的？
它负责：

- 接收一条查询文本
- 调用底层模型的 `encode(...)`
- 返回这一条查询对应的向量

所以：

- `embed_documents()` 用在“批量 chunk 入库”场景
- `embed_query()` 用在“用户提问检索”场景

#### 那为什么你会觉得它和 Chroma 又重复了一次？
因为这里有两层视角，容易混在一起：

##### 视角 A：对象本身
`LocalSentenceTransformerEmbeddings` 这个对象自己就具备向量化能力。

也就是说：

- 它有 `embed_documents()`
- 它有 `embed_query()`
- 它能把文本变成向量

##### 视角 B：项目实际调用方式
当前项目通常不是我们手动去写：

```python
vectors = embedder.embed_documents(texts)
```

而是把这个 `embedder` 交给 Chroma：

- `Chroma(..., embedding_function=self.embedder)`

然后由 Chroma 在内部触发：

- 入库时调用 `embed_documents()`
- 检索时调用 `embed_query()`

所以你看到的不是“两次向量化”，而是：

- **同一个 embedder 对象，在两个不同场景里被使用**
- 一个场景是批量入库
- 一个场景是用户检索

#### 最后把三者的关系一句话记住

- `LocalSentenceTransformerEmbeddings` = embedder 对象
- `embed_documents()` / `embed_query()` = 这个对象真正负责向量化的方法
- `Chroma` = 在入库和检索时调用这些方法的上层向量库

#### C. `Chroma`
它是当前项目的向量库接口层。

在项目里它主要负责：

- 存 chunk
- 存 metadata
- 存向量
- 做相似度检索

#### D. `PersistentClient`
它是 Chroma 的底层持久化 client。

当前项目里它主要拿来做一些 collection 级别操作，比如：

- 按 `source` 删除旧 chunk

#### E. OpenAI-compatible LLM client
这个词可以拆成三层来理解，不然第一次看会比较绕：

#### 先说 `LLM` 是什么？
`LLM` 是 `Large Language Model` 的缩写，中文通常叫：

- 大语言模型

它指的是：

- 能理解自然语言
- 能根据上下文生成文本
- 能做总结、问答、改写、推理、结构化输出

在当前项目里，LLM 主要负责的是：

- 接收“用户问题 + 检索到的上下文”
- 生成最终回答

也就是说，LLM 不是拿来做向量检索的，而是拿来做：

- **最后一跳的回答生成**

#### 再说 `client` 是什么？
这里的 `client` 可以理解成：

- 代码里用来“连接并调用某个大模型服务”的客户端对象

比如当前项目里，代码会创建：

- `OpenAI(api_key=..., base_url=...)`

然后再通过这个 client 去调用：

- `client.chat.completions.create(...)`

所以这里的 `client` 不是模型本身，而是：

- “程序调用模型服务的接口对象”

你可以把它理解成：

- 模型在云端 / 服务端
- `client` 是我们本地代码用来发请求、拿结果的调用器

#### 再说 `OpenAI-compatible` 是什么意思？
这个是最关键的。

它的意思不是“只能调用 OpenAI”，而是：

- 这些模型服务虽然不一定是 OpenAI 官方提供的
- 但它们**兼容 OpenAI 风格的 API 协议**
- 所以代码层可以统一使用类似 OpenAI SDK 的调用方式

比如当前项目里虽然默认是 DeepSeek，但代码仍然可以这样写：

- `OpenAI(api_key=config.api_key, base_url=config.base_url)`
- `client.chat.completions.create(...)`

只要不同厂商支持这种兼容协议，就可以共用这套调用逻辑。

#### 在当前项目里，这个词具体意味着什么？
意思是：

- 生成层不是写死只连一个厂商
- 而是通过统一的 OpenAI-compatible client 方式
- 去连接不同 provider 的 LLM 服务

当前代码里可以挂的 provider 包括：

- DeepSeek
- Qwen
- OpenAI
- Kimi
- Hunyuan
- SiliconFlow
- Qianfan
- 以及其他兼容 provider

#### 当前项目里的真实代码形态
位置主要在：

- `app/services/knowledge_base.py`
- `app/core/settings.py`

你能看到这些关键点：

1. 代码里 `from openai import OpenAI`
2. 根据 provider 配置出：
   - `api_key`
   - `base_url`
3. 再创建：
   - `OpenAI(api_key=config.api_key, base_url=config.base_url)`
4. 最后调：
   - `client.chat.completions.create(...)`

所以这里的“OpenAI-compatible LLM client”更准确的意思是：

- **项目使用 OpenAI 风格的 SDK / 协议，去统一调用多个不同厂商的大语言模型服务**

#### 你可以把这几个词最后这样记

- `LLM` = 大语言模型本体，负责生成最终回答
- `client` = 代码里调用大模型服务的客户端对象
- `OpenAI-compatible` = 虽然厂商不同，但都尽量按 OpenAI 风格协议来调用

#### 和 embedding 模型的区别一定要分清
这两个特别容易混：

- embedding 模型：负责把文本转成向量
- LLM：负责根据上下文生成自然语言回答

也就是说：

- **向量化阶段**主要用 embedding 模型
- **回答生成阶段**主要用 LLM

虽然默认模型是 DeepSeek，但代码层其实走的是 OpenAI-compatible 调用方式。

也就是说这里的“生成层”是可替换的，当前可以挂：

- DeepSeek
- Qwen
- OpenAI
- 其他兼容 provider

#### 当前已经升级成 `LLMProviderAdapter` 分层

上面说的 OpenAI-compatible client 是协议层理解。
当前代码实现上，已经不再让 `KnowledgeBaseService` 自己直接包办所有 provider 调用细节，而是拆成了一个适配层：

```text
KnowledgeBaseService
├─ 负责 RAG 主流程
├─ 负责检索、上下文、prompt、引用、会话
└─ 把模型调用交给 LLMProviderAdapter

LLMProviderAdapter
├─ 负责创建 / 复用 provider client
├─ 负责 Chat Completions 调用
├─ 负责 Responses API 调用
├─ 负责参数失败后的 fallback
└─ 负责把不同 provider 的返回归一化给主流程
```

核心代码位置：

- `app/services/llm_provider_adapter.py`
- `app/services/llm_provider_mapping.py`
- `app/services/llm_streaming.py`
- `app/services/tools.py`

当前主要 adapter 是：

```text
LLMProviderAdapter
├─ OpenAICompatibleProviderAdapter
│  └─ DeepSeek / Qwen Chat Completions / OpenAI / Kimi / Hunyuan / 其他兼容网关
└─ QwenResponsesProviderAdapter
   └─ QWEN_RESPONSES_API_ENABLED=true 时，千问原生联网可走 responses.create()
```

这样做的意义是：

- `knowledge_base.py` 继续保持 RAG 编排职责
- provider 的特殊参数不再全部堆在 RAG 主流程里
- 后续本地模型、厂商 SDK、Responses API、更多多模态能力，都可以继续新增 adapter

#### 当前模型能力兼容层已经完成的基础阶段

目前“模型能力兼容层”已经完成 1-7 阶段基础闭环：

1. `LLMProviderAdapter` 正式化
2. 统一 `StreamingEvent`
3. `ToolRegistry` 和只读工具调用闭环
4. 多模态 `message_parts`
5. 千问 Responses API adapter
6. 前端模型诊断和健康检查可视化
7. `ModelCapability` 自动匹配与降级

这些阶段不是替代 RAG 主流程，而是在“生成层”周围加了一圈工程化能力：

```text
RAG 主流程
├─ 仍然负责检索和上下文组织
└─ 生成层增强
   ├─ provider adapter
   ├─ model capability
   ├─ streaming event
   ├─ tool registry
   ├─ multimodal message parts
   └─ diagnostics
```

### 1.3 再记住这几个关键方法

下面这些方法，后面在主流程里会反复出现：

#### A. `iter_source_files()`
位置：

- `app/services/files.py`

作用：

- 扫描 `data/user_docs`
- 返回受支持的文件路径列表

#### B. `load_documents_from_file(path)`
位置：

- `app/services/files.py`

作用：

- 把一个原始文件解析成 `list[Document]`

这是“原始文件进入知识库链路”的真正入口。

#### C. `split_documents(documents)`
位置：

- `app/services/knowledge_base.py`

作用：

- 把原始 `Document` 列表切成更适合检索的 chunk 列表

#### D. `_build_vector_store()`
位置：

- `app/services/knowledge_base.py`

作用：

- 初始化 `Chroma`
- 把 `embedding_function=self.embedder` 挂进去

#### E. `_upsert_chunks(chunks)`
位置：

- `app/services/knowledge_base.py`

作用：

- 把切好的 chunk 批量写入 Chroma

#### F. `rebuild_index()`
作用：

- 全量重建索引

#### G. `reindex_source_file(path)`
作用：

- 只重建单个文件对应的 chunk

#### H. `reindex_document_files(file_ids, source_paths)`
作用：

- 第三阶段后更推荐的“按数据库文件 ID 重建索引”入口
- 先按 `file_id` 删除旧 chunk
- 再按当前数据库 metadata 和真实文件路径重新解析、切片、写入 Chroma
- 文件移动、重命名、文件夹移动、文件夹重命名后都会优先走这条链路

#### I. `delete_chunks_by_file_ids(file_ids)`
作用：

- 按 Chroma metadata 里的 `file_id` 删除对应 chunk
- 文件删除和文件夹删除后使用
- 比只按 `source path` 删除更适合现在的数据库文档库模型

#### J. `retrieve(query, top_k, scope_type, scope_id, workspace_key)`
作用：

- 做基础检索
- 返回 `SearchHit` 列表
- 默认按当前用户过滤
- 如果传了文件夹 / 知识库 / 工作区范围，还会追加 metadata filter

#### K. `_build_context(...)`
作用：

- 把命中的 chunk 组织成给大模型使用的上下文块

#### L. `answer()` / `stream_answer()`
作用：

- 走完整的“检索 + 生成回答”链路
- `answer()` 用于普通 JSON 响应
- `stream_answer()` 用于 SSE 流式响应
- 会先解析模型、provider、capability
- 会把 `message_parts` 转成 provider 可用的内容
- 会按模型能力决定是否开启工具调用、图片输入、Responses API
- 会把 `model_diagnostics` 带回前端和聊天记录

#### L-1. `_prepare_answer(...)`
作用：

- 归一化 `message_parts`
- 把文本、图片、文件引用整理成检索问题和 provider 输入
- 根据当前用户和会话 scope 检索 Chroma
- 组织证据上下文、引用标签、web context
- 输出最终要交给模型的 `messages`

它是“RAG 检索”和“模型生成”之间的准备层。

#### L-2. `_chat_completion_with_tools(...)` / `_stream_completion_with_tools(...)`
作用：

- 在 provider 支持工具调用时，把 `ToolRegistry` 里的只读工具传给模型
- 如果模型返回 `tool_calls`，后端执行工具
- 再把 `role=tool` 的结果回传模型
- 最后让模型生成自然语言回答

区别是：

- `_chat_completion_with_tools(...)` 服务普通 `/api/chat`
- `_stream_completion_with_tools(...)` 服务 `/api/chat/stream`

当前工具调用是保守设计，只开放只读工具，不能让模型直接删除文件、改文件、写数据库。

#### L-3. `_message_parts_to_provider_content(...)`
作用：

- 把 `ChatMessagePart` 转成 provider 能接收的 OpenAI-compatible message content
- 支持 `text`
- 支持 `image_url`
- 支持 `file_ref` 文本化引用

它会按 `ModelCapability.supports_multimodal_input` 做判断：

- 支持图片：把 `image_url` 原样传给 provider
- 不支持图片：把图片降级成文本引用，并写入 warning

#### L-4. `_build_model_diagnostics(...)`
作用：

- 为每次回答构建模型诊断信息
- 记录 provider / requested_model / resolved_model
- 记录是否用了原生联网 / 外部联网
- 记录 provider API
- 记录本次模型能力快照
- 记录 warnings 和 fallback

#### L-5. `run_mode`

`run_mode` 是当前聊天链路新补上的“运行模式”字段。

位置：

- 后端请求：`app/schemas.py::ChatRequest`
- 后端主流程：`app/services/knowledge_base.py::answer()` / `stream_answer()`
- 前端类型：`frontend/src/api.ts::RunMode`
- 前端状态：`frontend/src/composables/useChatWorkspace.ts`
- 前端入口：`frontend/src/components/chat/ChatComposer.vue`

当前取值：

```text
chat：普通聊天
rag：知识库问答
agent：单 Agent 工具调用模式
```

三种模式的区别：

```text
chat
├─ 不主动检索知识库
├─ 系统提示词会明确说明“不要假装已经查过知识库”
└─ 适合普通闲聊、解释概念、非知识库问题

rag
├─ 保持原来的 RAG 主流程
├─ 先按当前用户和会话范围检索 Chroma
├─ 再把证据上下文交给模型生成答案
└─ 适合基于知识库证据回答

agent
├─ 使用 Agent 系统提示词
├─ 在模型支持 tool calling 时注册 ToolRegistry
├─ 模型可以按需调用知识库搜索、文档列表、文档元数据、文档摘要、网页搜索、邮件发送等工具
├─ 工具调用过程会进入 model_diagnostics.tool_calls
└─ 写入类 / 高风险工具必须先进入用户确认流程
```

这个字段的意义是：

- 前端不再只有“问答”一种行为
- 后端可以根据用户选择切换不同 prompt 和执行策略
- 后续做多 Agent 或任务编排时，可以继续扩展 `run_mode`

#### L-6. `ToolSpec` / `ToolExecutionResult`

当前工具系统已经不再只是一个函数名列表，而是统一成 `ToolSpec`。

位置：

- `app/services/tools.py`

`ToolSpec` 负责描述一个工具：

```text
name：模型调用时使用的工具名
display_name：前端展示用中文名
description：给模型看的工具说明
parameters：OpenAI-compatible function schema
risk_level：read / write / dangerous
requires_confirmation：是否需要用户确认
default_enabled：是否默认暴露给模型
handler：真实执行函数
summarize_result：工具结果摘要函数
confirmation_requester：确认型工具的确认请求创建函数
```

`ToolExecutionResult` 负责描述一次工具执行结果：

```text
name
display_name
arguments
status：success / error / pending_confirmation
content：回传给模型的工具原始结果
summary：给前端看的摘要
duration_ms
risk_level
requires_confirmation
default_enabled
error
confirmation_id
confirmation_message
```

这样前端就可以把工具调用展示成“用户看得懂的轨迹”，而不是只显示底层函数名。

#### L-7. `AgentToolConfirmationService`

这是第二阶段新增的确认型工具服务。

位置：

- `app/services/agent_tools.py`
- `app/dependencies.py::get_agent_tool_confirmation_service()`
- `app/api/routes.py`

它解决的问题是：

- 模型不能直接执行会修改数据的工具
- 写入类工具要先生成一个待确认动作
- 用户确认后，后端再执行真实操作
- 用户取消后，后端不执行

当前快速版是**内存队列**：

```text
AgentToolConfirmationService
├─ create()：创建 pending 确认项
├─ confirm()：确认后执行注册好的 executor
├─ cancel()：取消确认项
├─ get()：查询确认项
└─ register_executor()：注册真正的工具执行函数
```

确认项状态：

```text
pending：等待用户确认
confirmed：已确认且已执行
cancelled：用户已取消
expired：已过期
failed：确认执行失败
```

当前限制：

- 确认项暂存在后端进程内存
- 后端重启后未处理的确认项会丢失
- 后续正式版建议落 MySQL 表 `agent_tool_confirmations`

#### L-8. `rebuild_file_index`

这是当前第一个确认型工具。

位置：

- 工具定义：`app/services/tools.py::build_readonly_tool_registry(...)`
- 确认请求：`app/services/knowledge_base.py::_request_tool_confirmation(...)`
- 确认执行：`app/services/knowledge_base.py::confirmed_rebuild_file_index(...)`
- 确认接口：`POST /api/agent/tool-confirmations/{confirmation_id}/confirm`
- 取消接口：`POST /api/agent/tool-confirmations/{confirmation_id}/cancel`

它的行为是：

```text
模型请求 rebuild_file_index(file_id)
├─ ToolRegistry 发现 requires_confirmation=true
├─ 不直接执行重建索引
├─ 创建 confirmation_id
├─ 返回 status=pending_confirmation
├─ 前端展示确认卡片
├─ 用户点击确认
├─ 后端执行 confirmed_rebuild_file_index()
├─ 按 file_id 找到文件 metadata 和真实 path
├─ 更新索引状态 queued -> running
├─ 调用 reindex_document_files(file_ids=[file_id], source_paths=[path])
├─ 成功后更新索引状态 success
└─ 前端把确认结果回写到同一条工具调用卡片
```

为什么先选它作为第一个确认型工具：

- 它确实会修改索引状态和向量库内容
- 但不删除用户源文件
- 风险比删除文件、移动文件、改文件低
- 很适合验证确认机制是否跑通

`rebuild_file_index` 也有一个保守兜底：

```text
用户明确说“重建索引 / 重新索引 / reindex”
├─ 原始问题或模型回答里能提取到 file_id
├─ 或用户说“第一个文件 / 第一个文档”，后端能从文档列表拿到第一个 file_id
├─ 模型没有主动调用 rebuild_file_index
└─ 后端创建 rebuild_file_index pending_confirmation
```

这个兜底解决的是：模型有时会先调用 `list_documents` 找到文件，然后在正文里问“是否确认重建索引”，但没有真正发起 `rebuild_file_index` tool call。前端只有收到 `model_diagnostics.tool_calls` 里的 `pending_confirmation` 诊断时才会出现确认按钮，所以后端会在这种明确场景下补一个真实确认项。

兜底仍然不会直接重建索引。它只是创建确认卡片，最终重建仍然必须由用户点击确认触发。

#### L-9. `send_email`

这是当前接入的第一个外部动作型 Agent 工具。

位置：

- 工具定义：`app/services/tools.py::build_readonly_tool_registry(...)`
- SMTP 配置：`app/core/settings.py`
- 邮件发送服务：`app/services/email_sender.py`
- 确认请求：`app/services/knowledge_base.py::_request_send_email_confirmation(...)`
- 确认执行：`app/services/knowledge_base.py::confirmed_send_email(...)`
- 前端预览：`frontend/src/components/chat/MessageItem.vue`

它的行为是：

```text
模型请求 send_email(to, cc, subject, body)
├─ ToolRegistry 发现 requires_confirmation=true
├─ 不直接调用 SMTP
├─ 创建 confirmation_id
├─ 返回 status=pending_confirmation
├─ 前端展示确认卡片
│  ├─ 收件人
│  ├─ 抄送
│  ├─ 主题
│  └─ 正文预览
├─ 用户点击确认
├─ 后端执行 confirmed_send_email()
├─ EmailSender 校验 SMTP 配置、收件人、主题、正文和域名白名单
├─ 通过 SMTP 发送纯文本邮件
└─ 前端把确认结果回写到同一条工具调用卡片
```

它不会默认暴露给模型。必须满足：

```text
EMAIL_TOOL_ENABLED=true
SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD 配置完整
SMTP_FROM_EMAIL 或 SMTP_USERNAME 可作为发件人
```

为什么它必须走确认：

- 邮件会离开本系统，属于真实外部动作
- 误发邮件的后果比普通查询更明显
- 模型可能误解收件人、主题或正文
- 用户确认卡片可以在发送前最后检查内容

可选安全配置：

```text
EMAIL_TOOL_MAX_RECIPIENTS：限制单次收件人和抄送总数
EMAIL_TOOL_ALLOWED_DOMAINS：限制允许发送到哪些邮箱域名
SMTP_TIMEOUT_SEC：限制 SMTP 阻塞时间
```

#### M. `_resolve_chat_memory_context(...)`
位置：

- `app/api/routes.py`

作用：

- 在真正调用 RAG 问答之前，先处理聊天记忆
- 如果请求里没有 `conversation_id`，就自动创建一条后端会话
- 如果请求里带了 `conversation_id`，就读取这条会话的最近消息
- 如果 MySQL / Redis 不可用，就降级使用前端传来的 `history`

它是新增聊天记忆链路的“前置入口”。

#### N. `_save_chat_memory_turn(...)`
位置：

- `app/api/routes.py`

作用：

- 在模型回答完成以后，把本轮对话写回 MySQL
- 写入一条 `user` 消息
- 写入一条 `assistant` 消息
- 保存引用、usage、改写问题、模型诊断等元信息

它是新增聊天记忆链路的“后置落库入口”。

### 1.4 这些功能在业务上分别是什么意思？

#### A. 文件解析
意思是：

- 把 txt、pdf、docx、xlsx、pptx 等文件内容抽出来
- 统一变成 `Document`

#### B. 建索引
意思是：

- 把文本切成 chunk
- 把 chunk 变成向量
- 把结果写进 Chroma

#### C. 检索
意思是：

- 用户提问后
- 用问题向量去找最相关的 chunk

#### D. 生成回答
意思是：

- 把检索命中的上下文交给大模型
- 由大模型组织最终回答

#### E. 全量重建索引
意思是：

- 把整个知识库重新扫描、重新切片、重新写库

#### F. 单文件增量重建索引
意思是：

- 只删掉某个文件原来的 chunk
- 再把这个文件重新解析、切片、写回库里

#### G. ONLYOFFICE 保存后更新索引
意思是：

- 用户在 ONLYOFFICE 编辑保存后
- 后端收到回调
- 再去触发这个文件的索引更新

### 1.5 再把容易混淆的名词和库先讲清楚

#### A. `embedding`
它是一个动作名，不是具体模型名。

意思是：

- 把文本转换成向量

#### B. `BAAI/bge-small-zh-v1.5`
它是当前默认 embedding 模型名。

也就是说：

- 真正算向量时，底层默认跑的是它

#### C. `sentence-transformers`
它是运行 embedding 模型的 Python 库。

作用是：

- 加载模型
- 调 `encode(...)`
- 产出向量

#### D. `LangChain`
它在当前项目里更像一个“接口规范层”。

它帮我们统一了这些东西：

- `Document`
- `Embeddings`
- `TextSplitter`
- 和 Chroma 这类组件的衔接方式

这里面最容易混淆的是：

- 哪些是“数据结构 / 对象”
- 哪些是“能力接口”
- 哪些是“执行动作的组件”

可以这样拆开记：

#### `Document` 是什么？
对，`Document` 确实是 LangChain 体系里的标准文档对象。

也就是说：

- 你现在项目里文件解析后得到的 `Document`
- 其中包含的 `page_content`
- 以及 `metadata`

本质上就是在使用 LangChain 提供的这套数据对象规范。

所以可以更准确地说：

- **文件解析阶段负责生成 `Document`**
- **而 `Document` 这个对象的形状，本身是 LangChain 这边统一好的**

你可以把它理解成：

- 业务代码负责“往里面装什么内容”
- LangChain 负责“这个标准对象长什么样”

在当前项目里，对应过程就是：

1. `files.py` 先解析原始文件
2. 再包装成 LangChain `Document`
3. 后面的切片器、Chroma、检索流程都继续沿用这个统一结构

#### `Embeddings` 是什么？
`Embeddings` 也是 LangChain 的统一接口，不是某个具体模型名。

它规定的是：

- 文本怎么批量转向量
- 单条 query 怎么转向量

在当前项目里：

- `LocalSentenceTransformerEmbeddings`
- 继承的就是 LangChain `Embeddings`

也就是说：

- 具体模型可以是 `BAAI/bge-small-zh-v1.5`
- 具体运行库可以是 `sentence-transformers`
- 但对上层暴露出来的调用方式，走的是 LangChain `Embeddings` 规范

#### `TextSplitter` 是什么？
这个不是“文件切片后的数据结构”，而是：

- **负责执行切片动作的组件 / 接口类型**

你可以把它理解成：

- `Document` 是被处理的数据对象
- `TextSplitter` 是处理这些对象、把它们切小的工具

所以它更像：

- 切片器
- 切分策略组件
- 文本分块工具

而不是：

- 最终存储结构
- 结果对象类型

#### 当前项目里真正用到的 `TextSplitter` 是哪个？
是：

- `RecursiveCharacterTextSplitter`

它是 LangChain 提供的一个具体切片器实现。

当前项目里做的事情是：

- 输入：原始 `list[Document]`
- 调用：`split_documents(documents)`
- 输出：切小后的 `list[Document]`

注意这里很关键：

- **切片前是 `Document` 列表**
- **切片后其实还是 `Document` 列表**
- 只是这些更小的 `Document`，业务上我们叫它 chunk

所以：

- `TextSplitter` 不是结果数据结构
- chunk 也不是 LangChain 里单独定义的新类
- chunk 只是“切片后的 `Document`”这件事的业务叫法

#### LangChain 在这里到底帮了什么忙？
它不是替你写完整个业务，而是帮你把这些关键边界统一了：

1. **统一文档对象**
   - 用 `Document` 表示“待处理文本 + metadata”
2. **统一向量化接口**
   - 用 `Embeddings` 表示“文本 -> 向量”的能力
3. **统一切片组件接口**
   - 用 `TextSplitter` / `RecursiveCharacterTextSplitter` 表示“怎么切文本”
4. **统一和向量库的对接方式**
   - Chroma 可以直接接 `Document` + `Embeddings`

所以你可以把 LangChain 理解成：

- 它不是你业务本身
- 但它把“文档对象、切片器、向量化接口、向量库衔接方式”先标准化了
- 这样你的业务代码就不用自己从零定义这整套协议

#### 最后一句最好记的话

- `Document` = LangChain 定义的标准文档对象
- `TextSplitter` = LangChain 提供的切片组件类型
- `RecursiveCharacterTextSplitter` = 当前项目实际使用的具体切片器
- chunk = 切片后的 `Document` 的业务叫法

#### E. `Chroma`
它是向量库，不是大模型。

它负责：

- 存储向量
- 存储 chunk 文本
- 存储 metadata
- 做相似度检索

#### F. `pypdf`
它用于：

- 读取 PDF
- 按页抽取文本

#### G. `python-docx`
它用于：

- 读取 `.docx`
- 抽正文与表格

#### H. `python-pptx`
它用于：

- 读取 `.pptx`
- 按 slide 抽文本和表格

#### I. `openpyxl` / `xlrd`
它们用于：

- 读取 Excel 内容
- 把 sheet 结构转成可索引文本

#### J. `LibreOffice`
它在当前项目里主要是兜底工具，不是主链路核心。

当前主要用在：

- 老格式 `.ppt` 转 `.pptx`
- 某些 Office 文件的 PDF 预览兜底

### 1.6 先把最容易混淆的三个问题讲清楚

#### 1）本地 embedding 模型是 LangChain 的一部分吗？

**不是。**

更准确地说，这里其实有 4 层东西，你不要把它们看成同一个层级：

1. `embedding`
   - 这是“动作 / 能力名”
   - 意思是：把文本变成向量
   - 它不是一个具体库名，也不是一个具体模型名

2. `BAAI/bge-small-zh-v1.5`
   - 这是“具体模型名”
   - 也就是当前项目默认使用的 embedding 模型
   - 真正算向量时，最后跑的是这个模型

3. `sentence-transformers`
   - 这是“模型运行库 / Python 包”
   - 作用是：负责把 `BAAI/bge-small-zh-v1.5` 这样的模型加载起来，并执行 `encode(...)`
   - 你可以把它理解成“运行这个 embedding 模型的发动机”

4. `LangChain`
   - 这是“上层框架接口”
   - 在当前项目里，它没有提供 embedding 模型本体
   - 它主要提供的是 `Embeddings` 这层统一接口，让上层 Chroma / 检索逻辑能用统一方式接入

#### 一句话记住

- `embedding` = 要做的事情
- `BAAI/bge-small-zh-v1.5` = 具体拿来算向量的模型
- `sentence-transformers` = 负责加载并运行这个模型的库
- `LangChain` = 给上层系统提供统一调用接口的框架层

#### 当前项目里的真实调用链

1. 代码先进入 `LocalSentenceTransformerEmbeddings`
2. 这个类继承了 LangChain 的 `Embeddings`
3. 类内部 `from sentence_transformers import SentenceTransformer`
4. 然后实例化：`SentenceTransformer(model_name, device=device)`
5. 这里的 `model_name` 默认就是 `BAAI/bge-small-zh-v1.5`
6. 后面真正做向量化时，调用的是 `self._model.encode(...)`

所以当前项目的更准确说法应该是：

- **真正算向量的具体模型**：`BAAI/bge-small-zh-v1.5`
- **真正加载和运行这个模型的库**：`sentence-transformers`
- **对上层暴露统一 embedding 接口的框架层**：LangChain `Embeddings`

#### 2）Chroma 是向量库吗？和 embedding 模型什么关系？

**是，Chroma 就是当前项目里的向量库。**

但它和 embedding 模型不是一回事。

可以这样区分：

- embedding 模型负责“把文本变成向量”
- Chroma 负责“存这些向量，并做相似度检索”

关系是：

1. embedding 模型先把文本转成向量
2. Chroma 把这些向量存起来
3. 用户提问时，再把问题转成向量
4. Chroma 用“问题向量”去库里找最接近的文档向量

#### 3）“让 Chroma 做语义相似度检索” 到底是什么意思？

意思是：

- 不是用数据库里的 `LIKE '%关键词%'`
- 也不是只看字面是否完全重合
- 而是把“问题”和“文档 chunk”都转换成向量
- 再比较向量之间的距离 / 相似度

当前项目里真正调用的位置在：

- `app/services/knowledge_base.py`
- `similarity_search_with_relevance_scores(...)`

也就是说，真正做“找最像的几段文本”的不是 DeepSeek，
而是 **Chroma + embedding 模型的组合**：

- embedding 模型负责把文本转成向量
- Chroma 负责在向量空间里找最接近的 chunk

---

## 2. 带着前置知识再看一眼总体角色图

现在先别急着进完整主流程，先把整体角色分工看一遍，后面读流程会轻松很多。

### 2.1 文件解析层

负责把原始文件转成“可检索文本”。

对应代码：

- `app/services/files.py`
- 核心入口：`load_documents_from_file(path)`

支持的事情包括：

- 读文本文件
- 抽取 PDF 文本
- 抽取 docx / pptx / xlsx 等 Office 内容
- 老格式 `.ppt` 必要时借助 LibreOffice 转换后再抽取

### 2.2 切片层

负责把大文档拆成更适合检索的小块。

对应代码：

- `app/services/knowledge_base.py`
- 核心函数：`split_documents(documents)`

当前具体实现：

- `RecursiveCharacterTextSplitter`

### 2.3 embedding 层

负责把 chunk 和 query 转成向量。

对应代码：

- `app/services/embeddings.py`
- 核心类：`LocalSentenceTransformerEmbeddings`

底层模型：

- `sentence-transformers`
- 默认模型：`BAAI/bge-small-zh-v1.5`

### 2.4 向量库存储与检索层

负责：

- 存储 chunk 向量
- 存储 chunk metadata
- 做相似度检索
- 按当前用户过滤
- 按会话 scope 过滤：全部 / 文件夹 / 知识库 / 工作区

对应代码：

- `app/services/knowledge_base.py`
- `_build_vector_store()`
- `retrieve()`
- `_retrieve_candidates()`
- `_similarity_search_for_current_user()`
- `_current_user_filter()`

底层中间件：

- `Chroma`
- `chromadb.PersistentClient`

### 2.4.1 文档库元数据层

负责把“文件系统里的真实文件”和“业务上的用户 / 文件夹 / 知识库 / 工作区”连起来。

对应代码：

- `app/services/document_library.py`
- `DocumentLibraryService`

底层表：

- `kop_document_folder`
- `kop_document_file`
- `kop_kb`
- `kop_workspace`

它提供给 RAG 的关键字段是：

- `user_id`
- `file_id`
- `folder_id`
- `kb_id`
- `workspace_key`
- `display_path`

这些字段会进入 Chroma metadata，后面检索和引用展示都要用。

### 2.5 生成层

负责根据检索结果组织最终回答。

对应代码：

- `app/services/knowledge_base.py`
- `answer()` / `stream_answer()` 链路
- `_prepare_answer(...)`
- `_build_context(...)`
- `_chat_completion(...)`
- `_chat_completion_with_tools(...)`
- `_stream_completion_with_tools(...)`
- `app/services/llm_provider_adapter.py`
- `app/services/llm_provider_mapping.py`
- `app/services/llm_streaming.py`
- `app/services/tools.py`

底层模型：

- DeepSeek / Qwen / OpenAI 等 OpenAI-compatible provider
- 当前默认主模型：`DEEPSEEK_MODEL=deepseek-v4-flash`
- `llm_provider_adapter.py` 负责 provider 调用、Chat Completions / Responses API、fallback
- `llm_provider_mapping.py` 负责模型能力、provider 参数和能力降级判断
- `llm_streaming.py` 负责统一正文、思考、工具、usage、diagnostics 等流式事件
- `tools.py` 负责只读工具注册和 tool calling 执行
- `model_diagnostics` 负责回传实际 provider、model、联网、思考、工具、图片、Responses 和 fallback 信息

现在生成层已经不是简单“调用 DeepSeek 得到一段文本”，而是：

```text
生成层
├─ 解析模型和 provider
├─ 解析 ModelCapability
├─ 处理 message_parts
├─ 读取 run_mode：chat / rag / agent
├─ 按能力决定是否启用图片输入
├─ 按能力决定是否启用 tool calling
├─ 按能力决定是否启用 Qwen Responses API
├─ 调用 provider adapter
├─ 流式时统一成 StreamingEvent
└─ 把 model_diagnostics 返回前端和落库
```

如果 `run_mode=agent`，生成层会额外进入工具编排路径：

```text
Agent 生成层
├─ 根据当前用户和会话范围构建 ToolRegistry
├─ 注册只读工具
│  ├─ search_knowledge_base
│  ├─ list_documents
│  ├─ get_document_metadata
│  ├─ read_document_summary
│  └─ search_web（仅外部搜索配置可用时）
├─ 注册确认型工具
│  └─ rebuild_file_index
├─ 将 OpenAI-compatible tools schema 传给支持 tool calling 的模型
├─ 模型返回 tool_calls
├─ 后端执行 read 工具，或为 write 工具创建 confirmation
├─ 工具调用诊断进入 model_diagnostics.tool_calls
└─ 模型基于工具结果生成最终回答
```

### 2.6 API 层

负责把这些能力暴露给前端。

对应代码：

- `app/api/routes.py`

典型接口：

- 登录 / 注册 / 当前用户：`/api/auth/*`
- 文档列表、上传、文件夹、文件移动 / 重命名 / 删除
- 上传与建索引
- 搜索
- 聊天
- 聊天配置：`/api/chat/options`
- 会话列表与消息列表：`/api/chat/conversations`
- Agent 工具确认：`/api/agent/tool-confirmations/{confirmation_id}/confirm` / `cancel`
- ONLYOFFICE 保存回调后的索引更新

### 2.7 聊天记忆层

负责把“聊天窗口”变成“可持续的后端会话”。

对应代码：

- `app/services/chat_memory.py`
- `app/core/database.py`
- `app/core/redis_client.py`
- `app/api/routes.py`

底层中间件：

- MySQL
- Redis

当前已经落地的职责：

- 未登录时默认使用游客用户 `local-user`
- 登录后按 session / token 对应的真实用户继续使用同一个会话体系
- MySQL 保存原始聊天记录
- Redis 缓存最近消息窗口
- 前端通过 `conversation_id` 关联后端会话
- 会话列表接口支持分页回显，并带 `scope_name` / `scope_type` / `scope_id` / `workspace_key`
- 消息列表接口支持分页读取和上拉补历史
- 后端回答前回读最近消息
- 后端回答后保存本轮消息，并把 `usage` / `citations` / `model_diagnostics` 一起落库

它和 Chroma 的分工是：

- Chroma 保存“知识库文件切片”
- MySQL 保存“聊天原始记录”
- Redis 保存“最近聊天窗口缓存”

所以现在它已经不只是简单“缓存一下历史”，而是完整承担了：

- 用户身份回落
- 会话持久化
- 会话回显
- 最近上下文缓存

---

## 3. 完整主流程图

下面这张树状图先给你一个“全链路总览”，重点不是装饰，而是把每个动作背后的对象、方法和原理摆出来：

```text
原始文件
├─ 文件来源
│  ├─ 业务元数据：kop_document_file / kop_document_folder
│  └─ 新文档库存储目录：data/user_docs/{user_id}/{folder_id}
├─ 当前用户
│  └─ app/main.py::CurrentUserContextMiddleware
│     ├─ 已登录：解析 kop_session 对应 user_id
│     └─ 未登录：回落到游客用户 local-user
├─ 文档库元数据服务
│  └─ app/services/document_library.py::DocumentLibraryService
│     ├─ 上传时写入 kop_document_file
│     ├─ 文件夹写入 kop_document_folder
│     ├─ 返回 file_id / folder_id / display_path
│     └─ 建索引时提供 user_id / file_id / folder_id / kb_id / workspace_key
├─ 文件扫描器
│  └─ app/services/files.py::iter_source_files()
│     └─ 找到受支持的扩展名，交给后面的解析器
├─ 文件解析器
│  └─ app/services/files.py::load_documents_from_file(path)
│     ├─ 统一输出 LangChain Document
│     ├─ 生成基础 metadata：source / file_name / extension
│     ├─ txt/md/json/yaml/sql/代码等文本文件
│     │  └─ 直接 read_text() 读成一个 Document
│     ├─ pdf
│     │  └─ 用 pypdf.PdfReader 按页抽取，每页一个 Document
│     ├─ docx
│     │  └─ 用 python-docx 抽正文和表格，合成一个 Document
│     ├─ xlsx/xls/xlsm
│     │  └─ 每个 sheet 先转成 markdown/plain 文本，再按 sheet 生成 Document
│     ├─ pptx
│     │  └─ 用 python-pptx 按 slide 抽取，每个 slide 一个 Document
│     ├─ ppt
│     │  └─ 先调用 LibreOffice soffice 转成 pptx，再走 pptx 解析
│     └─ doc
│        └─ 先尽力用 antiword/catdoc/ole 兜底抽取，再生成 Document
├─ 索引 metadata 合并
│  └─ app/services/knowledge_base.py::_attach_index_metadata(...)
│     ├─ 从 DocumentLibraryService.get_index_metadata_by_storage_path(...) 读取 DB 元数据
│     └─ 合并 user_id / file_id / folder_id / kb_id / workspace_key / display_path 等字段
├─ Document 为什么一定要先出现？
│  └─ 因为后面的切片器、向量化器、Chroma 写入接口，输入都按 Document 这个统一结构来接
├─ 切片器
│  └─ app/services/knowledge_base.py::split_documents(documents)
│     ├─ 使用 RecursiveCharacterTextSplitter
│     ├─ 按 chunk_size / chunk_overlap 切块
│     ├─ 按段落、换行、英文标点、中文标点、空格逐级兜底
│     └─ 每个 chunk 额外补 metadata：chunk_index / char_count
├─ 向量化适配器
│  └─ app/services/embeddings.py::LocalSentenceTransformerEmbeddings
│     ├─ 继承 LangChain 的 Embeddings 接口
│     ├─ 内部真正跑的是 sentence-transformers
│     ├─ 先尝试本地缓存加载
│     ├─ 再尝试 HF_ENDPOINT
│     ├─ 再尝试 HF_FALLBACK_ENDPOINT
│     ├─ embed_documents(texts)
│     │  └─ 把 chunk 文本批量 encode 成向量
│     └─ embed_query(text)
│        └─ 把用户问题转成向量
├─ 向量库存储
│  └─ app/services/knowledge_base.py::_build_vector_store()
│     ├─ 组件：Chroma
│     ├─ 参数：embedding_function=self.embedder
│     ├─ 原理：把“如何算向量”交给 embedding_function
│     └─ add_documents() 时由 Chroma 内部自动调用 embedder
├─ 入库
│  └─ app/services/knowledge_base.py::_upsert_chunks(chunks)
│     ├─ 先规范化 metadata
│     ├─ 用 content + metadata 算 hash 作为 ids
│     ├─ 把 chunk 重新构造成 Document
│     └─ 调用 self.vector_store.add_documents(...)
│        └─ Chroma 自动完成：文本 -> 向量 -> 持久化
├─ 检索
│  └─ app/services/knowledge_base.py::retrieve(query, top_k, scope_type, scope_id, workspace_key)
│     ├─ _current_user_filter(...) 先按 user_id 过滤
│     ├─ scope_type=folder 时包含当前文件夹和所有子文件夹
│     ├─ scope_type=kb 时按 kb_id 过滤
│     ├─ scope_type=workspace 时按 workspace_key 过滤
│     ├─ Chroma 内部先调用同一个 embedding_function 把 query 向量化
│     ├─ 再做相似度检索
│     └─ 返回相关 chunk，并整理成 SearchHit
└─ 生成回答
   └─ app/services/knowledge_base.py::_build_context() + answer()/stream_answer()
      ├─ 把检索命中的 chunk 组装成上下文
      ├─ 解析 model -> provider -> ModelCapability
      ├─ 处理 message_parts：text / image_url / file_ref
      ├─ 如果模型支持图片，image_url 原样进入 provider message
      ├─ 如果模型不支持图片，image_url 降级成文本摘要并写 warning
      ├─ 如果模型支持工具调用，构建 ToolRegistry 只读工具
      ├─ 如果模型是千问且启用 Responses API，可优先走 QwenResponsesProviderAdapter
      ├─ 否则走 OpenAICompatibleProviderAdapter / Chat Completions
      ├─ 流式输出时统一成 StreamingEvent
      ├─ 由大模型负责最终回答生成
      └─ 返回 answer / citations / usage / cost_estimate / model_diagnostics
```

### 补充：Agent 模式和确认型工具流程

当用户在前端选择 `Agent` 模式时，请求里会带：

```json
{
  "run_mode": "agent"
}
```

这时完整链路会变成：

```text
用户提问
├─ 前端 ChatComposer 发送 run_mode=agent
├─ app/api/routes.py 接收 ChatRequest
├─ KnowledgeBaseService.stream_answer(...)
├─ _prepare_answer(...) 按当前用户和会话范围准备上下文
├─ 判断当前模型 capability.supports_tool_calling
│  ├─ 不支持：写入 warning，走普通生成
│  └─ 支持：构建 ToolRegistry
├─ ToolRegistry 暴露工具 schema 给模型
├─ 模型按需返回 tool_calls
├─ 后端执行工具
│  ├─ read 工具：直接执行
│  └─ write / dangerous 工具：创建 pending_confirmation，不直接执行
├─ 工具调用结果写入 model_diagnostics.tool_calls
├─ 前端 MessageItem 展示工具调用轨迹
└─ 模型生成最终回答
```

确认型工具以 `rebuild_file_index` 为例：

```text
模型请求 rebuild_file_index(file_id=123)
├─ tools.py 发现 requires_confirmation=true
├─ ToolRegistry 返回 status=pending_confirmation
├─ knowledge_base.py 创建 confirmation_id
├─ 前端显示“待确认操作”卡片
│  ├─ 确认执行
│  └─ 取消
├─ 用户点击确认
├─ frontend/src/api.ts 调用：
│  └─ POST /api/agent/tool-confirmations/{confirmation_id}/confirm
├─ AgentToolConfirmationService.confirm()
├─ 状态 pending -> running
├─ 执行 registered executor：
│  └─ KnowledgeBaseService.confirmed_rebuild_file_index(...)
├─ 按 file_id 重新解析、切片、写入 Chroma
├─ 状态 running -> confirmed / failed
├─ ChatMemoryService.update_tool_confirmation_state(...)
│  └─ 把 confirmation_status / result / error 回写到 kop_chat_message.meta_json
└─ 前端把结果回写到同一条工具调用卡片
```

如果用户点击取消：

```text
POST /api/agent/tool-confirmations/{confirmation_id}/cancel
├─ 状态 pending -> cancelled
└─ 不执行真实工具函数
```

当前确认项是内存队列，适合快速验证核心流程。正式生产版如果要支持后端重启后继续确认、审计、审批历史，建议落到 MySQL 表。

注意这里有两层状态：

```text
1. 待确认队列状态
   └─ AgentToolConfirmationService 当前仍然是内存队列

2. 聊天消息展示状态
   └─ confirm / cancel 后会回写 kop_chat_message.meta_json.model_diagnostics.tool_calls
```

所以当前版本的语义是：

- 后端重启后，尚未处理的 pending 确认项会丢失。
- 但已经点击确认 / 取消的工具调用，会把状态和结果写回聊天消息。
- 页面刷新后，前端重新读取历史消息时，会看到 confirmed / cancelled / failed，而不会重新显示成待确认。

当前另一个确认型工具是 `send_email`：

```text
模型请求 send_email(to=["user@example.com"], subject="...", body="...")
├─ tools.py 发现 requires_confirmation=true
├─ ToolRegistry 返回 status=pending_confirmation
├─ knowledge_base.py 创建邮件确认项
├─ 前端 MessageItem 显示邮件预览
│  ├─ 收件人 / 抄送
│  ├─ 主题
│  └─ 正文
├─ 用户点击确认
├─ AgentToolConfirmationService.confirm()
├─ 执行 registered executor：
│  └─ KnowledgeBaseService.confirmed_send_email(...)
├─ app/services/email_sender.py 通过 SMTP 发送邮件
├─ ChatMemoryService.update_tool_confirmation_state(...) 回写工具调用状态
└─ 前端展示 confirmed / failed 状态和发送结果
```

`send_email` 只有在 `.env` 中设置 `EMAIL_TOOL_ENABLED=true` 并且 SMTP 配置完整时才会注册到 `ToolRegistry`。如果没有配置，模型不会看到这个工具，也就不会产生“假装可以发邮件”的工具调用。

邮件工具还有一个保守兜底：

```text
用户明确说“发邮件 / 发送邮箱”
├─ 原始问题里能提取到邮箱地址
├─ 邮件工具已注册
├─ 模型没有主动调用 send_email
└─ 后端根据模型回答整理 subject/body，并创建 send_email pending_confirmation
```

这个兜底解决的是：有些模型会在自然语言里说“请确认是否发送到 xxx@qq.com”，但没有真正发起 tool_call。前端只有收到 `model_diagnostics.tool_calls` 里的 `send_email` 诊断时才会出现“确认执行”按钮，所以后端会在这种明确场景下补一个真实的确认项。

兜底仍然不会直接发送邮件。它只是创建确认卡片，最终发送仍然必须由用户点击确认触发。

### 补充：当前聊天问答入口新增的会话记忆链路

上面的主流程图主要描述“知识库 RAG 主链路”。

但最近项目又新增了一层“聊天记忆链路”，它包在 RAG 问答链路的前后：

```text
用户在前端发送问题
├─ frontend/src/composables/useChatWorkspace.ts
│  ├─ 当前会话会同时携带 `scope_type` / `scope_id` / `workspace_key`
│  ├─ 如果当前 ChatSession 有 backendConversationId
│  │  └─ 请求里带 conversation_id
│  └─ 如果没有
│     └─ 先不带 conversation_id，让后端创建
├─ app/main.py::CurrentUserContextMiddleware
│  └─ 先解析当前有效用户
│     ├─ 已登录：用 session 对应的 user_id
│     └─ 未登录：回落到游客用户 `local-user`
├─ app/api/routes.py::chat() / chat_stream()
│  ├─ _resolve_chat_memory_context(...)
│  │  ├─ 调用 ChatMemoryService.resolve_conversation(...)
│  │  ├─ 绑定当前有效用户
│  │  ├─ 绑定 `scope_type` / `scope_id` / `workspace_key`
│  │  ├─ 新会话：创建 kop_chat_conversation
│  │  ├─ 老会话：读取已有 kop_chat_conversation
│  │  └─ 调用 ChatMemoryService.resolve_history(...)
│  │     ├─ 优先从 Redis 读最近消息窗口
│  │     ├─ Redis 没有时从 MySQL 读 kop_chat_message
│  │     └─ 都不可用时降级使用前端传来的 history
│  ├─ 把 effective_history 交给 KnowledgeBaseService
│  │  └─ 继续走原来的 RAG 检索 + 生成回答链路
│  ├─ 模型回答完成
│  ├─ _save_chat_memory_turn(...)
│  │  ├─ 写入 user 消息到 kop_chat_message
│  │  ├─ 写入 assistant 消息到 kop_chat_message
│  │  ├─ citations_json / meta_json 保存引用、usage、model_diagnostics 等信息
│  │  ├─ 更新 kop_chat_conversation.last_message_at
│  │  └─ 刷新 Redis 最近消息缓存
│  └─ 返回 conversation_id 给前端
└─ 前端保存 conversation_id
   └─ session.backendConversationId = donePayload.conversation_id
```

所以现在一次聊天请求可以拆成三层：

```text
聊天记忆前置层
├─ 解析 / 创建会话
└─ 回读最近消息窗口

RAG 问答层
├─ 归一化 message_parts
├─ 用历史改写检索问题
├─ 检索 Chroma
├─ 整理上下文
├─ 解析 provider / ModelCapability
├─ 按能力决定图片、工具、Responses API 是否启用
└─ 调用 LLMProviderAdapter 生成回答

聊天记忆后置层
├─ 保存本轮 user / assistant 消息
├─ 保存 message_parts / reasoning_parts / model_diagnostics
└─ 刷新 Redis 最近窗口缓存
```

### 3.1 这条链路里，每一步到底是谁在做什么？

#### 1）文件扫描是谁做的？
- `iter_source_files()` 负责扫描 `settings.user_docs_dir`
- 它只负责“找文件”，不负责读内容，不负责分块

#### 2）文件内容是谁读出来的？
- `load_documents_from_file(path)` 负责把单个文件转成 `list[Document]`
- 它是“格式适配器”
- 它做的核心事情不是展示，而是统一数据结构

#### 3）为什么一定要先转成 `Document` 列表？
因为后面这几个环节都希望拿到同一种输入：

- 切片器希望拿到 `Document`
- Chroma 写入希望拿到 `Document`
- 后续要保留 `metadata`，例如：
  - `source`
  - `file_name`
  - `page`
  - `sheet_name`
  - `slide_name`

所以 `Document` 的意义是：

- 把“原始文件”变成“带来源信息的标准文本块”
- 让不同格式的文件先归一，再进入后面的通用链路

#### 4）切片是谁做的？
- `KnowledgeBaseService.split_documents()` 做的
- 底层工具是 `RecursiveCharacterTextSplitter`

这个切片器的思路不是“按固定字数硬切”，而是：

- 先尽量按大分隔符切
- 例如段落、换行、标点
- 实在不行再向更小粒度退
- 最后才退到字符级别

这样做的目的，是尽量保留语义完整性，同时让 chunk 大小适合检索。

#### 5）chunk_index / char_count 是谁补的？
- 也是 `split_documents()` 补的
- `chunk_index` 方便知道这个 chunk 在本次切片结果里的顺序
- `char_count` 方便调试长度、排查切片效果

#### 6）embedding 是谁真正做的？
- 真正算向量的是 `sentence-transformers`
- 真正暴露给上层的是 `LocalSentenceTransformerEmbeddings`
- 这个类实现的是 LangChain 的 `Embeddings` 接口

你可以这样理解：

- `sentence-transformers` = 真正干活的发动机
- `LocalSentenceTransformerEmbeddings` = 把发动机包装成 LangChain 能用的标准插口
- `Chroma` = 通过这个插口去拿向量

#### 7）为什么说 Chroma 写入时会自动做 embedding？
看 `_build_vector_store()`：

- `Chroma(..., embedding_function=self.embedder)`

这表示：

- 你把“怎么把文本转向量”这件事交给了 `self.embedder`
- 后面调用 `add_documents()` 时，Chroma 会在内部调用这个 embedding_function
- 所以代码里看起来像是“直接塞 Document”，实际上 Chroma 会先把文本转向量，再存到向量库里

这也是为什么你会感觉“没有显式看到先算向量再写库”。
不是没算，是交给 Chroma 的内部流程算了。

#### 8）检索时为什么只传 query 文本？
因为 `retrieve()` 调的是：

- `self.vector_store.similarity_search_with_relevance_scores(query=query, k=limit)`

这里传进去的是原始问题文本，不是提前手工算好的向量。

原因也是同一个：

- Chroma 持有 `embedding_function`
- 它会先把 query 转成向量
- 再和库里的 chunk 向量做相似度比较

所以检索链路的本质是：

- 文档入库时：文本 -> 向量 -> 存库
- 提问时：问题文本 -> 向量 -> 相似度检索

#### 9）DeepSeek 在哪里出现？
DeepSeek 不负责找 chunk。
它只负责：

- 接收检索到的上下文
- 根据上下文生成最终回答

也就是说：

- **检索阶段** = Chroma + embedding 模型
- **生成阶段** = DeepSeek / 其他 LLM

### 3.2 你可以把它记成一句更准的话

- `files.py` 负责把文件变成 `Document`
- `split_documents()` 负责把 `Document` 切成 chunk
- `LocalSentenceTransformerEmbeddings` 负责把文本变成向量
- `Chroma` 负责存向量和做相似度检索
- `chat()` 负责把检索结果交给大模型生成答案

### 3.3 这条链路里最容易混淆的地方

#### `Document` 不是最终展示组件
它只是统一载体，方便后面做切片、入库、检索。

#### `embedding` 不是模型名字
它是“把文本转向量”的动作。

#### `sentence-transformers` 不是业务层概念
它是运行本地 embedding 模型的库。

#### `Chroma` 不只是存储
它既负责存，也负责算相似度检索。

#### `DeepSeek` 不负责向量检索
它只负责最后回答。

## 4. 文件进入知识库时，到底谁在做什么？

这一节专门回答你最关心的那个问题：

- 原始文件到底是谁接住的？
- 为什么要先转成 `list[Document]`？
- 不同格式会产出几个 `Document`？
- 这些 `Document` 上到底带了哪些 metadata？

### 4.1 文件先放在哪里？

当前主要来源是：

1. `data/user_docs`
   - 新文档库的真实文件存储目录
   - 当前真实路径一般是 `data/user_docs/{user_id}/{folder_id}/{stored_name}`
   - 文件由 `DocumentLibraryService` 上传并记录到 `kop_document_file`
   - 文件夹由 `DocumentLibraryService` 记录到 `kop_document_folder`

对应代码：

- `settings.user_docs_dir`
- `iter_source_files()`
- `DocumentLibraryService.save_uploaded_files(...)`
- `DocumentLibraryService.list_documents()`

这里先做的事情只是：

- 上传阶段：先写 MySQL 元数据，再把真实文件写到 `data/user_docs/{user_id}/{folder_id}`
- 建索引阶段：`iter_source_files()` 扫描受控目录，按扩展名过滤支持文件，返回 `Path` 列表
- 每个 `Path` 会再反查 `kop_document_file`，拿到 `user_id`、`file_id`、`folder_id`、`kb_id`、`workspace_key` 等索引 metadata

也就是说，`iter_source_files()` 还没有开始“解析内容”，它只是把候选文件找出来。

真正决定“这个文件属于哪个用户、哪个文件夹、哪个知识库”的，是数据库元数据，而不是目录名本身。

### 4.2 真正把文件读成统一结构的是谁？

是：

- `app/services/files.py`
- `load_documents_from_file(path)`

这个函数是整个知识库预处理链的真正入口。

它接收一个 `Path`，然后做三件核心事情：

1. 判断文件扩展名
2. 按文件类型选择对应解析器
3. 统一输出 `list[Document]`

注意这里的重点：

- 它不是前端预览组件
- 它不是向量库组件
- 它是“文件解析适配器”

也就是把各种乱七八糟的原始格式，先变成后续链路都能消费的标准结构。

### 4.3 为什么一定要先转成 `list[Document]`？

因为后面整个 RAG 管道都希望输入尽量统一。

后面这些环节都直接受益于 `Document` 结构：

- `split_documents()` 要按 `Document.page_content` 去切片
- Chroma 写入时要把 chunk 继续包装成 `Document`
- 检索结果要依赖 `metadata` 去知道来源、页码、sheet、slide
- 重新索引 / 删除旧 chunk 时，要靠 `metadata.source` 精确删除

所以 `Document` 不是一个“多此一举的中间对象”，而是一个统一协议。

你可以把它理解成：

- `page_content` = 真正要切片、向量化、检索的文本内容
- `metadata` = 这段文本从哪里来、属于哪个文件、哪一页、哪个 sheet、哪个 slide

### 4.4 `Document` 在这个项目里长什么样？

当前项目返回的 `Document` 至少会带两大块信息：

1. `page_content`
   - 真正的文本正文
   - 后面切片、embedding、检索都围绕它展开
2. `metadata`
   - 描述这段文本的来源信息

实际代码里最常见的 metadata 字段有：

- `source`
- `file_name`
- `extension`
- `page`
- `sheet_name`
- `slide_name`

第三阶段后，入库到 Chroma 前还会额外合并数据库元数据：

- `user_id`
- `file_id`
- `folder_id`
- `kb_id`
- `workspace_id`
- `workspace_key`
- `original_name`
- `stored_name`
- `display_name`
- `display_path`
- `folder_path`
- `file_path`
- `source_type`

这些字段的意义很大：

- `user_id` 用于用户隔离
- `file_id` 用于文件删除 / 移动 / 重命名后的精确删旧 chunk 和重建
- `folder_id` 用于文件夹范围检索
- `kb_id` 用于知识库范围检索
- `workspace_key` 用于工作区范围检索
- `display_path` / `display_name` 用于前端引用展示

这里有个容易混淆的点要特别记住：

- 真实代码里是 `sheet_name`
- 真实代码里是 `slide_name`
- 不是旧说法里的 `sheet` / `slide`

#### 一个最简单的文本文件例子

```python
Document(
    page_content='这是文档正文...',
    metadata={
        'source': 'data/user_docs/1/root/demo.md',
        'file_name': 'demo.md',
        'extension': '.md',
    },
)
```

#### 一个 PDF 页面例子

```python
Document(
    page_content='这是第 3 页抽出来的文本...',
    metadata={
        'source': 'data/user_docs/1/12/report.pdf',
        'file_name': 'report.pdf',
        'extension': '.pdf',
        'page': 3,
    },
)
```

这些 metadata 很重要，因为后面：

- 检索结果要知道命中的是哪个文件
- 引用要知道是第几页
- 重建单个文件索引时，要按 `source` 删掉旧 chunk

### 4.5 不同文件格式，到底会产出几个 `Document`？

这个问题一定要分开看，因为不同格式的“天然分页单位”不一样。

```text
load_documents_from_file(path)
├─ 纯文本 / 代码 / 配置 / JSON / YAML / SQL / Markdown
│  └─ 一整个文件 -> 1 个 Document
├─ CSV / TSV
│  └─ 先转成 markdown 表格文本 -> 1 个 Document
├─ PDF
│  └─ 每一页 -> 1 个 Document
├─ DOCX
│  └─ 整个文档正文 + 表格 -> 1 个 Document
├─ DOC
│  └─ 尽力抽取全文 -> 1 个 Document
├─ XLSX / XLS / XLSM
│  └─ 每个 sheet -> 1 个 Document
└─ PPTX / PPT
   └─ 每个 slide -> 1 个 Document
```

也就是说：

- 文本类文件通常是“整文件一个 Document”
- PDF 是“每页一个 Document”
- Excel 是“每个 sheet 一个 Document”
- PowerPoint 是“每个 slide 一个 Document”

这个设计的好处是：

- 检索粒度更自然
- 引用页码更容易解释
- 切片前就已经带上了一层“原始结构边界”

### 4.6 每种类型具体调用了什么解析器？

#### A. 文本类文件
适用范围大概包括：

- `.txt`
- `.md`
- `.json`
- `.yaml` / `.yml`
- `.sql`
- `.py` / `.js` / `.ts` 等代码文件
- 以及 `TEXT_FILE_EXTENSIONS` 里声明的其他文本扩展名

调用方式：

- 普通文本：`path.read_text(encoding='utf-8', errors='ignore')`
- `.csv`：`_extract_delimited_text_as_markdown(path, ',')`
- `.tsv`：`_extract_delimited_text_as_markdown(path, '\t')`

输出特点：

- 基本都是 1 个 `Document`
- metadata 只有基础字段：`source / file_name / extension`

#### B. PDF
调用方式：

- `pypdf.PdfReader(str(path))`
- 遍历 `reader.pages`
- 每页 `page.extract_text()`

输出特点：

- 每页生成 1 个 `Document`
- metadata 会额外带 `page`

原理上这是在做：

- 先按 PDF 页边界抽文本
- 再把每一页作为一个更自然的知识单元送去切片

#### C. DOCX
调用方式：

- `_extract_docx_markdown(path)`
- 内部使用 `python-docx`

做的事情包括：

- 读取段落
- 识别标题风格
- 读取表格
- 最后合成为 markdown 风格文本

输出特点：

- 整个文件生成 1 个 `Document`
- 表格内容不会丢，而是并入文本

#### D. DOC
调用方式：

- `_extract_doc_text(path)`

它会优先尝试：

- `antiword`
- `catdoc`

如果这些不可用，再走更弱一些的兜底抽取策略。

输出特点：

- 通常还是 1 个 `Document`
- 但质量可能不如 `.docx`

#### E. Excel：`.xlsx` / `.xls` / `.xlsm`
调用方式：

- `_extract_spreadsheet_pages(path)`

内部做的事情大概是：

1. 先把工作簿读出来
2. 按 sheet 遍历行列
3. 生成两种文本表达：
   - `text_markdown`
   - `text_plain`
4. 知识库入库时优先使用 `text_plain`

输出特点：

- 每个 sheet 对应 1 个 `Document`
- metadata 会带：
  - `page`
  - `sheet_name`

这里的 `page` 你可以理解成“统一页号字段”，不一定真的是 PDF 那种物理页，而是为了后续链路统一引用。

#### F. PowerPoint：`.pptx` / `.ppt`
调用方式：

- `.pptx`：`_extract_presentation_pages(path)` -> `_extract_presentation_pages_from_pptx(path)`
- `.ppt`：先通过 LibreOffice `soffice` 转成 `.pptx`，再走上面的 pptx 解析

内部做的事情包括：

- 遍历每一页 slide
- 抽取文本框内容
- 抽取表格内容
- 合成为 `text_plain` / `text_markdown`

输出特点：

- 每个 slide 对应 1 个 `Document`
- metadata 会带：
  - `page`
  - `slide_name`

### 4.7 为什么 Excel / PPT 也要带 `page`？

这是一个非常工程化的设计，不是说 Excel 真有 PDF 那种页。

它的意义主要有三个：

1. 统一后续检索与引用逻辑
2. 统一前端显示“第几页 / 第几个单元”的感觉
3. 让 `SearchHit.page` 这类结构不必针对 PDF / Excel / PPT 分三套字段

所以你可以理解为：

- PDF 的 `page` 更接近真实页码
- Excel 的 `page` 更接近 sheet 序号
- PPT 的 `page` 更接近 slide 序号

### 4.8 如果文件抽不到文本会怎么样？

`load_documents_from_file(path)` 里有一个很关键的行为：

- 如果抽出来是空文本，就返回空列表 `[]`

这表示：

- 后面不会继续切片
- 不会写入向量库
- 这个文件等于“扫描到了，但没有形成可索引内容”

这也是为什么有时候文件能上传成功，但知识库里看不到对应有效内容，问题并不一定在切片或 embedding，而可能在更前面的文本抽取阶段。

## 5. 切片到底是谁做的？用了什么优化？

### 5.1 谁切片？

是：

- `KnowledgeBaseService.split_documents()`

位置：

- `app/services/knowledge_base.py`

### 5.2 用什么切？

用的是：

- `RecursiveCharacterTextSplitter`

这是 LangChain 提供的文本切片器。

### 5.3 当前切片参数从哪里来？

配置来源：

- `.env`
- `TOP_K`
- `CHUNK_SIZE`
- `CHUNK_OVERLAP`

真正切片用的是：

- `CHUNK_SIZE`
- `CHUNK_OVERLAP`

#### `chunk_size` 是什么意思？
你可以先把它理解成：

- **每个 chunk 期望有多长**

在当前项目里，它本质上控制的是：

- 一个切片块最多大概保留多少字符级内容

注意这里不是“绝对精确切到某个字数”，而是：

- 切片器会尽量参考分隔符
- 先优先按段落、换行、标点去切
- 在尽量不破坏语义边界的前提下，让每块接近 `chunk_size`

所以它更像是：

- “目标块大小”
- 而不是“机械硬切长度”

#### `chunk_overlap` 是什么意思？
它的意思是：

- **相邻两个 chunk 之间要保留多少重复内容**

你可以把它理解成“前后文重叠区”。

举个最直白的例子：

假设：

- `chunk_size = 1000`
- `chunk_overlap = 200`

那大致效果可以理解成：

- 第 1 块：字符 `1 ~ 1000`
- 第 2 块：字符 `801 ~ 1800`

也就是说：

- 第 2 块会把第 1 块结尾附近的一部分内容再带上一遍

#### 为什么要 overlap？
因为很多语义信息刚好可能卡在切片边界上。

如果完全不重叠，可能会出现：

- 上一句在 chunk A 结尾
- 下一句在 chunk B 开头
- 单看其中一个 chunk 都不完整

有了 overlap 之后：

- 相邻 chunk 会共享一小段上下文
- 检索时更不容易把边界处的语义切断

所以你可以把：

- `chunk_size` 理解成“块有多大”
- `chunk_overlap` 理解成“块和块之间重复多少上下文”

### 5.4 当前分隔符策略是什么？

当前项目配置了这些分隔符：

- `\n\n`
- `\n`
- `.` `!` `?` `;`
- 中文句号、感叹号、问号、分号
- 空格
- 最后退到空字符串

这意味着当前策略是：

- 优先按段落切
- 不行再按行切
- 再按句子切
- 还不行再更细地切

这就是 `RecursiveCharacterTextSplitter` 的“递归”含义。

### 5.5 当前切片后的额外元数据

这里最容易误解的一点是：

- metadata 不是只有原始文件阶段的那些字段
- 也不是切片后把原来的 metadata 替换掉了

更准确地说，当前项目是：

- **先继承原始 `Document` 的 metadata**
- **再额外补充 chunk 级 metadata**

#### 原始 `Document` 的 metadata 可能有什么？
例如：

- `source`
- `file_name`
- `extension`
- `page`
- `sheet_name`
- `slide_name`

这些字段主要回答的是：

- 这段文本来自哪个文件
- 来自文件里的哪个位置

#### 切片后额外新增了什么？
当前 `split_documents()` 又给每个 chunk 额外补了两个字段：

- `chunk_index`
- `char_count`

也就是说，一个 chunk 的 metadata 最终更像是：

```text
chunk.metadata
├─ 继承自原始 Document 的来源信息
│  ├─ source
│  ├─ file_name
│  ├─ extension
│  ├─ page
│  ├─ sheet_name
│  └─ slide_name
└─ 切片阶段新增的信息
   ├─ chunk_index
   └─ char_count
```

#### `_upsert_chunks()` 里为什么要把 chunk 重新构造成 `Document`？

这里说的“重新构造”，不是把 chunk 变回别的东西，而是：

- 先把切片后的 chunk 的 `page_content` 和整理后的 `metadata`
- 再重新放进一个新的 LangChain `Document` 对象里

代码里对应的是：

```python
normalized_docs.append(Document(page_content=chunk.page_content, metadata=metadata))
```

这样做的原因是：

1. 入库接口 `add_documents(...)` 期望的是 `Document` 列表
2. 重新创建一次 `Document`，可以把清理过的 metadata 重新装进去
3. 方便后面交给 Chroma 时保持统一的数据结构

所以这里的意思不是“chunk 丢了又塞回去”
而是：

- **把切片后的 chunk 内容 + 规范化后的 metadata，再包装成一个用于入库的 `Document`**

这一步的本质是：

- 为 Chroma 入库准备标准输入格式#### `chunk_index` 是什么意思？
它表示：

- 这个 chunk 在本次切片结果里的顺序编号

你可以把它理解成：

- 第 1 块
- 第 2 块
- 第 3 块
- ...

它主要方便：

- 引用
- 排查切片顺序
- 组织检索结果

#### `chunk_index` 和 chunk ID 是一回事吗？

**不是。**

这两个东西完全不同：

- `chunk_index` = 切片后的顺序号
- `id` = 用 `content + metadata` 算出来的稳定哈希值

也就是说：

- `chunk_index` 是“第几块”
- `id` 是“这一块的唯一标识”

当前代码里：

1. `split_documents()` 先给 chunk 补 `chunk_index`
2. `_upsert_chunks()` 再把 `chunk.page_content + chunk.metadata` 拿去算 hash
3. hash 的结果才是传给 Chroma 的 `ids`

所以你刚才那句可以这样改成更准确的说法：

- **`chunk_index` 不是 hash 算出来的，hash 算出来的是 chunk 的 `id`**

#### `chunk_index` 和 `id` 为什么要分开？
因为它们解决的是不同问题：

- `chunk_index` 负责“当前切片结果里的顺序感”
- `id` 负责“这个 chunk 的稳定唯一标识”

`id` 用 `content + metadata` 做 hash 的好处是：

- 相同内容 + 相同 metadata，会得到相同 id
- 更适合增量写入和调试

#### `char_count` 是什么意思？
它表示：

- 这个 chunk 当前文本内容的字符数

它主要方便：

- 调试切片效果
- 看每个 chunk 实际有多长
- 排查某些 chunk 是否过短或过长

所以你刚才那个理解要稍微修正一下：

- metadata 不只是 `page / slide / source / file_name / sheet`
- 而是“原始来源字段 + chunk 阶段新增字段”共同组成的

作用：

- `chunk_index` 方便引用和去重
- `char_count` 方便后续统计和调试

### 5.6 这里已经有哪些优化？

当前已存在的工程化优化有：

1. 中文和英文标点都考虑了
2. chunk 重叠通过 `CHUNK_OVERLAP` 控制
3. chunk 会保留 metadata
4. chunk 会生成稳定 ID 前先做 metadata 归一化

### 5.7 这里暂时还没有的高级优化

当前项目还没有明显做这些更高级策略：

- 按标题层级切片
- 按 Markdown 结构切片
- 按表格 / 代码块特殊切片
- 按问答场景动态切片
- rerank 重排模型

也就是说当前方案是：

- **稳定、通用、工程够用**
- 但还不是“高级检索增强”那一套

---

## 6. 向量化到底是谁做的？模型怎么加载？

### 6.1 谁做向量化？

是：

- `LocalSentenceTransformerEmbeddings`

位置：

- `app/services/embeddings.py`

### 6.2 谁持有这个 embedder？

是：

- `KnowledgeBaseService.embedder`

位置：

- `app/services/knowledge_base.py`

它是懒加载的：

- 第一次真正要用的时候才初始化
- 初始化后缓存在 `self._embedder`

### 6.3 有没有进程级缓存？

有。

- `get_embedding_model(...)`
- 用了 `@lru_cache(maxsize=1)`

意思是：

- 同一个进程里，不会反复重建 embedding 模型对象
- 这对本地模型很重要，因为模型加载很重

### 6.4 当前模型加载顺序

你刚刚让我补的主备逻辑，现在是：

1. 先尝试本地缓存
2. 再试 `HF_ENDPOINT`
3. 再试 `HF_FALLBACK_ENDPOINT`

这样做的好处是：

- 已下载模型时，不依赖网络
- 网络环境切换时，更稳
- 国内 / 国外部署可以共用一套代码，只调配置顺序

### 6.5 embedding 模型加载失败会影响什么？

会影响：

- 首次建索引
- 手动重建索引
- ONLYOFFICE 保存后的自动增量索引
- 聊天检索

因为这些环节都要用到向量化。

但不会影响：

- 文件是否保存到磁盘
- 普通文本预览
- ONLYOFFICE 单纯打开文档

---

## 7. Chroma 在项目里到底做了什么？

### 7.1 Chroma 是如何初始化的？

位置：

- `KnowledgeBaseService._build_vector_store()`
- `KnowledgeBaseService._build_chroma_client()`

它做了两类事：

1. `langchain_chroma.Chroma`
   - 给上层提供 LangChain 风格操作接口
2. `chromadb.PersistentClient`
   - 用于底层 collection 操作，比如按 source 删除

### 7.2 Chroma 数据存在哪里？

当前配置目录：

- `settings.chroma_dir`
- 即 `data/chroma_db`

所以它是本地持久化向量库，不是纯内存。

### 7.3 它存的不是只有向量

Chroma 存的是一整组信息：

- 向量
- chunk 原文
- metadata
- 文档 ID

所以检索回来时，不只是“相似度分数”，还能拿回：

- 原始 chunk 文本
- 来源文件
- 页码
- chunk 序号

### 7.4 一个 `Document`、chunk、向量、Chroma 记录到底是什么关系？

先给你一句最准确的话：

- **原始解析阶段的 `Document`** 是“待切片的标准文本单元”
- **切片后的 chunk** 是“真正入向量库的最小检索单元”
- **每个 chunk** 会生成 **1 个向量**
- **每个 chunk** 最终对应 **1 条 Chroma 记录**

也就是说，关系通常是：

```text
1 个源文件
├─ 先被解析成 1 个或多个原始 Document
│  ├─ 文本文件：通常 1 个 Document
│  ├─ PDF：通常 1 页 1 个 Document
│  ├─ Excel：通常 1 个 sheet 1 个 Document
│  └─ PPT：通常 1 个 slide 1 个 Document
└─ 每个原始 Document
   ├─ 再被切成 1 个或多个 chunk
   ├─ 每个 chunk 生成 1 个向量
   └─ 每个 chunk 存成 1 条 Chroma 记录
```

所以你刚刚的理解是对的：

- 一个 `Document` **通常可能会变成多个 chunk**
- 一个 chunk **对应一个向量**
- Chroma 里真正存储的粒度，不是“原始 Document”，而是“chunk 记录”

#### 一个最直观的例子

比如一个 PDF：

- 第 3 页先被解析成 1 个原始 `Document`
- 如果这一页文本很长，`split_documents()` 可能把它切成 4 个 chunk
- 那最终会写入 Chroma 的就是 4 条记录
- 这 4 条记录各自都有：
  - chunk 文本
  - chunk metadata
  - chunk 对应向量
  - chunk 的唯一 id

也就是：

```text
PDF 第 3 页原始 Document
├─ chunk A -> vector A -> Chroma record A
├─ chunk B -> vector B -> Chroma record B
├─ chunk C -> vector C -> Chroma record C
└─ chunk D -> vector D -> Chroma record D
```

### 7.5 这个“父子关系”在代码里是怎么保留下来的？

关键不在单独的“父表”，而在 **metadata 继承**。

`RecursiveCharacterTextSplitter.split_documents(documents)` 在切片时，会把原始 `Document` 的 metadata 一起带到 chunk 上。

所以一个 chunk 在进入 `_upsert_chunks()` 时，通常已经带着这些父级信息：

- `source`
- `file_name`
- `extension`
- `page`
- `sheet_name`
- `slide_name`

然后项目又补了两个 chunk 级字段：

- `chunk_index`
- `char_count`

所以你可以把 chunk 的 metadata 理解成：

- 前半部分是“我来自哪个原始文档单元”
- 后半部分是“我在切片结果里是第几个块、长度多少”

#### 重点：当前项目没有单独存 `parent_document_id`

这点非常值得你记住。

当前实现里，并没有显式再存一个字段叫：

- `parent_document_id`
- `page_unit_id`
- `sheet_unit_id`

也就是说，当前“chunk 属于哪个原始 Document”这件事，主要是通过这些继承下来的 metadata 来推断的，而不是通过一张专门的父子关系表。

### 7.6 当前项目是怎么写进 Chroma 的？

对应代码：

- `KnowledgeBaseService._upsert_chunks(chunks)`
- `self.vector_store.add_documents(documents=normalized_docs, ids=ids)`

这一段做的事情可以拆成四步：

1. 拿到切片后的 chunk 列表
2. 对每个 chunk 的 metadata 做归一化
3. 用 `content + metadata` 计算稳定 id
4. 调 `add_documents()` 交给 Chroma

注意这里非常关键的一点：

- 我们的代码没有自己手工先算好一个 `vectors = [...]` 再塞进去
- 而是把 chunk `Document` 交给了 `Chroma`
- 因为初始化时已经给了它 `embedding_function=self.embedder`
- 所以 Chroma 会在内部自动调用 embedder，把每个 chunk 转成向量再入库

也就是说，逻辑上是：

```text
chunk Document
├─ page_content -> 交给 embedding_function 算向量
├─ metadata -> 直接一起存
├─ id -> 用 _hash_chunk(...) 算出
└─ 最终写成一条 Chroma record
```

### 7.7 一条 Chroma record 里，逻辑上有什么？

虽然你在业务代码里主要是通过 `add_documents()` 来写，但从逻辑理解上，一条记录你可以把它想成：

```text
Chroma record
├─ id
├─ document（也就是 chunk 原文）
├─ metadata
└─ embedding（向量）
```

所以“一个 chunk 对应一条记录”这句话，换成更具体一点就是：

- 1 个 chunk 文本
- 1 份 chunk metadata
- 1 个 chunk id
- 1 个 chunk 向量
- 一起组成 1 条 Chroma 记录

### 7.8 那检索回来时，怎么知道它属于哪个原始文件？

就是靠 metadata。

比如检索回来一个 chunk，代码会从 `doc.metadata` 里继续拿这些字段：

- `source`
- `page`
- `chunk_index`

然后组装成 `SearchHit`。

所以检索结果不是“裸向量命中”，而是：

- 命中的 chunk 文本
- 命中的来源信息
- 命中的页码 / 结构位置
- 命中的相关度分数

### 7.9 当前这种关联方式有什么特点？

#### 优点

- 结构简单
- 不需要额外维护父子关系表
- 单文件重建时，可以直接按 `source` 删除整文件对应的 chunk
- 检索时足够返回来源、页码、chunk 序号

#### 局限

- 当前没有单独的 `parent_document_id`
- 所以“一个 chunk 精确属于哪一个原始 Document 单元”主要靠 metadata 组合推断
- `chunk_index` 也不是天然的永久业务主键，它是当前切片结果里的顺序号

这里再细一点说：

- 全量建索引时，`chunk_index` 是对这次 `split_documents()` 产生的全部 chunk 统一编号
- 单文件重建时，`chunk_index` 又只是在这个文件本次切片结果里的顺序号

所以真正稳定的“归属关系”核心还是：

- `source`
- 再加上 `page / sheet_name / slide_name` 这类结构信息

### 7.10 如果后面想让这种关联更强，可以怎么做？

如果后续你想把“原始 Document -> chunk” 的父子关系做得更显式，可以在切片前补一个字段，例如：

- `document_unit_id`
- 或 `parent_unit_id`

比如：

- PDF 的每一页一个 `document_unit_id`
- Excel 的每个 sheet 一个 `document_unit_id`
- PPT 的每个 slide 一个 `document_unit_id`

这样切成多个 chunk 之后，所有 chunk 都显式挂在同一个父级 id 下面。

不过要注意：

- **当前项目还没有这样做**
- 当前项目是“靠 metadata 继承 + chunk 级字段”来完成关联的

### 7.11 你可以最后这样记

```text
原始文件
-> 解析成原始 Document
-> 原始 Document 再切成多个 chunk
-> 每个 chunk 生成 1 个向量
-> 每个 chunk 写成 1 条 Chroma 记录
-> 检索命中的其实也是 chunk 记录，不是原始整文档
```

### 7.12 当前 chunk ID 怎么生成？

位置：

- `_hash_chunk(content, metadata)`

做法：

- 把内容和 metadata 组成 JSON
- `sha1` 哈希
- 作为 chunk ID

好处：

- 相同内容 + 相同 metadata，会得到稳定 ID
- 更适合做增量写入和调试

---

## 8. 建索引的几条业务路径

### 8.1 全量重建索引

对应函数：

- `rebuild_index()`

流程：

1. 扫描所有 source files
2. 每个文件 `load_documents_from_file()`
3. 根据 `source path` 反查 `kop_document_file`，拿到当前文件的索引 metadata
4. 把 `user_id` / `file_id` / `folder_id` / `kb_id` / `workspace_key` 等 metadata 合并到 `Document`
5. 全部文档统一 `split_documents()`
6. `reset_collection()` 清空旧集合
7. `_upsert_chunks(chunks)` 全量写入
8. 写入成功后更新 `kop_document_file.index_status` 和 `last_indexed_at`

触发场景：

- 启动时自动重建（取决于启动逻辑）
- 手动点击重建索引
- 上传后走全量重建的接口
- ONLYOFFICE 保存后如果配置 `full`

### 8.2 单文件增量重建索引

对应函数：

- `reindex_source_file(path)`
- `reindex_document_files(file_ids, source_paths)`

`reindex_source_file(path)` 是旧一些、仍可用的路径型入口：

1. 读取目标文件
2. 反查数据库 metadata
3. 抽取文本
4. 切片
5. 先确保 `vector_store` 能初始化
6. 按 `source` 删除该文件原有 chunk
7. 重新写入新 chunk

这个“先确保 vector_store 能初始化”是我们前面刚补的稳健性修复。

目的就是防止：

- 新索引还没建起来
- 旧索引先被删掉

触发场景：

- ONLYOFFICE 保存后的默认增量更新
- 后续如果扩展成“单文件重建”按钮，也会走这条

`reindex_document_files(file_ids, source_paths)` 是现在文档库 mutation 更推荐的入口：

1. 先按 `file_id` 删除旧 chunk
2. 再按新的 `source_paths` 读取真实文件
3. 重新查询最新数据库 metadata
4. 重新解析、切片、写入 Chroma
5. 更新文件索引状态

触发场景：

- 文件重命名
- 文件移动
- 文件夹重命名
- 文件夹移动
- 文本编辑保存后重建

这就是“移动 / 重命名文件之后，索引 metadata 更新策略”的当前落地方式：

- 不直接在 Chroma 里原地改 metadata
- 而是删除旧 `file_id` 对应 chunks
- 再按最新数据库 metadata 重新写入

### 8.3 删除文件后的重建

对应函数：

- `delete_source_file_and_rebuild(path)`
- `delete_chunks_by_file_ids(file_ids)`

`delete_source_file_and_rebuild(path)` 是路径型旧入口，它会：

1. 删除源文件
2. 必要时删预览 PDF 缓存
3. 再做全量重建

现在文件 / 文件夹删除更常走的是：

```text
DocumentLibraryService 删除 MySQL 记录和真实文件
├─ 文件删除：返回 file_id
└─ 文件夹删除：返回该文件夹及子文件夹下所有 file_ids

KnowledgeBaseService.delete_chunks_by_file_ids(file_ids)
└─ 按 Chroma metadata.file_id 删除对应 chunks
```

这样比全量重建更轻，也更符合现在的 DB 文档库结构。

---

## 9. 检索阶段到底谁在做什么？

### 9.1 简单检索入口

对应函数：

- `retrieve(query, top_k, scope_type, scope_id, workspace_key)`

做法：

- 先构造当前用户过滤条件
- 再按 scope 追加过滤条件
- 再调用 `self.vector_store.similarity_search_with_relevance_scores(...)`
- 把结果整理成 `SearchHit`

真实调用入口是：

```text
retrieve(...)
└─ _similarity_search_for_current_user(...)
   ├─ _current_user_filter(...)
   └─ _similarity_search_with_recovery(...)
      └─ vector_store.similarity_search_with_relevance_scores(...)
```

如果是 `folder` 范围，会先调用：

- `DocumentLibraryService.get_descendant_folder_ids(folder_id)`

也就是说，选中某个父文件夹时，检索会覆盖它自己和所有子文件夹。

### 9.2 检索结果里有什么？

每个 `SearchHit` 主要包括：

- `source`
- `chunk_index`
- `page`
- `score`
- `preview`
- `content`
- `file_id`
- `folder_id`
- `display_name`
- `display_path`
- `folder_path`

### 9.3 更复杂的候选检索逻辑

项目里还有一层：

- `_retrieve_candidates(...)`

它会做这些事：

1. 支持多个 query 变体
2. 汇总不同 query 的命中
3. 按 `(source, page, chunk_index)` 去重
4. 保留分数更高的命中
5. 对 overview / general / comparison / list 问题会尝试扩大候选数量
6. 技术类问题会更宽松地保留代码密集片段

说明当前项目不是只有“最朴素的 top_k 检索”，
而是已经有一点工程化候选聚合思路了。

### 9.4 命中结果不是原样全塞给大模型

后面还会经过：

- `_select_hits_for_answer(...)`
- `_group_hits_for_context(...)`
- `_build_context(...)`

这些函数会做：

- 去重
- 减少重复页
- 区分 code-heavy 与非 code-heavy 片段
- 按问题类型控制上下文长度
- 把命中 chunk 组装成带 citation label 的上下文块

也就是说：

- **检索结果 != 最终送给大模型的上下文**
- 中间还有一层“上下文整理器”

这就是你说的“很多业务化内容没有展示出来”的地方。

---

## 10. 最终回答是谁生成的？DeepSeek 在哪里出现？

这个项目里，DeepSeek 不是用来做 embedding 的。

DeepSeek 负责的是：

- 根据检索回来的上下文
- 结合 prompt
- 生成最终自然语言回答

所以它是在 **RAG 的最后一跳** 才进入。

你可以这样区分：

### 10.1 检索阶段

负责者：

- `files.py`
- `split_documents()`
- `sentence-transformers`
- `Chroma`

### 10.2 生成阶段

负责者：

- DeepSeek / Qwen / OpenAI-compatible provider
- `LLMProviderAdapter`
- `ModelCapability`
- `ToolRegistry`
- `StreamingEvent`

现在生成阶段可以拆成更细的几步：

```text
KnowledgeBaseService.answer() / stream_answer()
├─ resolve_model(model)
├─ _resolve_model_provider(model_name)
├─ _resolve_model_capability(model_name, provider)
├─ _prepare_answer(...)
│  ├─ 归一化 message_parts
│  ├─ 用文本和历史做检索 query
│  ├─ 检索知识库上下文
│  └─ 组织 provider messages
├─ 按 capability 判断是否启用 ToolRegistry
├─ _chat_completion_with_tools(...) 或 _stream_completion_with_tools(...)
│  ├─ 可能先让模型请求工具
│  ├─ 后端执行只读工具
│  └─ 再让模型生成最终回答
├─ LLMProviderAdapter 调用真实 provider
│  ├─ OpenAICompatibleProviderAdapter
│  └─ QwenResponsesProviderAdapter
└─ 返回 answer / citations / usage / model_diagnostics
```

所以现在 DeepSeek / Qwen / OpenAI 仍然是“最终生成回答的模型”，
但它们已经被包在一个更完整的模型能力兼容层里。

### 10.3 这也是为什么当前项目叫“显式检索 + 自定义 Prompt + 模型生成”

因为它不是那种一行 `qa_chain.run()` 黑盒。

而是拆成了：

1. 自己决定怎么检索
2. 自己决定怎么整理上下文
3. 自己决定怎么调用 LLM

优点是：

- 更可控
- 更容易调试
- 更适合工程扩展
- 更容易接多 provider
- 更容易做模型能力降级
- 更容易把 tool calling / 多模态 / Responses API 接进来

当前生成阶段已经不是“只调用一个模型接口”，而是：

```text
显式检索
  -> 自定义上下文
  -> 模型能力判断
  -> provider adapter
  -> tool calling / multimodal / streaming diagnostics
  -> 最终回答
```

### 10.4 最近新增：回答完成后还要保存聊天记录

以前这里讲到“大模型生成最终回答”基本就结束了。

现在要再补一层：

```text
LLM 生成回答
├─ routes.py 收到 answer / citations / usage / model_diagnostics
├─ _save_chat_memory_turn(...)
│  ├─ 把当前用户问题写成一条 user 消息
│  ├─ 把模型回答写成一条 assistant 消息
│  ├─ citations_json 保存引用片段
│  ├─ meta_json 保存 rewritten_question / usage / model_diagnostics 等信息
│  └─ 更新 conversation 的 last_message_at
└─ ChatMemoryService 刷新 Redis 最近消息缓存
```

所以现在“最终回答生成”之后，还有一个会话状态持久化动作。

这个动作不属于 RAG 检索本身，但属于完整聊天产品链路。

---

## 11. 这条链路里有哪些“中间件”和“模型”？

### 11.1 主要模型

1. embedding 模型
   - `BAAI/bge-small-zh-v1.5`
   - 负责向量化

2. 生成模型
   - 当前默认 `deepseek-v4-flash`
   - 负责最终回答
   - 通过 OpenAI-compatible client 调用
   - 可以按 provider 路由到 DeepSeek / Qwen / OpenAI / 其他兼容网关

3. 模型能力映射
   - `app/services/llm_provider_mapping.py`
   - 解析 `ModelCapability`
   - 判断原生联网、工具调用、图片输入、Responses API、Responses 流式、思考参数是否可用
   - 把统一的联网、深度思考、流式、温度、token 上限等参数转换成 provider 能接受的参数
   - 如果 provider 不接受扩展参数，后端会去掉扩展参数重试，并写入 `model_diagnostics.warnings`

4. provider adapter
   - `app/services/llm_provider_adapter.py`
   - `OpenAICompatibleProviderAdapter` 负责 Chat Completions 兼容接口
   - `QwenResponsesProviderAdapter` 负责千问 Responses API
   - `LLMProviderAdapterFactory` 根据 provider 和开关选择具体 adapter

5. 流式事件和工具层
   - `app/services/llm_streaming.py`
   - `app/services/tools.py`
   - `StreamingEvent` 把正文、思考、工具、usage、diagnostics 分开
   - `ToolRegistry` 负责只读工具注册和执行

### 11.2 主要框架 / 中间件

1. FastAPI
   - 后端 API 框架

2. LangChain
   - 提供 `Embeddings` 接口、`Document`、`RecursiveCharacterTextSplitter`、Chroma 封装接入点

3. Chroma
   - 向量库存储和相似度检索

4. sentence-transformers
   - 真正执行 embedding 推理

5. ONLYOFFICE
   - Office 文件浏览器查看 / 编辑
   - 不是知识库检索核心中间件

6. LibreOffice
   - 老 Office 格式兼容和转换辅助
   - 不是知识库向量检索核心中间件

7. MySQL
   - 保存聊天用户、会话、消息、摘要和长期记忆
   - 当前已经实际使用 `kop_user`、`kop_chat_conversation`、`kop_chat_message`

8. Redis
   - 缓存最近聊天窗口
   - 当前用于减少每次聊天都从 MySQL 回读最近消息的成本

9. 前端 Vue 组件层
   - `App.vue`：应用总壳、登录入口、主题、侧边栏、viewer / ONLYOFFICE 弹窗控制
   - `AuthScreen.vue`：登录 / 注册界面
   - `LeftSidebar.vue`：工作区导航、最近会话列表、范围标签、用户菜单
   - `ChatWorkspace.vue`：聊天主界面
   - `ChatComposer.vue`：模型、深度思考、联网、会话范围选择、发送入口
   - `MessageList.vue` / `MessageItem.vue`：消息列表、引用、usage、cost、模型诊断展示
   - `ModelHealthPanel.vue`：模型健康检查弹窗内容
   - `DocumentsWorkspace.vue`：文档库文件系统式界面、文件夹树、文件 / 文件夹操作、ONLYOFFICE 健康弹窗
   - `IndexWorkspace.vue`：索引概览和重建入口
   - `SearchWorkspace.vue`：检索实验场
   - `UnifiedFileViewer.vue`：普通文件 / PDF / Markdown / 表格预览
   - `OnlyOfficeEditor.vue`：ONLYOFFICE 在线编辑器

---

## 12. 当前项目已经有的优化与暂时还没有的优化

### 12.1 已经有的

- 本地 embedding 缓存优先
- HF 主备地址兜底
- chunk overlap
- 中文 + 英文分隔符
- 按 source 增量删除与重建
- 保存后增量索引
- 检索结果去重
- 上下文分组与引用标签生成
- 简单 code-heavy 片段识别
- 多 query 候选召回和按问题类型扩展候选
- file_id 优先的文档 mutation
- `file_id` 级删除旧 chunk
- 文件移动 / 重命名后的重新索引
- 文件夹移动 / 重命名后的子文件批量重新索引
- 文档库文件夹树和文件系统式列表
- 会话作用域 `scope_type` / `scope_id` / `workspace_key`
- 会话列表分页回显
- 消息列表分页回显
- `conversation_id` 前后端对齐
- 默认游客用户 `local-user`
- 登录 / 注册 / 退出
- Redis session cookie：`kop_session`
- `model_diagnostics` 随回答返回
- 模型健康检查弹窗
- `LLMProviderAdapter` 把 provider 调用从 RAG 主流程拆出来
- `OpenAICompatibleProviderAdapter` 支持通用 Chat Completions 兼容 provider
- `QwenResponsesProviderAdapter` 支持千问 Responses API 基础调用和基础流式
- `StreamingEvent` 统一正文、思考、工具调用、usage、diagnostics、done 事件
- `ToolRegistry` 接入只读工具调用闭环
- 非流式 `/api/chat` 和流式 `/api/chat/stream` 都支持基础 tool calling
- `ChatMessagePart` 支持 `text` / `image_url` / `file_ref`
- 聊天输入支持图片 URL 和直接粘贴图片
- `ModelCapability` 支持按模型能力自动判断图片、工具、Responses API 等能力
- 模型不支持图片 / 工具 / Responses API 时可以自动降级并写入 warning
- 助手消息可以展示 reasoning、tool calls、provider_api、warnings
- ONLYOFFICE 健康检查弹窗
- 检索时按当前用户过滤
- 检索时按 scope 限定范围
- folder scope 会自动包含子文件夹
- 文档引用里带 `file_id` / `folder_id` / `display_path`，方便前端打开对应文件

### 12.2 暂时还没有明显看到的

- rerank 重排模型
- hybrid search（关键词 + 向量混检）
- BM25 融合召回
- 更细的 metadata filter 检索策略增强
- 多向量索引
- 标题树 / 章节树切片
- 查询改写模型
- 结果摘要缓存
- 自动会话摘要生成
- 长期记忆事实抽取
- 更完整的权限模型 / 多租户隔离
- 会话重命名 / 删除 / 归档接口
- 细粒度角色权限，例如管理员、团队空间、共享知识库
- 文件版本历史 / 回滚
- 知识库对象的完整前端管理页，目前更多是文档库与 scope 选择先落地
- 图片上传到后端 / 对象存储并生成公网 URL，目前粘贴图片先走 data URL
- 更完整的多模态输入，例如音频、视频、provider 原生 file input
- Responses API 原生复杂事件完整解析，例如结构化引用、web_extractor、code_interpreter
- 高风险写入类工具，例如编辑文件、删除文件、写数据库；这些需要权限、审计和人工确认
- 模型能力配置中心，目前主要靠 `.env` 和 `MODEL_CAPABILITIES_JSON`

所以当前项目已经不是“最原始 demo”，
但也还没走到“高级检索架构”的阶段。

---

## 13. 失败点和排查思路

### 13.1 文件抽取失败

影响：

- 文件无法正常入索引

排查：

- `files.py` 是否支持该扩展名
- `.ppt` 是否安装 LibreOffice
- 文件内容是否为空

### 13.2 embedding 模型加载失败

影响：

- 建索引失败
- 检索失败

排查：

- 本地缓存是否存在
- `HF_ENDPOINT` 是否可达
- `HF_FALLBACK_ENDPOINT` 是否可达
- Python 依赖是否完整

### 13.3 Chroma 写入 / 删除失败

影响：

- 索引不一致
- 增量更新不生效

排查：

- `data/chroma_db` 是否正常
- collection 是否可访问
- metadata 是否异常

### 13.4 生成模型失败

影响：

- 检索成功但回答失败

排查：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- 供应商路由配置

### 13.5 MySQL / Redis 聊天记忆失败

影响：

- 聊天记录无法落库
- 后端无法从数据库回读最近消息窗口
- Redis 缓存失效时会退回 MySQL

当前代码的兜底策略是：

- MySQL / Redis 不可用时，聊天接口不会直接崩掉
- `routes.py::_resolve_chat_memory_context(...)` 会降级使用前端传来的 `history`
- `_save_chat_memory_turn(...)` 保存失败时只记录 warning，不影响本次回答返回

排查：

- `.env` 里的 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_PASSWORD`
- `.env` 里的 `REDIS_HOST` / `REDIS_PORT`
- Docker 中间件是否启动
- `requirements.txt` 里的 `SQLAlchemy` / `PyMySQL` / `redis` 是否安装到 `.venv311`
- `KOP` 数据库是否已经执行当前版本的初始化 SQL，例如 `sql/KOP_v1_init.sql`

### 13.6 登录态 / 游客用户失败

影响：

- `/api/auth/me` 异常
- 文档列表、聊天会话、索引统计无法按用户隔离
- 未登录游客模式无法自动创建 `local-user`

排查：

- `app/services/auth.py::UserAuthService`
- `app/main.py::CurrentUserContextMiddleware`
- `kop_user` 是否有默认用户，或是否允许自动创建
- Redis 是否能保存 `kop_session`
- 浏览器请求是否携带 cookie

### 13.7 文档库 metadata 与 Chroma metadata 不一致

影响：

- 文件移动 / 重命名后引用路径不对
- 文件夹范围检索不完整
- 删除文件后旧 chunk 还被召回

排查：

- `kop_document_file.file_path` / `folder_id` 是否正确
- `DocumentLibraryService.get_index_metadata_by_storage_path(...)` 是否能查到 metadata
- `KnowledgeBaseService.reindex_document_files(...)` 是否被触发
- 删除时是否调用 `delete_chunks_by_file_ids(file_ids)`
- Chroma metadata 里是否有 `user_id` / `file_id` / `folder_id` / `kb_id` / `workspace_key`

### 13.8 模型诊断显示扩展参数失败

影响：

- 原生联网可能没有生效
- 深度思考参数可能没有生效
- 但不会自动换成另一个 provider / model

排查：

- `MessageItem.vue` 里的 `modelDiagnostics`
- 后端返回的 `option_fallback_used`
- `model_diagnostics.warnings`
- `app/services/llm_provider_mapping.py`
- `.env` 中模型 base_url、API key、模型名是否匹配 provider 要求

### 13.9 图片输入没有生效

影响：

- 用户粘贴图片或添加图片 URL 后，模型仍然像没看到图片
- 或者 `model_diagnostics.warnings` 提示图片已降级成文本引用

排查：

- 当前模型的 `supports_multimodal_input` 是否为 true
- 模型健康检查弹窗里“图片输入”标签是否为“是”
- 当前模型是否属于视觉模型，例如 `qwen3.7-plus`、`qwen-vl-plus`、`gpt-4o-mini`
- 如果是 `qwen-max` 这类文本模型，系统默认不会把它当成视觉模型
- `.env` 里的 `MODEL_CAPABILITIES_JSON` 是否需要覆盖
- 粘贴图片是否超过前端 2MB 限制
- provider 是否支持 `data:image/...;base64,...`；如果不支持，需要后续改成图片上传后生成公网 URL

### 13.10 工具调用没有触发

影响：

- 模型没有调用知识库搜索 / 网页搜索工具
- 助手消息下方没有 tool calls 折叠区

排查：

- 当前模型的 `supports_tool_calling` 是否为 true
- 模型健康检查弹窗里“工具调用”标签是否为“是”
- `model_diagnostics.tool_calls` 是否为空
- `model_diagnostics.warnings` 是否提示模型不支持工具调用
- 当前是否启用了千问 Responses API 原生联网；这种情况下会优先让 Responses API 的 `web_search` 接管，不再同时塞本地 `ToolRegistry`
- `app/services/tools.py` 里的工具是否注册成功

### 13.11 千问 Responses API 没有走

影响：

- 明明选择了千问模型和原生联网，但 `provider_api` 仍然是 `chat_completions`

排查：

- `.env` 是否设置 `QWEN_RESPONSES_API_ENABLED=true`
- 当前模型的 `supports_responses_api` 是否为 true
- 流式请求还要看 `supports_responses_streaming`
- 前端是否打开“模型原生联网”
- `model_diagnostics.provider_api` 是否是 `qwen_responses` / `qwen_responses_stream`
- `model_diagnostics.warnings` 是否提示 Responses API 回退到 Chat Completions
- 当前 Qwen `base_url` 是否支持 Responses API

### 13.12 流式思考 / 工具事件没有展示

影响：

- 后端实际可能返回了 reasoning 或 tool call，但前端看不到折叠区
- 或者 UI 显示“思考：deep”，但没有“思考片段”折叠区

排查：

- 先区分两个概念：`thinking=deep` 表示用户选择了深度模式；“思考片段”只有 provider 返回 reasoning 内容时才会展示
- 当前模型是否声明支持原生思考参数：`supports_thinking_budget` 或 `supports_reasoning_effort`
- `qwen-max` 当前按通用文本模型处理，可以 deep 回答，但不承诺有可展示 reasoning；`qwen3.7-plus` 这类 `qwen3*` 模型才按千问 thinking 模型处理
- 后端是否发出 `reasoning_delta` / `tool_call_delta`
- `app/services/llm_streaming.py` 的事件类型是否正确
- `routes.py::_streaming_event_payload(...)` 是否正确把内部事件转成 SSE payload
- `frontend/src/api.ts::chatStream(...)` 是否接住对应事件
- `frontend/src/composables/useChatWorkspace.ts` 是否把事件写入当前 `UiMessage`
- `MessageItem.vue` 是否展示 reasoning / tool calls 折叠区
- 如果 `model_diagnostics.warnings` 提示“当前模型未声明支持原生深度思考参数”，说明后端没有强行传 provider thinking 参数

---

### 13.13 最近一轮模型能力 Bug 修复记录

这轮修了几类容易混淆的问题：

1. 思考片段一字一行
   - 原因：流式 `reasoning_delta` 每个小片段都被前端渲染成单独段落
   - 修复：`MessageItem.vue` 合并 `reasoningParts` 成 `assistantReasoningText` 展示，并加换行/溢出保护

2. `qwen-max` 没有思考片段
   - 原因：原来把整个 `qwen` provider 都当成支持 thinking budget
   - 修复：`llm_provider_mapping.py` 改为只对 `qwen3*`、`qwq*`、`qvq*` 开启千问 thinking 参数
   - 结论：`qwen-max` 可以 deep 回答，但不承诺返回可展开的原生思考片段

3. `qwen-max` 图片输入为“否”
   - 原因：图片能力是模型级能力，不是 provider 级能力；官方图像示例使用的是 `qwen3.7-plus`
   - 修复：`.env` / `.env.example` 增加 `qwen3.7-plus`，并由 `ModelCapability` 自动识别图片能力

4. 粘贴图片显示超长 base64
   - 原因：用户消息回显直接展示了 `data:image/...`
   - 修复：`MessageItem.vue` 对 data URL 显示“粘贴图片”

5. 千问天气问题没有联网结果
   - 原因：请求诊断里 `nativeWeb=off, externalWeb=off` 时表示实际没联网；并且原来没有外部搜索配置时也注册了 `search_web` 假工具
   - 修复：支持原生联网的模型默认开启 native web；`ToolRegistry` 只有外部搜索可用时才注册 `search_web`；千问 Chat Completions 原生联网会带 `enable_search` 和 `forced_search`

6. 流式回答正文结束后仍卡在模型诊断区
   - 原因：`stream_answer()` 在 provider 流式正文结束后，又同步调用 `_polish_answer(...)` 做二次润色；这次调用不会继续吐字，前端只能等待最终 `done`
   - 为什么深度思考更明显：`thinking=deep` 时 `_should_polish_answer(...)` 更容易触发，所以尾部等待时间更长
   - 修复：流式 `/api/chat/stream` 不再做结束后的二次润色；provider stream 结束后直接发送 `done`，非流式 `/api/chat` 的润色逻辑保留

涉及文件：

- `frontend/src/components/chat/MessageItem.vue`
- `frontend/src/composables/useChatWorkspace.ts`
- `app/services/knowledge_base.py`
- `app/services/llm_provider_mapping.py`
- `app/services/tools.py`
- `.env`
- `.env.example`
- `业务逻辑解析/模型能力思考.md`

## 14. 一句话记忆版

你可以把这套项目的 RAG 链路记成下面这几句话：

1. `CurrentUserContextMiddleware` 先解析当前用户；未登录时回落到游客用户 `local-user`
2. `DocumentLibraryService` 管文件夹、文件、`file_id`、`folder_id` 和真实存储路径
3. 文件内容由 `files.py` 抽取成统一 `Document`
4. `KnowledgeBaseService` 给 `Document` 合并数据库 metadata
5. `knowledge_base.py` 用 `RecursiveCharacterTextSplitter` 切 chunk
6. `embeddings.py` 用本地 sentence-transformers 模型做向量化
7. Chroma 存 chunk、向量和 metadata
8. 用户提问时，也先转成向量
9. Chroma 按当前用户和 scope 过滤后，再按向量相似度找最相关 chunk
10. `knowledge_base.py` 再把命中结果整理成上下文和引用
11. `message_parts` 让用户消息可以携带文本、图片、文件引用
12. `ModelCapability` 判断当前模型是否支持图片、工具、Responses API、思考参数
13. `ToolRegistry` 在模型需要时执行只读工具调用
14. `LLMProviderAdapter` 负责真正调用 DeepSeek / Qwen / OpenAI-compatible provider
15. `StreamingEvent` 把正文、思考、工具调用、usage、diagnostics 分开返回
16. `model_diagnostics` 告诉前端这次实际 provider、model、联网、思考、工具、图片和 fallback 是否生效

如果把最近新增的聊天记忆也一起放进去，可以继续记成：

17. `ChatMemoryService` 先按当前用户和 `conversation_id` 回读最近会话窗口
18. `routes.py` 把最近窗口和当前 scope 交给 `KnowledgeBaseService`
19. 回答结束后，把本轮 user / assistant 消息、引用、usage、模型诊断、message_parts 写回 MySQL，并刷新 Redis 缓存

---

## 15. 你后面继续深挖时，建议按这个顺序看源码

### 第一层：先看总入口

- `app/services/knowledge_base.py`
- `app/api/routes.py`
- `app/main.py::CurrentUserContextMiddleware`

### 第二层：看三个核心函数

- `load_documents_from_file()`
- `split_documents()`
- `retrieve()` / `_retrieve_candidates()` / `_similarity_search_for_current_user()`

### 第三层：看两个外部依赖接入点

- `app/services/embeddings.py`
- `Chroma(...)` 初始化
- `app/services/llm_provider_adapter.py`
- `app/services/llm_provider_mapping.py`
- `app/services/llm_streaming.py`
- `app/services/tools.py`

### 第四层：再看文档库和用户怎么接入这些链路

- `app/services/document_library.py`
- `app/services/auth.py`
- `app/core/request_context.py`

### 第五层：再看聊天记忆怎么接入

- `app/services/chat_memory.py`
- `app/core/database.py`
- `app/core/redis_client.py`
- `frontend/src/composables/useChatWorkspace.ts`

### 第六层：最后看前端怎么把这些能力展示出来

- `frontend/src/App.vue`
- `frontend/src/components/chat/ChatComposer.vue`
- `frontend/src/components/chat/MessageItem.vue`
- `frontend/src/components/chat/ModelHealthPanel.vue`
- `frontend/src/components/sidebar/LeftSidebar.vue`
- `frontend/src/components/workspaces/DocumentsWorkspace.vue`
- `frontend/src/components/workspaces/SearchWorkspace.vue`

---

## 16. 当前项目最准确的定位

如果你要给这套项目下一个很准确的定义，我建议你记成：

**这是一个“用户隔离文档库 + 本地文件解析 + LangChain 切片接口 + sentence-transformers 向量化 + Chroma 向量检索 + OpenAI-compatible LLM 生成回答”的工程化 RAG 项目。**

如果按现在已经补上的模型能力层再说得更完整一点，可以记成：

**这是一个“用户隔离文档库 + 会话范围检索 + 本地向量索引 + OpenAI-compatible 多 provider 生成 + 模型能力自动匹配 + 基础工具调用 + 基础多模态输入”的知识编排平台。**

它不是：

- 纯 LangChain 黑盒 QA Chain
- 纯关键词搜索项目
- ONLYOFFICE 项目
- LibreOffice 项目

ONLYOFFICE 和 LibreOffice 都只是“文档生态配套能力”，
而真正的 RAG 主链路核心还是：

- 文件抽取
- 切片
- 向量化
- 向量检索
- 大模型生成

如果从完整聊天产品链路看，现在还额外包括：

- 登录 / 注册 / 游客用户回落
- 文档库文件夹化和 `file_id` 优先操作
- 会话范围选择：全部 / 文件夹 / 知识库 / 工作区
- MySQL 聊天记录持久化
- Redis 最近消息窗口缓存
- 前后端 `conversation_id` 会话续接
- 模型调用诊断和健康检查弹窗
- `LLMProviderAdapter` provider 适配层
- `StreamingEvent` 流式事件分层
- `ToolRegistry` 只读工具调用闭环
- `ChatMessagePart` 多模态消息片段
- 图片 URL / 直接粘贴图片输入
- `ModelCapability` 模型能力自动匹配与降级
- 千问 Responses API 基础 adapter

---

## 17. 上下文长度、聊天记录存储、用户关联，怎么设计更合理？

这个问题非常重要，因为它直接决定后面项目能不能“越聊越像个产品”，而不是只会一次性问答。

### 17.1 先说上下文长度：为什么它总是不够？

LLM 的上下文长度有限，意思是：

- 你不能把无限长的历史消息都塞进去
- 也不能把整个知识库全文都塞进去
- 更不能一直把所有轮次聊天原封不动发给模型

所以在工程上，必须做“上下文预算分配”。

这个预算通常要分给三部分：

1. 用户当前问题
2. 对话历史里真正有用的几轮
3. 检索回来的知识库证据

如果这三块都无限堆，最后就会出现：

- 模型输入超长
- 费用上涨
- 检索噪声变大
- 关键问题反而被淹没

### 17.2 当前项目里已经做了什么？

当前项目已经有一部分“短期上下文压缩”思路了：

- `_compose_search_query(question, history)` 只取最近几轮历史去改写检索问题
- `_prepare_answer(...)` 里会把历史消息拼进提示词，但不是无限拼
- `_build_context(...)` 会对检索命中的 chunk 再做分组、裁剪和引用整理
- `ChatMemoryService.resolve_conversation(...)` 会把会话和当前有效用户、`scope_type` / `scope_id` / `workspace_key` 一起对齐
- `ChatMemoryService.resolve_history(...)` 会优先读取后端最近会话窗口
- `routes.py` 会在真正回答前先处理 `conversation_id`
- `routes.py` 还会把 `model_diagnostics` 一并回传前端和落库
- 回答完成后，后端会把 user / assistant 两条消息写入 MySQL
- Redis 会缓存最近消息窗口，减少重复读库
- 前端刷新会先回读会话列表和消息列表，确保聊天能回显

也就是说，项目不是“全量历史直塞”，而是已经开始做：

- 取最近的、相关的、能帮助回答的内容

### 17.3 想尽可能提升上下文“记忆感”，通常怎么做？

这里要先分清两种“记忆”：

#### A. 短期记忆
指的是：

- 最近几轮对话还能被模型看见

做法一般是：

- 只保留最近 N 轮
- 或者只保留最近几轮的 user/assistant 消息
- 再配合一段“会话摘要”

#### B. 长期记忆
指的是：

- 历史上很久之前的内容也能被再次找回来

做法一般是：

- 把对话记录落库
- 再做摘要表 / 主题索引 / 向量索引
- 需要时按用户、会话、主题检索回来

### 17.4 对当前项目来说，最实用的上下文策略是什么？

我建议你把上下文分成三层：

#### 第一层：当前轮问题
- 一定保留
- 这是最核心的输入

#### 第二层：最近几轮对话
- 保留最近 3 ~ 8 轮，具体看长度
- 如果历史很长，先做摘要，再放进 prompt

#### 第三层：知识库证据
- 只放检索命中的少量高质量 chunk
- 不要把所有命中文本都原封不动塞进去

这样做的好处是：

- 模型不会被长历史压垮
- 关键上下文不会被淹没
- 成本可控
- 回答也更稳定

### 17.5 聊天记录要怎么存，后面才好和用户关联？

这个问题现在已经不只是“建议”了，第三阶段已经把核心表落地了。

现在可以分成两层看：

1. 已经实际使用的主链路表
2. 后续为摘要和长期记忆预留的扩展表

当前项目已经实际落地的表名是：

- `kop_user`
- `kop_chat_conversation`
- `kop_chat_message`

这里要特别注意一下：

- `kop_user` 现在既承担正式注册用户，也承担默认游客用户 `local-user`
- `kop_chat_conversation` 现在已经把 `scope_type` / `scope_id` / `workspace_key` 作为会话范围字段落下来了
- 会话列表接口会补一个 `scope_name`，前端就能直接显示“全部 / 文件夹 / 知识库 / 工作区”
- `kop_chat_message` 会把原始消息、引用和诊断信息都保留下来，方便回显和排查

当前项目已经预留、但还没有正式接入完整摘要 / 长期记忆业务逻辑的是：

- `kop_chat_conversation_summary`
- `kop_chat_memory_fact`

对应建表脚本是：

- `sql/KOP_v1_init.sql`

#### 表 1：`kop_chat_conversation`
保存“会话本身”。

适合放：

- 会话 id
- 用户 id
- 会话标题
- `workspace_key`
- `scope_type`
- `scope_id`
- 创建时间
- 最后更新时间
- 最后消息时间
- 是否归档 / 是否删除

它解决的问题是：

- 这一串消息属于哪个会话
- 这个会话属于哪个用户
- 这个会话现在属于哪个范围

#### 表 2：`kop_chat_message`
保存“每一条消息”。

适合放：

- 消息 id
- 会话 id
- 用户 id
- 角色（user / assistant / system）
- 消息内容
- 消息顺序
- `meta_json`
- `citations_json`
- token 数
- 创建时间

它解决的问题是：

- 一段会话里每一轮具体说了什么
- 方便回放、导出、追踪上下文

#### 表 3：`kop_chat_conversation_summary` 或 `kop_chat_memory_fact`
保存“摘要记忆”。

适合放：

- 会话 id
- 摘要内容
- 摘要版本
- 最近总结时间
- 是否最新

它解决的问题是：

- 长会话不可能把所有历史都塞进 prompt
- 但又希望保留前文脉络

所以摘要是很有用的中间层。

### 17.6 当前 MySQL 结构和通用设计名的关系

这段现在可以理解成“通用设计名”和“当前实际表名”的对应关系。

当前项目实际落地时，把表名前缀统一成了 `kop_`：

```text
通用设计名                  当前项目实际表名
sys_user                  -> kop_user
chat_conversation         -> kop_chat_conversation
chat_message              -> kop_chat_message
chat_conversation_summary -> kop_chat_conversation_summary
chat_memory_fact          -> kop_chat_memory_fact
```

#### `sys_user`
对应当前项目的 `kop_user`。

这张表现在已经接入登录 / 注册 / 游客用户。

字段大致包括：

- `id`
- `username`
- `password_hash`
- `nickname`
- `status`
- `created_at`
- `updated_at`

#### `chat_conversation`

对应当前项目的 `kop_chat_conversation`。

当前字段大致包括：

- `id`
- `user_id`
- `title`
- `workspace_key`
- `model_name`
- `scope_type`
- `scope_id`
- `summary`
- `summary_updated_at`
- `status`
- `created_at`
- `updated_at`
- `last_message_at`

#### `chat_message`

对应当前项目的 `kop_chat_message`。

当前字段大致包括：

- `id`
- `conversation_id`
- `sender_user_id`
- `role`
- `content`
- `seq_no`
- `model`
- `token_prompt`
- `token_completion`
- `token_total`
- `citations_json`
- `meta_json`
- `created_at`

#### `chat_conversation_summary`

对应当前项目的 `kop_chat_conversation_summary`，目前属于后续摘要能力预留。

字段大致包括：

- `id`
- `conversation_id`
- `summary_text`
- `summary_version`
- `last_summary_at`
- `created_at`
- `updated_at`

### 17.7 为什么 `user_id` 和 `conversation_id` 现在是核心字段？

因为当前项目已经开始围绕它们组织业务：

- 按用户查历史
- 按会话继续问
- 按用户做权限隔离
- 按用户统计使用量
- 按会话做导出 / 删除 / 归档

现在 `user_id` 已经同时进入：

- `kop_user`
- `kop_document_folder`
- `kop_document_file`
- `kop_chat_conversation`
- Chroma metadata

`conversation_id` 已经同时进入：

- `/api/chat` / `/api/chat/stream` 请求响应
- `kop_chat_conversation`
- `kop_chat_message`
- 前端 `ChatSession.backendConversationId`

所以这两个字段已经不是“以后可能需要”，而是当前用户隔离、会话续接、刷新回显的基本骨架。

### 17.8 向量库要不要也存聊天记录？

一般建议分开看：

- **聊天原文**：放 MySQL 这种关系库
- **聊天摘要 / 长期记忆**：可以考虑再做一份向量索引
- **知识库内容**：继续放现在的 Chroma

也就是说：

- MySQL 更适合做“真相记录”
- 向量库更适合做“语义记忆检索”

### 17.9 对当前项目最推荐的落地顺序

如果你现在还在开发期，我建议这样来：

1. 先把 `chat_conversation` 和 `chat_message` 跑通
2. 再加 Redis 最近消息缓存
3. 再做 `chat_conversation_summary`
4. 最后再考虑把“长期记忆”单独向量化

当前项目已经完成并扩展了前两步：

- `kop_chat_conversation`
- `kop_chat_message`
- Redis 最近消息窗口缓存
- 前后端 `conversation_id` 对齐
- `.env` / `.env.example` 已加入 MySQL、Redis、聊天窗口配置
- 登录 / 注册 / 游客用户回落
- 会话范围字段：`scope_type` / `scope_id` / `workspace_key`
- 会话列表和消息列表分页回显
- 回答消息保存引用、usage、模型诊断

这样比较稳，不会一开始就把架构做得太重。

### 17.10 结合你现在的 Docker 中间件环境，最适合的后续方向

你已经把中间件集中到 `C:\Users\30372\Desktop\docker-middleware` 这一类公共目录了，那后面数据库设计上也建议保持这种思路：

- MySQL 负责结构化存储
- Redis 负责短期缓存 / 会话状态 / 限流
- Chroma 负责知识库向量检索
- 对话历史先进 MySQL
- 热门会话状态再进 Redis

这样后面迁移到云服务器时，边界会很清楚。

### 17.11 最后给你一句最好记的话

- **上下文长度靠“分层 + 截断 + 摘要 + 检索”来控制，不是靠把所有历史都塞进 prompt**
- **聊天记录已经落 MySQL，`user_id` / `conversation_id` 是当前会话体系的骨架**
- **长期记忆如果后面要做，再考虑摘要表和向量化检索**
- **当前项目已经把第一阶段落地成：MySQL 存原始消息，Redis 缓存最近窗口，前端用 `conversation_id` 续接会话**

### 17.12 现在已经补上的会话回显链路

当前项目已经不只是“发送时保存 `conversation_id`”，还补上了刷新后的回读链路。

相关代码位置：

```text
后端
├─ app/services/chat_memory.py
│  ├─ list_conversations()
│  └─ list_messages()
├─ app/api/routes.py
│  ├─ GET /api/chat/conversations
│  └─ GET /api/chat/conversations/{conversation_id}/messages
└─ app/schemas.py
   ├─ ChatConversationSummary
   ├─ ChatConversationListResponse
   ├─ ChatMessageRecord
   └─ ChatMessagePageResponse

前端
├─ frontend/src/api.ts
│  ├─ listChatConversations()
│  └─ listChatMessages()
├─ frontend/src/composables/useChatWorkspace.ts
│  ├─ initialize()
│  ├─ loadConversations()
│  ├─ loadSessionMessages()
│  └─ loadOlderMessages()
├─ frontend/src/components/sidebar/LeftSidebar.vue
│  └─ 最近会话列表滚到底部加载下一页会话，并展示范围标签
└─ frontend/src/components/chat/MessageList.vue
   └─ 消息列表滚到顶部加载更早消息
```

刷新页面时的流程是：

```text
页面初始化
├─ 前端调用 GET /api/chat/conversations
├─ 后端按当前有效用户查询 kop_chat_conversation
├─ 当前未登录时会回落到游客用户 local-user
├─ 前端把数据库会话映射成 ChatSession
├─ 默认选中最近一条会话
├─ 前端调用 GET /api/chat/conversations/{id}/messages
├─ 后端查询 kop_chat_message
├─ 前端把数据库消息映射成 UiMessage
└─ 聊天窗口完成回显
```

这里要特别区分两种“读取历史”：

1. 聊天界面回显历史
   - 查 MySQL
   - 走 `list_messages()`
   - 用于把聊天窗口显示出来
2. 下一轮问答拿最近上下文
   - 优先读 Redis 最近窗口
   - Redis 没有时再查 MySQL
   - 走 `resolve_history()`
   - 用于给 RAG 问答链路拼最近对话上下文

所以：

- **MySQL 是完整聊天历史主库**
- **Redis 是最近 12 条左右的热缓存**
- **前端刷新回显主要依赖 MySQL**
- **模型回答时的最近上下文优先用 Redis 加速**

会话卡片上的 `scope_name` / `scope_type` / `scope_id` / `workspace_key` 现在也都能跟着回显出来，所以用户刷新后不会只看到一串标题，而是能看到这条会话到底属于“全部 / 文件夹 / 知识库 / 工作区”中的哪一类。
