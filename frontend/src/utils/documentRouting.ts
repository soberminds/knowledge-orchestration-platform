const EDITABLE_TEXT_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".xml",
  ".ini",
  ".cfg",
  ".conf",
  ".toml",
  ".log",
  ".rst",
  ".rtf",
  ".sql",
  ".py",
  ".js",
  ".ts",
  ".jsx",
  ".tsx",
  ".java",
  ".c",
  ".cpp",
  ".h",
  ".hpp",
  ".go",
  ".rs",
  ".sh",
  ".bat",
  ".ps1",
]);

export const ONLYOFFICE_DOCUMENT_EXTENSIONS = [".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx"] as const;
const ONLYOFFICE_EXTENSION_SET = new Set<string>(ONLYOFFICE_DOCUMENT_EXTENSIONS);

export function getDocumentExtension(value: string): string {
  let normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }

  const queryIndex = normalized.indexOf("?");
  if (queryIndex >= 0) {
    normalized = normalized.slice(0, queryIndex);
  }

  const hashIndex = normalized.indexOf("#");
  if (hashIndex >= 0) {
    normalized = normalized.slice(0, hashIndex);
  }

  const slashIndex = Math.max(normalized.lastIndexOf("/"), normalized.lastIndexOf("\\"));
  if (slashIndex >= 0) {
    normalized = normalized.slice(slashIndex + 1);
  }

  if (!normalized) {
    return "";
  }

  if (normalized.startsWith(".")) {
    return normalized;
  }

  const dotIndex = normalized.lastIndexOf(".");
  if (dotIndex < 0) {
    return "";
  }

  return normalized.slice(dotIndex);
}

export function isOnlyOfficeDocument(value: string): boolean {
  return ONLYOFFICE_EXTENSION_SET.has(getDocumentExtension(value));
}

export function isEditableTextDocument(value: string): boolean {
  return EDITABLE_TEXT_EXTENSIONS.has(getDocumentExtension(value));
}
