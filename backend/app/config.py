"""环境驱动配置。

存储双模式：
  - 配置了容器连接串（KB_PG_DSN / KB_GRAPH_URL / KB_VECTOR_URI / KB_S3_*）时连真实组件；
  - 未配置时使用内嵌回退（SQLite / 文件图库 / 内嵌向量索引 / 本地对象目录），
    保证无 Docker 环境开箱即跑，代码路径与设计文档一致。
LLM 双模式：
  - 配置 KB_LLM_API_KEY 时走 OpenAI 兼容接口（GLM/DeepSeek/Qwen 均可）；
  - 未配置时使用 MockLLM（基于检索证据的模板作答），全链路可演示。
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('KB_DATA_DIR', str(BASE_DIR / 'data')))
SEED_DIR = BASE_DIR / "data" / "seed"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "某行核心系统迁移知识库"
    api_prefix: str = "/api/v1"
    jwt_secret: str = "hf-kb-demo-secret-change-me"
    jwt_expire_hours: int = 12

    # ---- 存储（未配置则内嵌回退） ----
    kb_pg_dsn: str | None = None            # 例 postgresql+psycopg://kb:kb@localhost:5432/kb
    kb_graph_url: str | None = None         # 例 bolt://localhost:7687
    kb_graph_user: str = "neo4j"
    kb_graph_password: str = "kbpass"
    kb_vector_uri: str | None = None        # 例 http://localhost:19530
    kb_s3_endpoint: str | None = None       # 例 localhost:9000
    kb_s3_access_key: str = ""
    kb_s3_secret_key: str = ""

    # ---- LLM（OpenAI 兼容） ----
    kb_llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    kb_llm_api_key: str = ""
    kb_llm_model: str = "glm-4.6"
    kb_llm_timeout: float = 120.0
    kb_emb_base_url: str = ""               # 缺省沿用 kb_llm_base_url
    kb_emb_api_key: str = ""                # 缺省沿用 kb_llm_api_key
    kb_emb_model: str = "embedding-3"
    kb_rerank_url: str = ""                 # TEI /rerank 端点，可选

    # ---- 长时记忆阈值（设计初值，可配置） ----
    threshold_exact: float = 0.95
    threshold_similar: float = 0.80

    # ---- 检索预算 ----
    retrieve_top_k: int = 5
    context_budget_tokens: int = 6000

    # ---- 数据集清洗（默认指向仓库根 hf_data）----
    kb_dataset_root: str = ""           # 例 D:/zcode/hsbc/kb-system/hf_data


settings = Settings()
