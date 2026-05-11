<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

const props = defineProps<{
  headers: string[];
  rows: string[][];
  dataStartRow?: number;
  snippet?: string;
  truncated?: boolean;
  totalRows?: number;
  totalColumns?: number;
}>();

const gridRef = ref<HTMLElement | null>(null);
const locateRowInput = ref("");
const locateColInput = ref("");
const activeCellKey = ref("");

function normalizeForMatch(raw: string): string {
  return raw.replace(/[\s\u3000]/g, "").replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, "").toLowerCase();
}

function buildSnippetTokens(snippet: string): string[] {
  const normalized = normalizeForMatch(snippet);
  const tokens: string[] = [];
  if (!normalized) {
    return tokens;
  }

  if (normalized.length <= 14) {
    tokens.push(normalized);
    return tokens;
  }

  tokens.push(normalized.slice(0, 20));
  tokens.push(normalized.slice(Math.max(0, Math.floor(normalized.length / 2) - 8), Math.floor(normalized.length / 2) + 8));
  tokens.push(normalized.slice(Math.max(0, normalized.length - 20)));
  return Array.from(new Set(tokens.filter((item) => item.trim())));
}

const snippetTokens = computed(() => buildSnippetTokens(props.snippet ?? ""));
const headerCount = computed(() => props.headers.length);
const dataRowStart = computed(() => Math.max(1, props.dataStartRow ?? 1));

const normalizedRows = computed(() => {
  const width = headerCount.value;
  return props.rows.map((row, index) => {
    const padded = [...row];
    while (padded.length < width) {
      padded.push("");
    }
    return {
      rowNumber: dataRowStart.value + index,
      cells: padded.slice(0, width),
    };
  });
});

const tableSummary = computed(() => {
  const rowCount = props.totalRows ?? props.rows.length;
  const colCount = props.totalColumns ?? props.headers.length;
  return `Rows ${rowCount}, Columns ${colCount}`;
});

function colIndexToLetters(index: number): string {
  let value = index + 1;
  let letters = "";
  while (value > 0) {
    const mod = (value - 1) % 26;
    letters = String.fromCharCode(65 + mod) + letters;
    value = Math.floor((value - 1) / 26);
  }
  return letters;
}

function parseColumnInput(raw: string): number | null {
  const text = raw.trim();
  if (!text) {
    return null;
  }
  if (/^\d+$/.test(text)) {
    const value = Number(text);
    if (!Number.isFinite(value) || value < 1) {
      return null;
    }
    return value - 1;
  }

  const letters = text.toUpperCase();
  if (!/^[A-Z]+$/.test(letters)) {
    return null;
  }

  let result = 0;
  for (let i = 0; i < letters.length; i += 1) {
    result = result * 26 + (letters.charCodeAt(i) - 64);
  }
  return result - 1;
}

function cellKey(rowNumber: number, colIndex: number): string {
  return `${rowNumber}:${colIndex}`;
}

function isCellHit(cellText: string): boolean {
  const left = normalizeForMatch(cellText);
  if (!left || left.length < 3) {
    return false;
  }
  const tokens = snippetTokens.value;
  if (!tokens.length) {
    return false;
  }
  return tokens.some((token) => left.includes(token) || token.includes(left));
}

async function locateCell(rowNumber: number, colIndex: number, behavior: ScrollBehavior = "smooth"): Promise<boolean> {
  const root = gridRef.value;
  if (!root) {
    return false;
  }

  const selector = `[data-row="${rowNumber}"][data-col="${colIndex}"]`;
  const target = root.querySelector<HTMLElement>(selector);
  if (!target) {
    return false;
  }

  activeCellKey.value = cellKey(rowNumber, colIndex);
  await nextTick();
  target.scrollIntoView({
    behavior,
    block: "center",
    inline: "center",
  });
  return true;
}

async function locateFromToolbar() {
  const rowNumber = Number(locateRowInput.value.trim());
  const colIndex = parseColumnInput(locateColInput.value);
  if (!Number.isFinite(rowNumber) || rowNumber < 1 || colIndex === null || colIndex < 0) {
    return;
  }
  void locateCell(rowNumber, colIndex, "smooth");
}

async function focusFirstSnippetHit() {
  if (!snippetTokens.value.length) {
    return;
  }

  for (const row of normalizedRows.value) {
    for (let colIndex = 0; colIndex < row.cells.length; colIndex += 1) {
      if (isCellHit(row.cells[colIndex])) {
        locateRowInput.value = String(row.rowNumber);
        locateColInput.value = colIndexToLetters(colIndex);
        await locateCell(row.rowNumber, colIndex, "smooth");
        return;
      }
    }
  }
}

watch(
  () => [props.headers, props.rows, props.dataStartRow],
  () => {
    activeCellKey.value = "";
    locateRowInput.value = String(dataRowStart.value);
    locateColInput.value = "A";
  },
  { immediate: true },
);

watch(
  () => [props.snippet, props.rows, props.headers],
  () => {
    void nextTick().then(() => focusFirstSnippetHit());
  },
  { immediate: true },
);
</script>

<template>
  <section class="sheet-viewer">
    <header class="sheet-toolbar">
      <div class="sheet-meta">
        <strong>{{ tableSummary }}</strong>
        <small v-if="truncated">Preview truncated for performance.</small>
      </div>
      <div class="sheet-locator">
        <label>
          Row
          <input v-model="locateRowInput" type="number" min="1" />
        </label>
        <label>
          Col
          <input v-model="locateColInput" type="text" placeholder="A / 3" />
        </label>
        <button type="button" class="locate-btn" @click="locateFromToolbar">Go</button>
      </div>
    </header>

    <div ref="gridRef" class="sheet-grid-wrap">
      <table class="sheet-grid">
        <thead>
          <tr>
            <th class="row-head">#</th>
            <th v-for="(header, index) in headers" :key="`head-${index}`" :title="header">
              <span class="col-name">{{ colIndexToLetters(index) }}</span>
              <span class="col-title">{{ header }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in normalizedRows" :key="`row-${row.rowNumber}`">
            <th class="row-index">{{ row.rowNumber }}</th>
            <td
              v-for="(cell, colIndex) in row.cells"
              :key="`cell-${row.rowNumber}-${colIndex}`"
              :data-row="row.rowNumber"
              :data-col="colIndex"
              :title="cell"
              :class="[
                'sheet-cell',
                isCellHit(cell) ? 'is-hit' : '',
                activeCellKey === cellKey(row.rowNumber, colIndex) ? 'is-active' : '',
              ]"
            >
              {{ cell || " " }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.sheet-viewer {
  display: grid;
  gap: 10px;
}

.sheet-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #dbe3ef;
  border-radius: 10px;
  padding: 8px 10px;
  background: #f8fafc;
}

.sheet-meta {
  display: grid;
  gap: 2px;
}

.sheet-meta strong {
  font-size: 0.84rem;
  color: #0f172a;
}

.sheet-meta small {
  color: #64748b;
  font-size: 0.75rem;
}

.sheet-locator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.sheet-locator label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #475569;
  font-size: 0.78rem;
}

.sheet-locator input {
  width: 84px;
  height: 28px;
  border: 1px solid #cfd8e3;
  border-radius: 8px;
  background: #fff;
  color: #0f172a;
  padding: 0 8px;
}

.locate-btn {
  height: 28px;
  border: 1px solid #10a37f;
  border-radius: 8px;
  background: #0f766e;
  color: #fff;
  padding: 0 10px;
  font-size: 0.78rem;
  cursor: pointer;
}

.sheet-grid-wrap {
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  overflow: auto;
  max-height: 68vh;
  background: #fff;
}

.sheet-grid {
  width: max-content;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: auto;
}

.sheet-grid th,
.sheet-grid td {
  border-right: 1px solid #e5edf7;
  border-bottom: 1px solid #e5edf7;
  padding: 7px 9px;
  font-size: 0.82rem;
  color: #0f172a;
  vertical-align: top;
  white-space: pre-wrap;
  min-width: 120px;
  max-width: 360px;
}

.sheet-grid thead th {
  position: sticky;
  top: 0;
  z-index: 4;
  background: #f1f5f9;
}

.sheet-grid .row-head {
  position: sticky;
  left: 0;
  z-index: 6;
  min-width: 72px;
  max-width: 72px;
  text-align: center;
}

.sheet-grid .row-index {
  position: sticky;
  left: 0;
  z-index: 5;
  min-width: 72px;
  max-width: 72px;
  text-align: center;
  background: #f8fafc;
  color: #475569;
}

.col-name {
  display: block;
  font-size: 0.7rem;
  color: #64748b;
  line-height: 1.1;
}

.col-title {
  display: block;
  font-weight: 650;
  margin-top: 2px;
}

.sheet-cell.is-hit {
  background: rgba(52, 211, 153, 0.22);
}

.sheet-cell.is-active {
  box-shadow: inset 0 0 0 2px rgba(15, 118, 110, 0.9);
  background: rgba(20, 184, 166, 0.16);
}

@media (max-width: 900px) {
  .sheet-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .sheet-locator {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
