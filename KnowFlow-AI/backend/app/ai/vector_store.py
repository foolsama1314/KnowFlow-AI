"""Qdrant 向量库封装：支持服务器模式与本地嵌入式模式（无需 Docker）。"""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import uuid4

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.core.errors import AIProviderError

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: QdrantClient | None = None
        self._dim: int | None = None

    # ---------- 连接 ----------
    @property
    def collection(self) -> str:
        return get_settings().qdrant_collection

    @property
    def mode(self) -> str:
        return "server" if get_settings().qdrant_url else "local"

    def client(self) -> QdrantClient:
        if self._client is None:
            settings = get_settings()
            if settings.qdrant_url:
                self._client = QdrantClient(url=settings.qdrant_url, timeout=30)
                logger.info("连接 Qdrant 服务：%s", settings.qdrant_url)
            else:
                settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(settings.qdrant_local_path))
                logger.info("使用 Qdrant 本地模式：%s", settings.qdrant_local_path)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                logger.debug("关闭 Qdrant 客户端失败", exc_info=True)
            self._client = None

    def reset(self) -> None:
        """配置变化后重建连接（本地模式需要释放文件锁）。"""
        self.close()
        self._dim = None

    # ---------- 集合 ----------
    def ensure_collection(self, dim: int) -> None:
        with self._lock:
            client = self.client()
            if client.collection_exists(self.collection):
                current = client.get_collection(self.collection)
                vectors = current.config.params.vectors
                size = getattr(vectors, "size", None)
                if size is not None and int(size) != int(dim):
                    raise AIProviderError(
                        f"向量维度不一致：集合为 {size} 维，当前模型为 {dim} 维。"
                        "请在检索页执行「重建索引」，或恢复原来的向量模型配置。"
                    )
                self._dim = int(size) if size is not None else dim
                return
            client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
            self._dim = dim
            logger.info("已创建向量集合 %s（%d 维）", self.collection, dim)

    def create_staging_collection(self, dim: int) -> str:
        """建立独立重建集合，新索引完整前不触碰当前集合。"""
        name = f"{self.collection}__rebuild_{uuid4().hex}"
        self.client().create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        return name

    def activate_staging_collection(self, staging: str) -> None:
        """通过 Qdrant 别名切换新集合；已有别名时使用原子别名事务。"""
        client = self.client()
        aliases = client.get_aliases().aliases
        current_alias = next((item for item in aliases if item.alias_name == self.collection), None)
        create_operation = models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=staging, alias_name=self.collection)
        )
        old_collection: str | None = None
        if current_alias is not None:
            old_collection = current_alias.collection_name
            client.update_collection_aliases(
                change_aliases_operations=[
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=self.collection)
                    ),
                    create_operation,
                ]
            )
        else:
            # 兼容首次升级前使用固定集合名的数据：新集合已完整建好才执行切换。
            if client.collection_exists(self.collection):
                client.delete_collection(self.collection)
            client.update_collection_aliases(change_aliases_operations=[create_operation])

        if old_collection and old_collection != staging:
            try:
                client.delete_collection(old_collection)
            except Exception:  # noqa: BLE001
                logger.warning("旧向量集合清理失败：%s", old_collection, exc_info=True)
        self._dim = None

    # ---------- 写入 ----------
    def upsert(self, records: list[dict[str, Any]], collection_name: str | None = None) -> None:
        if not records:
            return
        points = [
            models.PointStruct(
                id=record["id"], vector=record["vector"], payload=record.get("payload", {})
            )
            for record in records
        ]
        self.client().upsert(
            collection_name=collection_name or self.collection, points=points, wait=True
        )

    def delete_document(self, document_id: str, collection_name: str | None = None) -> None:
        client = self.client()
        target = collection_name or self.collection
        if not client.collection_exists(target):
            return
        client.delete(
            collection_name=target,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    def drop_collection(self, collection_name: str | None = None) -> None:
        client = self.client()
        target = collection_name or self.collection
        aliases = client.get_aliases().aliases
        alias = next((item for item in aliases if item.alias_name == target), None)
        if alias is not None:
            client.update_collection_aliases(
                change_aliases_operations=[
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=target)
                    )
                ]
            )
            target = alias.collection_name
        if client.collection_exists(target):
            client.delete_collection(target)
        self._dim = None

    # ---------- 查询 ----------
    def search(
        self,
        vector: list[float],
        *,
        limit: int,
        document_ids: list[str] | None = None,
        file_types: list[str] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        client = self.client()
        if not client.collection_exists(self.collection):
            return []
        must: list[models.Condition] = []
        if document_ids:
            must.append(
                models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids))
            )
        if file_types:
            must.append(
                models.FieldCondition(key="file_type", match=models.MatchAny(any=file_types))
            )
        query_filter = models.Filter(must=must) if must else None
        response = client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [(hit.payload or {}, float(hit.score)) for hit in response.points]

    def count(self, collection_name: str | None = None) -> int:
        client = self.client()
        target = collection_name or self.collection
        if not client.collection_exists(target):
            return 0
        return int(client.count(target, exact=True).count)

    def healthy(self) -> bool:
        try:
            self.client().get_collections()
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Qdrant 连接检查失败", exc_info=True)
            return False


vector_store = VectorStore()
