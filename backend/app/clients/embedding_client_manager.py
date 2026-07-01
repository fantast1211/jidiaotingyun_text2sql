from typing import Optional

from langchain_openai import OpenAIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[OpenAIEmbeddings] = None
        self.config = config

    def init(self):
        self.client = OpenAIEmbeddings(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            check_embedding_ctx_length=False,
        )


embedding_client_manager = EmbeddingClientManager(app_config.embedding)
