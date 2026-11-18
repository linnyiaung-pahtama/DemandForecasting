from app import config
from tests.conftest import TEST_URL


def test_tests_never_use_the_real_database(db):
    import app.main  # noqa: F401  (importing the app module must not touch the planner's database)
    assert config.DATABASE_URL == TEST_URL      # the app can only see the test database
    assert db["schema"].startswith("t_")        # and each test works in its own throwaway schema
    assert not hasattr(app.main, "app")         # no module-level app: the server uses the factory
