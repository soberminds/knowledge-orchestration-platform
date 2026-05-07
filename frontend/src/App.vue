<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  chat,
  getHealth,
  listDocuments,
  rebuildIndex,
  uploadDocuments,
  type DocumentInfo,
  type HealthResponse,
  type HistoryItem,
  type SourceHit,
} from "./api";

const question = ref("我的笔记里关于 Flex 布局的总结是什么？");
const answer = ref(
  "点击右侧的“开始问答”，系统会先检索本地文档，再交给 DeepSeek 生成答案。",
);
const sources = ref<SourceHit[]>([]);
const documents = ref<DocumentInfo[]>([]);
const history = ref<HistoryItem[]>([]);
const health = ref<HealthResponse | null>(null);
const loading = ref(false);
const ingesting = ref(false);
const uploading = ref(false);
const errorMessage = ref("");
const topK = ref(4);
const selectedFiles = ref<File[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);

const selectedFileNames = computed(() => selectedFiles.value.map((file) => file.name));

const examples = [
  "我的笔记里关于 Flex 布局的总结是什么？",
  "RAG 知识库的完整流程可以怎么讲？",
  "这个项目用了哪些技术栈？",
];

function setExample(text: string) {
  question.value = text;
}

function clearHistory() {
  history.value = [];
}

async function refreshDashboard() {
  const [healthData, docs] = await Promise.all([getHealth(), listDocuments()]);
  health.value = healthData;
  documents.value = docs;
}

async function runIngest() {
  ingesting.value = true;
  errorMessage.value = "";
  try {
    await rebuildIndex();
    await refreshDashboard();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "索引重建失败";
  } finally {
    ingesting.value = false;
  }
}

function onUploadChange(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files || input.files.length === 0) {
    return;
  }

  selectedFiles.value = Array.from(input.files);
}

async function uploadAndBuild() {
  if (selectedFiles.value.length === 0) {
    errorMessage.value = "先选择要上传的文档，再点击上传。";
    return;
  }

  uploading.value = true;
  errorMessage.value = "";
  try {
    await uploadDocuments(selectedFiles.value);
    selectedFiles.value = [];
    if (fileInput.value) {
      fileInput.value.value = "";
    }
    await refreshDashboard();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "上传失败";
  } finally {
    uploading.value = false;
  }
}

async function ask() {
  if (!question.value.trim()) {
    errorMessage.value = "请输入一个问题。";
    return;
  }

  loading.value = true;
  errorMessage.value = "";
  try {
    const currentQuestion = question.value.trim();
    const result = await chat({
      question: currentQuestion,
      history: history.value.slice(-6),
      top_k: topK.value,
    });

    answer.value = result.answer;
    sources.value = result.sources;
    history.value.push({ role: "user", content: currentQuestion });
    history.value.push({ role: "assistant", content: result.answer });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "问答失败";
  } finally {
    loading.value = false;
  }
}

async function askQuick(text: string) {
  setExample(text);
  await ask();
}

onMounted(async () => {
  try {
    await refreshDashboard();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "初始化失败";
  }
});
</script>

<template>
  <main class="app-shell">
    <div class="orb orb-a"></div>
    <div class="orb orb-b"></div>
    <div class="orb orb-c"></div>

    <section class="hero panel">
      <div>
        <p class="eyebrow">DeepSeek · FastAPI · Chroma · Vue 3</p>
        <h1>RAG 知识库</h1>
        <p class="lead">
          把本地 Markdown、TXT、PDF、DOCX 变成可问答的知识中台。上传文档、重建索引、即时检索、生成答案，一条链路全打通。
        </p>
      </div>

      <div class="hero-stats">
        <article class="stat-card">
          <span>索引状态</span>
          <strong>{{ health?.status ?? "loading" }}</strong>
        </article>
        <article class="stat-card">
          <span>已切片数量</span>
          <strong>{{ health?.indexed_chunks ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span>文档数量</span>
          <strong>{{ documents.length }}</strong>
        </article>
      </div>
    </section>

    <section v-if="errorMessage" class="error-row">
      <el-alert :title="errorMessage" type="error" show-icon :closable="false" />
    </section>

    <section class="grid">
      <div class="column">
        <el-card class="panel upload-panel" shadow="never">
          <template #header>
            <div class="panel-title">
              <span>文档入口</span>
              <el-tag type="success" effect="dark">{{ health?.collection_name ?? "..." }}</el-tag>
            </div>
          </template>

          <div class="upload-box">
            <label class="file-picker">
              <input ref="fileInput" type="file" multiple @change="onUploadChange" />
              <span>选择文档</span>
            </label>

            <div class="file-preview" v-if="selectedFileNames.length">
              <el-tag v-for="name in selectedFileNames" :key="name" type="info" effect="plain">
                {{ name }}
              </el-tag>
            </div>

            <div class="actions">
              <el-button type="primary" :loading="uploading" @click="uploadAndBuild">上传并重建索引</el-button>
              <el-button :loading="ingesting" @click="runIngest">仅重建索引</el-button>
            </div>
          </div>
        </el-card>

        <el-card class="panel docs-panel" shadow="never">
          <template #header>
            <div class="panel-title">
              <span>已接入文档</span>
              <el-tag type="warning" effect="plain">{{ documents.length }}</el-tag>
            </div>
          </template>

          <div v-if="documents.length" class="doc-list">
            <article v-for="doc in documents" :key="doc.path" class="doc-item">
              <div class="doc-head">
                <strong>{{ doc.path }}</strong>
                <el-tag size="small" type="info">{{ doc.extension }}</el-tag>
              </div>
              <p>{{ doc.modified_at }} · {{ doc.size_bytes }} bytes</p>
            </article>
          </div>
          <el-empty
            v-else
            description="把 Markdown / PDF / TXT / DOCX 放进 data/docs，或通过上传接口接入"
          />
        </el-card>

        <el-card class="panel flow-panel" shadow="never">
          <template #header>
            <div class="panel-title">
              <span>这套 RAG 的关键步骤</span>
            </div>
          </template>
          <ol class="flow-list">
            <li>加载文档并按规则切片。</li>
            <li>用本地 Sentence Transformer 做向量化。</li>
            <li>把向量和元数据存进 Chroma。</li>
            <li>提问时先检索，再交给 DeepSeek 生成答案。</li>
          </ol>
        </el-card>
      </div>

      <div class="column main-column">
        <el-card class="panel chat-panel" shadow="never">
          <template #header>
            <div class="panel-title">
              <span>问答区</span>
              <div class="kpi-row">
                <el-input-number v-model="topK" :min="1" :max="10" size="small" controls-position="right" />
                <el-tag type="success" effect="plain">top_k</el-tag>
              </div>
            </div>
          </template>

          <div class="examples">
            <button v-for="item in examples" :key="item" class="example-chip" @click="setExample(item)">
              {{ item }}
            </button>
          </div>

          <el-input
            v-model="question"
            type="textarea"
            :rows="7"
            resize="none"
            placeholder="输入你的问题，例如：我的笔记里关于 Flex 布局的总结是什么？"
          />

          <div class="actions">
            <el-button type="primary" :loading="loading" @click="ask">开始问答</el-button>
            <el-button plain @click="clearHistory">清空上下文</el-button>
          </div>
        </el-card>

        <el-card class="panel answer-panel" shadow="never">
          <template #header>
            <div class="panel-title">
              <span>模型回答</span>
              <el-tag type="info" effect="plain">{{ sources.length }} 条引用</el-tag>
            </div>
          </template>

          <div class="answer-body">
            <div class="answer-text">{{ answer }}</div>

            <div v-if="sources.length" class="source-zone">
              <h3>引用来源</h3>
              <article v-for="(source, index) in sources" :key="`${source.source}-${index}`" class="source-item">
                <div class="source-meta">
                  <strong>[{{ index + 1 }}] {{ source.source }}</strong>
                  <span>chunk {{ source.chunk_index }}</span>
                  <span v-if="source.page !== null && source.page !== undefined">page {{ source.page }}</span>
                  <span v-if="source.score !== null && source.score !== undefined">score {{ source.score }}</span>
                </div>
                <p>{{ source.preview }}</p>
              </article>
            </div>
          </div>
        </el-card>
      </div>
    </section>

    <section class="footer-note">
      <span>这个页面专门为“简历演示”准备，强调的是完整链路和工程化交付感。</span>
      <el-button text type="primary" @click="askQuick('RAG 知识库的完整流程可以怎么讲？')">
        快速问一句
      </el-button>
    </section>
  </main>
</template>

