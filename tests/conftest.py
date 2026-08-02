"""Deterministic test substrate created before test modules are collected."""
from scripts.seed_test_fixtures import (
    DB_PATH,
    FASE2_PATH,
    RATINGS_PATH,
    build_database,
    build_fase2_params,
    build_ratings,
)


def pytest_configure() -> None:
    for path, builder in (
        (DB_PATH, build_database),
        (RATINGS_PATH, build_ratings),
        (FASE2_PATH, build_fase2_params),
    ):
        if not path.exists():
            builder(path)
