"""Shared Neo4j connection helper."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from loguru import logger

from common.config import env_int, load_env_file, required_env


class Neo4jConnection:
    """Manage a Neo4j driver and provide session context managers."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        max_pool_size: int | None = None,
    ) -> None:
        load_env_file()
        self.uri = uri or required_env("NEO4J_URI")
        self.user = user or required_env("NEO4J_USER")
        self.password = password or required_env("NEO4J_PASSWORD")
        self.database = database or required_env("NEO4J_DATABASE")
        self.max_pool_size = max_pool_size or env_int("NEO4J_MAX_POOL_SIZE", 50)
        self._driver: Any | None = None

    def connect(self) -> None:
        """Open the Neo4j driver if needed."""
        if self._driver is not None:
            return
        from neo4j import GraphDatabase

        logger.info("Connecting to Neo4j at {}", self.uri)
        self._driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_pool_size=self.max_pool_size,
        )

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @contextmanager
    def session(self):
        """Yield a Neo4j session."""
        if self._driver is None:
            self.connect()
        assert self._driver is not None
        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            session.close()

    def verify_connectivity(self) -> bool:
        """Return whether Neo4j is reachable."""
        try:
            with self.session() as session:
                record = session.run("RETURN 1 AS num").single()
                return bool(record and record["num"] == 1)
        except Exception as exc:
            logger.error("Neo4j connectivity check failed: {}", exc)
            return False

    def __enter__(self) -> Neo4jConnection:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
