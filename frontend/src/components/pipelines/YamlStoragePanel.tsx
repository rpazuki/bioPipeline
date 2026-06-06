"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import YamlTreeView from "@/components/pipelines/YamlTreeView";
import {
  createYamlFolder,
  deletePipelineYaml,
  deleteYamlFolder,
  getPipelineTemplate,
  getPipelineYaml,
  getPipelineYamlTree,
  listPipelineTemplates,
  movePipelineYaml,
} from "@/lib/api";
import type { PipelineTemplateSummary, YamlTreeNode } from "@/types";

type ActionPanel = "add-folder" | "add-yaml" | "move-rename" | null;

interface Props {
  yamlName: string;
  onYamlNameChange: (name: string) => void;
  onYamlContentChange: (content: string) => void;
  onPipelinesChange: (pipelines: string[]) => void;
  onYamlValidityChange: (isValid: boolean, error: string | null) => void;
  onStatus: (message: string) => void;
}

function joinPath(folderPath: string, fileName: string) {
  return [folderPath, fileName].filter(Boolean).join("/");
}

function parentFolder(path: string) {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

function findNode(nodes: YamlTreeNode[], path: string): YamlTreeNode | null {
  for (const node of nodes) {
    if (node.path === path) return node;
    const nested = findNode(node.children, path);
    if (nested) return nested;
  }
  return null;
}

export default function YamlStoragePanel({
  yamlName,
  onYamlNameChange,
  onYamlContentChange,
  onPipelinesChange,
  onYamlValidityChange,
  onStatus,
}: Props) {
  const router = useRouter();
  const [tree, setTree] = useState<YamlTreeNode[]>([]);
  const [templates, setTemplates] = useState<PipelineTemplateSummary[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("empty");
  const [selectedPath, setSelectedPath] = useState("");
  const [createFileName, setCreateFileName] = useState("pipeline.yaml");
  const [newFolderName, setNewFolderName] = useState("");
  const [moveTargetPath, setMoveTargetPath] = useState("");
  const [activePanel, setActivePanel] = useState<ActionPanel>(null);
  const [selectedFileMessage, setSelectedFileMessage] = useState<string | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const selectedNode = useMemo(() => findNode(tree, selectedPath), [tree, selectedPath]);
  const activeFolderPath = selectedNode?.node_type === "folder" ? selectedNode.path : selectedNode ? parentFolder(selectedNode.path) : "";

  useEffect(() => {
    if (selectedNode?.node_type === "file") {
      setMoveTargetPath(selectedNode.path);
    }
    if (activePanel === "move-rename" && selectedNode?.node_type !== "file") {
      setActivePanel(null);
    }
  }, [activePanel, selectedNode]);

  async function refresh() {
    const [treeNodes, templateList] = await Promise.all([getPipelineYamlTree(), listPipelineTemplates()]);
    setTree(treeNodes);
    setTemplates(templateList);
    if (templateList.length && !templateList.some((template) => template.name === selectedTemplate)) {
      setSelectedTemplate(templateList[0].name);
    }
  }

  function run(label: string, fn: () => Promise<void>) {
    setFileError(null);
    fn().catch((cause: Error) => {
      setFileError(cause.message);
      onStatus(`${label} failed: ${cause.message}`);
    });
  }

  function createFolder() {
    setFolderError(null);
    addFolder().catch((cause: Error) => {
      setFolderError(cause.message);
      onStatus(`Create folder failed: ${cause.message}`);
    });
  }

  function createYaml() {
    setCreateError(null);
    createAndEdit().catch((cause: Error) => {
      setCreateError(cause.message);
      onStatus(`Create failed: ${cause.message}`);
    });
  }

  useEffect(() => {
    run("Load storage", refresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectNode(node: YamlTreeNode) {
    setSelectedPath(node.path);
    setSelectedFileMessage(null);

    if (node.node_type === "folder") {
      onStatus(`Selected folder ${node.path || "."}`);
      return;
    }

    const document = await getPipelineYaml(node.path);
    onYamlNameChange(document.name);
    onYamlContentChange(document.content);
    onPipelinesChange(document.pipelines);
    onYamlValidityChange(document.is_valid, document.error ?? null);
    setSelectedFileMessage(document.is_valid ? null : document.error ?? "Invalid YAML");
    onStatus(document.is_valid ? `Selected ${document.name}` : `Selected ${document.name}; invalid YAML`);
  }

  async function navigatePath(path: string) {
    if (!path) {
      setSelectedPath("");
      setSelectedFileMessage(null);
      onStatus("Selected root folder");
      return;
    }
    const node = findNode(tree, path);
    if (!node) {
      throw new Error(`Path not found: ${path}`);
    }
    await selectNode(node);
  }

  async function addFolder() {
    const folderName = newFolderName.trim().replace(/^\/+|\/+$/g, "");
    if (!folderName) {
      throw new Error("Enter a folder name first");
    }
    const folderPath = joinPath(activeFolderPath, folderName);
    await createYamlFolder(folderPath);
    setNewFolderName("");
    await refresh();
    setSelectedPath(folderPath);
    onStatus(`Created folder ${folderPath}`);
    setActivePanel(null);
  }

  async function removeFolder() {
    if (!selectedNode || selectedNode.node_type !== "folder" || !selectedNode.path) {
      throw new Error("Select a folder to delete");
    }
    if (selectedNode.children.length > 0) {
      throw new Error("Only empty folders can be deleted");
    }
    if (!window.confirm(`Delete folder ${selectedNode.path}? This cannot be undone.`)) {
      return;
    }
    await deleteYamlFolder(selectedNode.path);
    await refresh();
    setSelectedPath(parentFolder(selectedNode.path));
    onStatus(`Deleted folder ${selectedNode.path}`);
  }

  async function createAndEdit() {
    const fileName = createFileName.trim().replace(/^\/+|\/+$/g, "");
    if (!fileName) {
      throw new Error("Enter a YAML file name first");
    }
    if (fileName.includes("/")) {
      throw new Error("Enter only a YAML file name; folder comes from your current selection");
    }
    const targetPath = joinPath(activeFolderPath, fileName);
    const template = await getPipelineTemplate(selectedTemplate);

    onYamlNameChange(targetPath);
    onYamlContentChange(template.content);
    onPipelinesChange([]);
    onYamlValidityChange(true, null);
    onStatus(`Editing new YAML ${targetPath} in validation`);
    setActivePanel(null);
    router.push("/validation");
  }

  async function editSelectedFile() {
    if (!selectedNode || selectedNode.node_type !== "file") {
      throw new Error("Select a YAML file to edit");
    }
    const document = await getPipelineYaml(selectedNode.path);
    onYamlNameChange(document.name);
    onYamlContentChange(document.content);
    onPipelinesChange(document.pipelines);
    onYamlValidityChange(document.is_valid, document.error ?? null);
    onStatus(`Editing ${document.name} in validation`);
    router.push("/validation");
  }

  async function moveSelectedFile() {
    if (!selectedNode || selectedNode.node_type !== "file") {
      throw new Error("Select a YAML file to move");
    }
    const targetPath = moveTargetPath.trim();
    if (!targetPath) {
      throw new Error("Enter a destination path first");
    }
    const document = await movePipelineYaml(selectedNode.path, targetPath);
    await refresh();
    setSelectedPath(document.name);
    setSelectedFileMessage(document.is_valid ? null : document.error ?? "Invalid YAML");
    if (yamlName === selectedNode.path) {
      onYamlNameChange(document.name);
      onYamlContentChange(document.content);
      onPipelinesChange(document.pipelines);
      onYamlValidityChange(document.is_valid, document.error ?? null);
    }
    onStatus(`Moved ${selectedNode.path} to ${document.name}`);
    setActivePanel(null);
  }

  async function deleteSelectedFileAction() {
    if (!selectedNode || selectedNode.node_type !== "file") {
      throw new Error("Select a YAML file to delete");
    }
    const filePath = selectedNode.path;
    if (!window.confirm(`Delete YAML file ${filePath}? This cannot be undone.`)) {
      return;
    }
    await deletePipelineYaml(filePath);
    await refresh();
    setSelectedPath(parentFolder(filePath));
    setSelectedFileMessage(null);
    if (yamlName === filePath) {
      onYamlNameChange("pipeline.yaml");
      onYamlContentChange("");
      onPipelinesChange([]);
      onYamlValidityChange(true, null);
    }
    onStatus(`Deleted ${filePath}`);
    setActivePanel(null);
  }

  const canDeleteFolder = Boolean(selectedNode && selectedNode.node_type === "folder" && selectedNode.path);

  return (
    <section className="grid gap-4 border border-slate-200 bg-white p-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-950">YAML Storage</h2>
        <p className="mt-1 text-xs text-slate-500">Browse folders and YAML files under <span className="font-mono">.bio_pipeline/yamls</span>.</p>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div className="grid self-start gap-3">
          <YamlTreeView
            nodes={tree}
            selectedPath={selectedPath}
            onSelect={(node) => run("Select", () => selectNode(node))}
            onNavigatePath={(path) => run("Navigate", () => navigatePath(path))}
          />
        </div>

        <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="grid gap-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selection</div>
            <div className="rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-800">
              {selectedNode ? (
                <div className="grid gap-1">
                  <div className="font-semibold text-slate-950">{selectedNode.path || "."}</div>
                  <div className="text-xs text-slate-500">{selectedNode.node_type === "folder" ? "Folder" : "YAML file"}</div>
                  {selectedNode.node_type === "file" && selectedNode.pipelines.length ? (
                    <div className="text-xs text-slate-500">Pipelines: {selectedNode.pipelines.join(", ")}</div>
                  ) : null}
                  {selectedFileMessage ? <div className="text-xs text-amber-700">{selectedFileMessage}</div> : null}
                </div>
              ) : (
                <div className="grid gap-1">
                  <div className="font-semibold text-slate-950">.</div>
                  <div className="text-xs text-slate-500">Root folder</div>
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-3">
            <h3 className="text-sm font-semibold text-slate-950">Actions</h3>
            <p className="text-xs text-slate-500">Use these buttons for the selected item.</p>
            <div className="flex flex-wrap gap-2">
              <button
                className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white"
                onClick={() => {
                  setFolderError(null);
                  setActivePanel("add-folder");
                }}
              >
                Add folder
              </button>
              <button
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
                onClick={() => {
                  setCreateError(null);
                  setCreateFileName("pipeline.yaml");
                  setActivePanel("add-yaml");
                }}
              >
                Add YAML
              </button>
              {selectedNode?.node_type === "folder" ? (
                <button
                  className="rounded-md border border-red-200 px-3 py-2 text-sm font-semibold text-red-700 disabled:opacity-40"
                  onClick={() => {
                    setFolderError(null);
                    removeFolder().catch((cause: Error) => {
                      setFolderError(cause.message);
                      onStatus(`Delete folder failed: ${cause.message}`);
                    });
                  }}
                  disabled={!canDeleteFolder || selectedNode.children.length > 0}
                >
                  Delete selected folder
                </button>
              ) : null}
              {selectedNode?.node_type === "file" ? (
                <>
                  <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => run("Edit", editSelectedFile)}>
                    Edit in validation
                  </button>
                  <button
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
                    onClick={() => {
                      setFileError(null);
                      setMoveTargetPath(selectedNode.path);
                      setActivePanel("move-rename");
                    }}
                  >
                    Move / rename
                  </button>
                  <button className="rounded-md border border-red-200 px-3 py-2 text-sm font-semibold text-red-700" onClick={() => run("Delete", deleteSelectedFileAction)}>
                    Delete file
                  </button>
                </>
              ) : null}
            </div>
            {!canDeleteFolder ? <div className="text-xs text-slate-500">Select a folder to enable folder deletion.</div> : null}
            {selectedNode?.node_type === "folder" && selectedNode.children.length > 0 ? <div className="text-xs text-slate-500">Only empty folders can be deleted.</div> : null}
            {folderError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">{folderError}</div> : null}
          </div>

          {activePanel === "add-folder" ? (
            <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-3">
              <h3 className="text-sm font-semibold text-slate-950">Folders</h3>
              <p className="text-xs text-slate-500">New folders are created inside the selected folder.</p>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                New folder name
                <input
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                  value={newFolderName}
                  onChange={(event) => setNewFolderName(event.target.value)}
                  placeholder="analysis"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white" onClick={createFolder}>
                  Add folder
                </button>
                <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => setActivePanel(null)}>
                  Close
                </button>
              </div>
              {folderError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">{folderError}</div> : null}
            </div>
          ) : null}

          {activePanel === "add-yaml" ? (
            <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-3">
              <h3 className="text-sm font-semibold text-slate-950">Create in selected folder</h3>
              <p className="text-xs text-slate-500">Folder: <span className="font-mono">{activeFolderPath || "."}</span></p>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                YAML file name
                <input
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                  value={createFileName}
                  onChange={(event) => setCreateFileName(event.target.value)}
                  placeholder="pipeline.yaml"
                />
              </label>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                Template
                <select
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                  value={selectedTemplate}
                  onChange={(event) => setSelectedTemplate(event.target.value)}
                >
                  {templates.map((template) => (
                    <option key={template.name} value={template.name}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white" onClick={createYaml}>
                  Create &amp; edit in validation
                </button>
                <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => setActivePanel(null)}>
                  Close
                </button>
              </div>
              {createError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">{createError}</div> : null}
            </div>
          ) : null}

          {activePanel === "move-rename" && selectedNode?.node_type === "file" ? (
            <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-3">
              <h3 className="text-sm font-semibold text-slate-950">Move / rename YAML</h3>
              <p className="text-xs text-slate-500">Current path: <span className="font-mono">{selectedNode.path}</span></p>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                New path (folder/name.yaml)
                <input
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                  value={moveTargetPath}
                  onChange={(event) => setMoveTargetPath(event.target.value)}
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => run("Move", moveSelectedFile)}>
                  Move / rename
                </button>
                <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => setActivePanel(null)}>
                  Close
                </button>
              </div>
            </div>
          ) : null}

          {fileError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">{fileError}</div> : null}
        </div>
      </div>
    </section>
  );
}