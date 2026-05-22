"""Small Neo4j connection wrapper used by standalone test scripts."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session

from .config import (
    NEO4J_DATABASE,
    NEO4J_MAX_POOL_SIZE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    required,
)

logger = logging.getLogger(__name__)


class Neo4jConnection:
    """Manages a Neo4j driver and provides session context managers."""

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
    ) -> None:
        self.uri = required(uri, "NEO4J_URI")
        self.user = required(user, "NEO4J_USER")
        self.password = required(password, "NEO4J_PASSWORD")
        self.database = database or "neo4j"
        self._driver: Driver | None = None

        logging.getLogger("neo4j").setLevel(logging.WARNING)

    def connect(self) -> None:
        if self._driver is None:
            logger.info("Connecting to Neo4j at %s", self.uri)
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_pool_size=NEO4J_MAX_POOL_SIZE,
            )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @contextmanager
    def session(self) -> Session:
        if self._driver is None:
            self.connect()

        assert self._driver is not None
        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            session.close()

    def verify_connectivity(self) -> bool:
        try:
            with self.session() as session:
                result = session.run("RETURN 1 AS num")
                record = result.single()
                return bool(record and record["num"] == 1)
        except Exception as exc:
            logger.error("Neo4j connectivity check failed: %s", exc)
            return False

    def __enter__(self) -> "Neo4jConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

