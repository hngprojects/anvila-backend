import itertools
import sys, os
import warnings
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from decouple import config as decouple_config
from datetime import datetime, timezone

# passlib 1.7.4 is incompatible with bcrypt >= 4.0: detect_wrap_bug() passes a
# 73-byte password which bcrypt 4.x now rejects with ValueError instead of
# silently truncating. Patch it out before any test file is imported.
try:
    import passlib.handlers.bcrypt as _passlib_bcrypt
    _passlib_bcrypt.detect_wrap_bug = lambda ident: False
except Exception:
    pass

# Import all models so SQLAlchemy's metadata is fully populated before create_all()
import api.v1.models  # noqa: F401
from api.v1.models.permissions.permissions import Permission  # noqa: F401
from api.v1.models.permissions.role import Role  # noqa: F401
from api.db.database import Base



# Global IP generator (supports 16 million+ unique IPs)
IP_GENERATOR = itertools.cycle(
    (f"127.{i//65536}.{(i//256)%256}.{i%256}" for i in itertools.count())
)

@pytest.fixture(autouse=True)
def auto_mock_client_ip():
    """Automatically mock client IP for all tests"""
    with patch("fastapi.Request.client") as mock_client:
        mock_client.host = next(IP_GENERATOR)
        yield

warnings.filterwarnings("ignore", category=DeprecationWarning)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Get the project root directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@pytest.fixture(scope='module')
def mock_send_email():
    with patch("api.core.dependencies.email_sender.send_email") as mock_email_sending:
        with patch("fastapi.BackgroundTasks.add_task") as add_task_mock:
            add_task_mock.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
            yield mock_email_sending


@pytest.fixture(scope="session")
def db_engine():

   # Create a PostgreSQL test database engine.
    db_url = decouple_config('DB_URL')

    engine = create_engine(db_url)
    yield engine


@pytest.fixture(scope="session")
def apply_migrations(db_engine):
    """Create all tables in the test database."""
    Base.metadata.create_all(bind=db_engine)
    return


@pytest.fixture(scope="function")
def db_session(db_engine, apply_migrations):

    #Create a new database session for a test.
    connection = db_engine.connect()

    # Begin a transaction
    transaction = connection.begin()

    # Create a session bound to the connection
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    # Rollback the transaction after the test completes
    session.close()
    transaction.rollback()
    connection.close()

    # Blog Model Test Fixtures

    @pytest.fixture
    def test_user(db_session):
        """Create a test user for blog tests."""
        from api.v1.models.user import User

        # Create a unique email with timestamp to avoid conflicts
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        user = User(
            email=f"testuser_{timestamp}@example.com",
            username=f"testuser_{timestamp}",
            first_name="Test",
            last_name="User",
            is_active=True,
            is_verified=True,
            is_deleted=False,
            is_superadmin=False
        )

        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        yield user

    @pytest.fixture
    def test_blog(db_session, test_user):
        """Create a test blog post."""
        from api.v1.models.blog import Blog

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        blog = Blog(
            author_id=test_user.id,
            title=f"Test Blog {timestamp}",
            content="This is test content for the blog post.",
            excerpt="Test excerpt",
            tags="test,blog,indexing",
            is_deleted=False
        )

        db_session.add(blog)
        db_session.commit()
        db_session.refresh(blog)

        yield blog

    @pytest.fixture
    def test_multiple_blogs(db_session, test_user):
        """Create multiple test blog posts for a user."""
        from api.v1.models.blog import Blog

        blogs = []
        for i in range(5):
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            blog = Blog(
                author_id=test_user.id,
                title=f"Test Blog {i} {timestamp}",
                content=f"This is test content for blog post {i}.",
                excerpt=f"Test excerpt {i}",
                tags=f"test,blog{i},indexing",
                is_deleted=(i % 4 == 0)  # Make some blogs "deleted" for testing
            )

            db_session.add(blog)
            blogs.append(blog)

        db_session.commit()

        # Refresh all blogs to get their IDs
        for blog in blogs:
            db_session.refresh(blog)

        yield blogs

    @pytest.fixture
    def test_blog_like(db_session, test_user, test_blog):
        """Create a test blog like."""
        from api.v1.models.blog import BlogLike

        like = BlogLike(
            blog_id=test_blog.id,
            user_id=test_user.id,
            ip_address="127.0.0.1"
        )

        db_session.add(like)
        db_session.commit()
        db_session.refresh(like)

        yield like

    @pytest.fixture
    def test_blog_dislike(db_session, test_user, test_blog):
        """Create a test blog dislike."""
        from api.v1.models.blog import BlogDislike

        dislike = BlogDislike(
            blog_id=test_blog.id,
            user_id=test_user.id,
            ip_address="127.0.0.1"
        )

        db_session.add(dislike)
        db_session.commit()
        db_session.refresh(dislike)

        yield dislike

    @pytest.fixture
    def test_multiple_users(db_session):
        """Create multiple test users for advanced testing."""
        from api.v1.models.user import User

        users = []
        for i in range(3):
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            user = User(
                email=f"testuser{i}_{timestamp}@example.com",
                username=f"testuser{i}_{timestamp}",
                first_name=f"Test{i}",
                last_name=f"User{i}",
                is_active=True,
                is_verified=True,
                is_deleted=False,
                is_superadmin=(i == 0)  # Make one user a superadmin
            )

            db_session.add(user)
            users.append(user)

        db_session.commit()

        # Refresh all users to get their IDs
        for user in users:
            db_session.refresh(user)

        yield users

        # No need to delete as transaction is rolled back
