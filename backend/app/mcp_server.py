"""某行知识库 MCP Server。

将文档检索、代码检索、知识图谱、答案缓存、影响分析等能力暴露为 MCP Tools，
由 Cursor / Claude Desktop 等 Host 的模型自动调度。

启动（stdio，供 Cursor 配置）：
  cd backend
  python -m app.mcp_server
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _bootstrap() -> None:
    from app.db import init_db
    from app.ingest.tagger import ensure_vocab
    from app.seed import seed_knowledge, seed_users

    init_db()
    seed_users()
    ensure_vocab()
    seed_knowledge(force=False)


def build_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError:
        # mcp 2.x 兼容入口
        from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore

    from app.tools.handlers import invoke_tool

    mcp = FastMCP(
        "hf-kb",
        instructions=(
            "某行核心系统迁移知识库工具集。\n"
            "【接入建库链路】scan_dataset → clean_dataset → build_knowledge_graph → kb_stats；"
            "也可直接调用 ingest_knowledge_base 一键编排。\n"
            "【问答链路】analyze_question → query_cache；未命中再 search_graph/search_doc/search_code。"
            "禁止编造业务规则。"
        ),
    )

    @mcp.tool()
    def analyze_question(question: str) -> str:
        """分析用户问题：意图、实体、改写检索问句。"""
        return json.dumps(invoke_tool("analyze_question", {"question": question}),
                          ensure_ascii=False)

    @mcp.tool()
    def query_cache(question: str, scene_code: str = "ATM") -> str:
        """查询已验证答案库（exact / similar / miss）。"""
        return json.dumps(invoke_tool("query_cache", {
            "question": question, "scene_code": scene_code}), ensure_ascii=False)

    @mcp.tool()
    def search_doc(query: str, top_k: int = 5) -> str:
        """业务文档 / 错误码 / 报文语义检索。"""
        return json.dumps(invoke_tool("search_doc", {"query": query, "top_k": top_k}),
                          ensure_ascii=False)

    @mcp.tool()
    def search_code(query: str, top_k: int = 5) -> str:
        """COBOL / 源码 chunk 语义检索。"""
        return json.dumps(invoke_tool("search_code", {"query": query, "top_k": top_k}),
                          ensure_ascii=False)

    @mcp.tool()
    def search_mapping(query: str, top_k: int = 5) -> str:
        """字段映射检索。"""
        return json.dumps(invoke_tool("search_mapping", {"query": query, "top_k": top_k}),
                          ensure_ascii=False)

    @mcp.tool()
    def search_graph(query: str, intent: str = "business_rule") -> str:
        """知识图谱检索（实体邻域 / 三层查全 / 影响面）。intent: business_rule|impact|entity"""
        return json.dumps(invoke_tool("search_graph", {
            "query": query, "intent": intent}), ensure_ascii=False)

    @mcp.tool()
    def retrieve_all(query: str, intent: str = "business_rule", top_k: int = 5) -> str:
        """多路融合检索（图谱+文档+代码+映射）并重排。"""
        return json.dumps(invoke_tool("retrieve_all", {
            "query": query, "intent": intent, "top_k": top_k}), ensure_ascii=False)

    @mcp.tool()
    def impact_analyze(target: str, change_summary: str = "", depth: int = 3) -> str:
        """迁移影响面分析。"""
        return json.dumps(invoke_tool("impact_analyze", {
            "target": target, "change_summary": change_summary, "depth": depth}),
            ensure_ascii=False)

    @mcp.tool()
    def codegen_skeleton(interface_id: str, target: str = "spring_controller") -> str:
        """生成代码骨架（仅参考）。"""
        return json.dumps(invoke_tool("codegen_skeleton", {
            "interface_id": interface_id, "target": target}), ensure_ascii=False)

    @mcp.tool()
    def annotate_code(code: str, language: str = "cobol", hint: str = "") -> str:
        """基于知识库为粘贴代码生成注释（不改逻辑）。"""
        return json.dumps(invoke_tool("annotate_code", {
            "code": code, "language": language, "hint": hint}), ensure_ascii=False)

    @mcp.tool()
    def preview_source(path: str = "", source_type: str = "doc",
                       ref: str = "", loc: str = "") -> str:
        """预览依据原文（文档/代码/图谱）。"""
        return json.dumps(invoke_tool("preview_source", {
            "path": path, "source_type": source_type, "ref": ref, "loc": loc}),
            ensure_ascii=False)

    @mcp.tool()
    def kb_stats() -> str:
        """知识库图谱与向量规模统计。"""
        return json.dumps(invoke_tool("kb_stats", {}), ensure_ascii=False)

    # ---- 知识接入 / 图谱构建 ----
    @mcp.tool()
    def scan_dataset(root: str = "") -> str:
        """扫描数据源目录（默认 hf_data），接入前第一步。"""
        return json.dumps(invoke_tool("scan_dataset", {"root": root}), ensure_ascii=False)

    @mcp.tool()
    def clean_dataset(root: str = "", out_dir: str = "") -> str:
        """清洗数据集，产出三元组与 chunk（08_cleaned）。"""
        return json.dumps(invoke_tool("clean_dataset", {
            "root": root, "out_dir": out_dir}), ensure_ascii=False)

    @mcp.tool()
    def build_knowledge_graph(out_dir: str = "", include_tier_c: bool = False,
                              min_trust: float = 0.0) -> str:
        """将清洗产物导入知识图谱与向量库。"""
        return json.dumps(invoke_tool("build_knowledge_graph", {
            "out_dir": out_dir, "include_tier_c": include_tier_c,
            "min_trust": min_trust}), ensure_ascii=False)

    @mcp.tool()
    def upload_knowledge(filename: str, content_base64: str,
                         source_type: str = "doc") -> str:
        """上传单文件并执行六步接入流水线。"""
        return json.dumps(invoke_tool("upload_knowledge", {
            "filename": filename, "content_base64": content_base64,
            "source_type": source_type}), ensure_ascii=False)

    @mcp.tool()
    def ingest_knowledge_base(root: str = "", include_tier_c: bool = False,
                              min_trust: float = 0.0) -> str:
        """一键接入：scan → clean → build_knowledge_graph → kb_stats。"""
        return json.dumps(invoke_tool("ingest_knowledge_base", {
            "root": root, "include_tier_c": include_tier_c,
            "min_trust": min_trust}), ensure_ascii=False)

    return mcp


def main() -> None:
    _bootstrap()
    mcp = build_mcp()
    transport = "stdio"
    if "--transport" in sys.argv:
        i = sys.argv.index("--transport")
        if i + 1 < len(sys.argv):
            transport = sys.argv[i + 1]
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
