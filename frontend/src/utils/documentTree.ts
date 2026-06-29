import type { DocumentInfo } from "../api";

export interface FolderScopeNode {
  id: number;
  value: number;
  label: string;
  path: string;
  children: FolderScopeNode[];
}

type MutableFolderScopeNode = FolderScopeNode & {
  parentId: number | null;
};

function normalizePath(value: string) {
  return String(value || "")
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "");
}

function resolveFolderLabel(item: DocumentInfo): string {
  const candidates = [item.name, item.display_path, item.path];
  for (const candidate of candidates) {
    const text = String(candidate || "").trim();
    if (text) {
      return text;
    }
  }
  return `Folder ${item.id ?? ""}`.trim();
}

function sortFolders(nodes: FolderScopeNode[]) {
  nodes.sort((left, right) => {
    const labelDiff = left.label.localeCompare(right.label, undefined, { sensitivity: "base" });
    if (labelDiff !== 0) {
      return labelDiff;
    }
    return left.path.localeCompare(right.path, undefined, { sensitivity: "base" });
  });

  for (const node of nodes) {
    if (node.children.length) {
      sortFolders(node.children);
    }
  }
}

export function buildFolderScopeTree(documents: DocumentInfo[]): FolderScopeNode[] {
  const folderRows = documents.filter((item) => item.is_directory && item.id !== null && item.id !== undefined);
  const nodes = new Map<number, MutableFolderScopeNode>();

  for (const folder of folderRows) {
    const id = Number(folder.id);
    if (!Number.isFinite(id) || id <= 0) {
      continue;
    }
    const path = normalizePath(folder.display_path || folder.path);
    nodes.set(id, {
      id,
      value: id,
      label: resolveFolderLabel(folder),
      path,
      children: [],
      parentId: folder.parent_id !== null && folder.parent_id !== undefined && Number(folder.parent_id) > 0
        ? Number(folder.parent_id)
        : null,
    });
  }

  const roots: MutableFolderScopeNode[] = [];
  for (const node of nodes.values()) {
    if (node.parentId !== null && nodes.has(node.parentId)) {
      nodes.get(node.parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const result = roots.map(({ parentId: _parentId, ...node }) => node);
  sortFolders(result);
  return result;
}
