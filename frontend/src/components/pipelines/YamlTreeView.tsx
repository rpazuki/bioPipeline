"use client";

import { useEffect, useMemo, useState } from "react";

import type { YamlTreeNode } from "@/types";

interface Props {
  nodes: YamlTreeNode[];
  selectedPath: string;
  onSelect: (node: YamlTreeNode) => void;
  onNavigatePath?: (path: string) => void;
}

function findNode(nodes: YamlTreeNode[], path: string): YamlTreeNode | null {
  for (const node of nodes) {
    if (node.path === path) return node;
    const nested = findNode(node.children, path);
    if (nested) return nested;
  }
  return null;
}

function collectFolderPaths(nodes: YamlTreeNode[]): string[] {
  return nodes.flatMap((node) => {
    const nested = collectFolderPaths(node.children);
    return node.node_type === "folder" ? [node.path, ...nested].filter(Boolean) : nested;
  });
}

function ancestorPaths(path: string): string[] {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join("/"));
}

function FileBadge({ node }: { node: YamlTreeNode }) {
  if (node.node_type !== "file") return null;
  if (!node.is_valid) {
    return <span className="text-[11px] font-semibold text-amber-700">invalid</span>;
  }
  if (!node.pipelines.length) {
    return <span className="text-[11px] text-slate-500">no pipelines</span>;
  }
  return <span className="text-[11px] text-slate-500">{node.pipelines.length} pipeline{node.pipelines.length === 1 ? "" : "s"}</span>;
}

function TreeNode({ node, depth, selectedPath, onSelect, expandedPaths, onToggle }: { node: YamlTreeNode; depth: number; selectedPath: string; onSelect: (node: YamlTreeNode) => void; expandedPaths: Set<string>; onToggle: (path: string) => void; }) {
  const isSelected = node.path === selectedPath;
  const indent = { paddingLeft: `${depth * 16 + 12}px` };
  const isExpanded = node.node_type !== "folder" || expandedPaths.has(node.path);
  const hasChildren = node.node_type === "folder" && node.children.length > 0;

  return (
    <div>
      <div className="flex items-center gap-1">
        {node.node_type === "folder" ? (
          <button
            type="button"
            style={indent}
            className="rounded-md px-1 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100"
            onClick={() => onToggle(node.path)}
            aria-label={isExpanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
          >
            {hasChildren ? (isExpanded ? "v" : ">") : "-"}
          </button>
        ) : (
          <span style={indent} className="w-4" />
        )}
        <button
          type="button"
          className={`flex min-w-0 flex-1 items-center justify-between rounded-md py-1 pr-3 text-left text-sm ${
            isSelected ? "bg-cyan-50 text-cyan-900" : "text-slate-800 hover:bg-slate-50"
          } ${node.node_type === "folder" ? "font-semibold" : ""}`}
          onClick={() => onSelect(node)}
        >
          <span className="truncate">
            {node.node_type === "folder" ? "[dir] " : ""}
            {node.name}
          </span>
          <FileBadge node={node} />
        </button>
      </div>
      {node.children.length && isExpanded ? (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={`${child.path || child.name}-${child.node_type}`}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              expandedPaths={expandedPaths}
              onToggle={onToggle}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function YamlTreeView({ nodes, selectedPath, onSelect, onNavigatePath }: Props) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());

  const folderPaths = useMemo(() => collectFolderPaths(nodes), [nodes]);

  useEffect(() => {
    setExpandedPaths((current) => {
      if (current.size === 0) {
        return new Set(folderPaths);
      }
      const next = new Set(current);
      for (const path of ancestorPaths(selectedPath)) {
        next.add(path);
      }
      return next;
    });
  }, [folderPaths, selectedPath]);

  function toggle(path: string) {
    setExpandedPaths((current) => {
      const next = new Set(current);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }

  function navigate(path: string) {
    if (onNavigatePath) {
      onNavigatePath(path);
      return;
    }
    const node = findNode(nodes, path);
    if (node) {
      onSelect(node);
    }
  }

  const breadcrumbParts = selectedPath.split("/").filter(Boolean);

  if (!nodes.length) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-500">
        No folders or YAML files found yet.
      </div>
    );
  }

  return (
    <div className="grid content-start gap-2 rounded-md border border-slate-200 bg-white p-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2 text-xs">
        <div className="flex flex-wrap items-center gap-1 text-slate-500">
          <button type="button" className="rounded-md px-2 py-1 font-semibold hover:bg-slate-100" onClick={() => navigate("")}>root</button>
          {breadcrumbParts.map((part, index) => {
            const path = breadcrumbParts.slice(0, index + 1).join("/");
            return (
              <div key={path} className="flex items-center gap-1">
                <span>/</span>
                <button type="button" className="rounded-md px-2 py-1 hover:bg-slate-100" onClick={() => navigate(path)}>
                  {part}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex gap-1">
          <button type="button" className="rounded-md border border-slate-300 px-2 py-1 font-semibold text-slate-600" onClick={() => setExpandedPaths(new Set(folderPaths))}>
            Expand all
          </button>
          <button type="button" className="rounded-md border border-slate-300 px-2 py-1 font-semibold text-slate-600" onClick={() => setExpandedPaths(new Set(ancestorPaths(selectedPath)))}>
            Collapse all
          </button>
        </div>
      </div>
      <div>
        {nodes.map((node) => (
          <TreeNode
            key={`${node.path || node.name}-${node.node_type}`}
            node={node}
            depth={0}
            selectedPath={selectedPath}
            onSelect={onSelect}
            expandedPaths={expandedPaths}
            onToggle={toggle}
          />
        ))}
      </div>
    </div>
  );
}
