// P4：节点配色（参照 ../ComfyUI-QwenVL/web/js/appearance.js 的观感，按新 Node ID 重写）。

import { app } from "/scripts/app.js";

const THEMES = {
  Ollama: { nodeColor: "#2b3a4a", nodeBgColor: "#22303d", width: 360 },
  QwenVL: { nodeColor: "#28403f", nodeBgColor: "#28403f", width: 360 },
  Enhancer: { nodeColor: "#374445", nodeBgColor: "#474539", width: 360 },
};

const NODE_COLORS = {
  OllamaQWEConnect: "Ollama",
  OllamaQWEVL: "QwenVL",
  OllamaQWEVLAdvanced: "QwenVL",
  OllamaQWEEnhancer: "Enhancer",
};

function applyTheme(node, theme) {
  if (!theme) return;
  if (theme.nodeColor) node.color = theme.nodeColor;
  if (theme.nodeBgColor) node.bgcolor = theme.nodeBgColor;
  if (theme.width) {
    node.size = node.size || [240, 100];
    node.size[0] = Math.max(node.size[0], theme.width);
  }
}

app.registerExtension({
  name: "Comfy.OllamaQWEnhancer.Appearance",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const themeName = NODE_COLORS[nodeData.name];
    if (!themeName) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);
      applyTheme(this, THEMES[themeName]);
      return result;
    };
  },
});
