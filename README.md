# RAG 知识库项目（FastAPI + LangChain + Chroma + DeepSeek）

一个可本地运行的知识库问答项目：支持 Markdown/TXT/PDF/DOCX 入库，先检索再生成，最终由 DeepSeek 输出答案。

## 这套项目做了什么（校正版）

- 文档上传和本地文档自动入库
- 文档切片、Embedding、向量检索（RAG 核心流程）
- DeepSeek 负责最终回答生成
- FastAPI 提供后端 API
- Vue 3 + Element Plus 提供前端问答界面
- 预留了 LangChain Tool，方便后续接入 Agent

## RAG 三个核心步骤（按当前代码解释）

### 1. 文档切片（Chunking）

- 作用：把长文档切成小片段，便于检索和拼接上下文。
- 为什么要切：大模型上下文有限，整本 PDF 不能一次塞进去。
- 当前实现：`app/services/knowledge_base.py` 的 `split_documents()` 使用 `RecursiveCharacterTextSplitter`。
- 关键说明：**chunk 是“检索片段”，不是“一问一答对”**。

### 2. Embedding（向量化）

- 作用：把文本转成向量，便于做“语义相似度”比较。
- 当前实现：`app/services/embeddings.py` 里 `LocalSentenceTransformerEmbeddings`（本地 `sentence-transformers`）。
- 关键说明：当前项目**没有用 `OpenAIEmbeddings`**，也**没有调用 DeepSeek 的 embedding 接口**。

### 3. 向量检索（Vector Search）

- 作用：把用户问题也向量化，再去向量库里找最相关的 K 段文本。
- 当前实现：`app/services/knowledge_base.py` 的 `retrieve()` 调用 `langchain_chroma.Chroma.similarity_search_with_relevance_scores(...)`。
- 关键说明：当前项目**没有使用** `as_retriever()` + `qa_chain.run()` 这条链路，而是“显式检索 + 自定义 Prompt + DeepSeek 生成”。

## 你问的两个关键问题

### Q1：`预留了 LangChain Tool` 是什么意思？

意思是：我们把“知识库搜索”封装成了一个标准工具函数，后续可以让 Agent 自动调用。

- 代码位置：`app/services/tools.py`
- 入口函数：`build_search_tool(...)`
- 工具名：`search_knowledge_base`

未来如果你接 LangChain Agent / LangGraph，Agent 可以在推理过程中主动调用这个工具先查资料，再组织回答。

### Q2：检索到底有没有用 LangChain？

有，用了，而且是关键路径在用：

- `langchain_text_splitters.RecursiveCharacterTextSplitter`（切片）
- `langchain_core.embeddings.Embeddings` 接口（Embedding 适配）
- `langchain_chroma.Chroma`（向量库封装与检索）

但不是“全自动 QA Chain”那种写法。  
当前项目是“半框架化”方式：**检索用 LangChain，生成调用 DeepSeek SDK，Prompt 逻辑自定义**。这在工程里很常见，也更可控。

## 技术栈

- 后端：FastAPI
- 检索框架：LangChain（text splitter + embeddings interface + chroma vectorstore）
- 向量库：Chroma
- Embedding：sentence-transformers（本地）
- LLM：DeepSeek（OpenAI 兼容 API）
- 前端：Vue 3 + Element Plus
- 部署：Docker

## 核心后端文件

- `app/core/settings.py`：环境变量与全局配置
- `app/services/files.py`：文档读取（md/txt/pdf/docx）
- `app/services/embeddings.py`：本地 embedding 适配到 LangChain 接口
- `app/services/knowledge_base.py`：索引构建、检索、问答主链路
- `app/services/tools.py`：Agent Tool 预留
- `app/api/routes.py`：HTTP API（upload/ingest/search/chat）
- `app/main.py`：FastAPI 入口与启动流程

## 本地运行

### 1) 配置环境变量

复制 `.env.example` 为 `.env`，填入：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）
- `DEEPSEEK_MODEL`（建议 `deepseek-v4-flash`）

> 安全提醒：不要把真实 API Key 写死在代码或提交到仓库。

### 2) 安装后端依赖

```bash
pip install -r requirements.txt
```

### 3) 启动后端

```bash
uvicorn app.main:app --reload
```

访问：`http://127.0.0.1:8000/docs`

### 4) 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问：`http://127.0.0.1:5173`

## 简历可用描述（可直接改写）

- 基于 FastAPI + LangChain + Chroma + DeepSeek 搭建本地 RAG 知识库，支持 Markdown/TXT/PDF/DOCX 文档入库、切片检索与引用溯源。  
- 使用本地 sentence-transformers 完成向量化，结合 Chroma 语义检索实现“检索增强生成”问答链路。  
- 采用“显式检索 + 自定义 Prompt + DeepSeek 生成”的工程化方案，并预留 LangChain Tool 以支持后续 Agent 化扩展。  

## Windows（Python 3.11）推荐启动方式

> `.venv311` 是本地虚拟环境目录，不需要提交到 GitHub。

```powershell
cd "e:\00-我的AI Agent\RGA知识库"

# 方式 A：如果 python3.11 已在 PATH
python3.11 -m venv .venv311

# 方式 B：如果 python3.11 不在 PATH，使用完整路径
# C:\Users\<你的用户名>\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv311

.\.venv311\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

说明：
- 这样做可以固定使用 Python 3.11，避免 Python 3.12 在 Windows 上安装 `chroma-hnswlib` 时触发本地 C++ 编译报错。
- 虚拟环境只用于本机开发隔离依赖，不应提交到仓库。

## Chat Production Config (New)

- See `docs/production-chat-config.md` for:
  - DeepSeek + web search `.env` recommendations
  - provider-grouped model dropdown behavior
  - per-answer token/cost estimate behavior
- Use `.env.example` as the template before local or docker startup.

## Multi-Provider Auto Routing (New)

- Backend now routes model calls by model name prefix to provider-specific `API_KEY` + `BASE_URL`.
- Frontend model dropdown now shows availability; models without key are shown as `暂未配置` and cannot be selected.
- Configure providers in `.env` (see `.env.example` and `docs/production-chat-config.md`).

### Supported provider env keys

- `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL`
- `QWEN_API_KEY` + `QWEN_BASE_URL`
- `ZAI_API_KEY` + `ZAI_BASE_URL`
- `KIMI_API_KEY` + `KIMI_BASE_URL`
- `HUNYUAN_API_KEY` + `HUNYUAN_BASE_URL`
- `SILICONFLOW_API_KEY` + `SILICONFLOW_BASE_URL`
- `QIANFAN_API_KEY` + `QIANFAN_BASE_URL`
- `OPENAI_API_KEY` + `OPENAI_BASE_URL`

### Optional advanced routing

- `MODEL_PROVIDER_OVERRIDES_JSON` for explicit model->provider mapping
- `EXTRA_PROVIDER_CONFIGS_JSON` for custom OpenAI-compatible gateways

## ONLYOFFICE Professional Editing (doc/docx/xls/xlsx)

This project now supports professional browser editing for Office files via ONLYOFFICE Docs.

### 1) Environment variables

Set the following in `.env`:

- `ONLYOFFICE_DOCUMENT_SERVER_URL`: browser-accessible URL of ONLYOFFICE Document Server  
  example: `http://127.0.0.1:8088`
- `PUBLIC_BACKEND_URL`: backend URL reachable by ONLYOFFICE server for file download and callback  
  local docker example: `http://host.docker.internal:8000`
- `ONLYOFFICE_JWT_ENABLED`: `true` or `false`
- `ONLYOFFICE_JWT_SECRET`: required when `ONLYOFFICE_JWT_ENABLED=true`
- `ONLYOFFICE_VERIFY_CALLBACK_TOKEN`: optional callback token verification toggle
- `ONLYOFFICE_AUTO_REBUILD_INDEX_ON_SAVE`: auto rebuild RAG index when editor saves

### 2) Docker quick start (example)

```bash
docker run -d --name onlyoffice-docs -p 8088:80 \
  -e JWT_ENABLED=true \
  -e JWT_SECRET=your_secret_here \
  onlyoffice/documentserver
```

### 3) Frontend usage

- Open `Document Management`
- For `doc/docx/xls/xlsx/xlsm`, click `专业编辑` / `Pro Edit`
- Save in ONLYOFFICE editor; backend callback writes file to disk and can auto rebuild index

## ONLYOFFICE Incremental Index + Health (New)

### Incremental index update after save

- Default mode: `ONLYOFFICE_INDEX_UPDATE_MODE=incremental`
- On ONLYOFFICE callback save, backend re-indexes only the saved source file
- Fallback mode: `ONLYOFFICE_INDEX_UPDATE_MODE=full` (rebuild whole index)
- You can disable callback indexing with `ONLYOFFICE_AUTO_REBUILD_INDEX_ON_SAVE=false`

### ONLYOFFICE health panel

- Document Management now includes an `ONLYOFFICE Health` panel
- It checks:
  - Document Server connectivity
  - Command API (`/command` and legacy `/coauthoring/CommandService.ashx`)
  - JWT match (best effort)
  - Callback URL reachability

### How to fill ONLYOFFICE env values

These values are deployment-side settings (not auto-assigned by provider account):

- `ONLYOFFICE_DOCUMENT_SERVER_URL`
  - URL used by browser to load ONLYOFFICE Docs API
  - local example: `http://127.0.0.1:8088`
- `ONLYOFFICE_DOCUMENT_SERVER_INTERNAL_URL`
  - optional backend-only probe/command URL
  - useful when backend container cannot access the public DS URL directly
  - example: `http://onlyoffice` or `http://host.docker.internal:8088`
- `PUBLIC_BACKEND_URL`
  - URL used by ONLYOFFICE server to download files and callback
  - local non-docker: `http://127.0.0.1:8000`
  - docker-compose internal: `http://backend:8000`
- `ONLYOFFICE_JWT_ENABLED`
  - `true` is recommended in production
- `ONLYOFFICE_JWT_SECRET`
  - shared secret between backend and ONLYOFFICE
  - generate one:
    - `python -c "import secrets; print(secrets.token_hex(32))"`
- `ONLYOFFICE_VERIFY_CALLBACK_TOKEN`
  - optional strict callback token verification
- `ONLYOFFICE_AUTO_REBUILD_INDEX_ON_SAVE`
  - whether save callback triggers index update
- `ONLYOFFICE_CALLBACK_TTL_SEC`
  - callback token expiration seconds

### Pull image and run

- Pull image: `docker pull onlyoffice/documentserver:latest`
- Start with compose example: `docker compose -f docker-compose.onlyoffice.yml up -d`

### Production architecture note

- Keep backend and ONLYOFFICE as separate services/containers
- Do not bake ONLYOFFICE into backend `Dockerfile`
- Recommended deployment:
  - backend image from this repo `Dockerfile`
  - ONLYOFFICE from official `onlyoffice/documentserver` image
  - reverse proxy/domain to expose stable HTTPS URLs
