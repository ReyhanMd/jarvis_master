import queue
import sqlite3
import os
from contextlib import contextmanager
from apps.shail.settings import get_settings

class PooledConnectionProxy:
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._conn.__exit__(exc_type, exc_val, exc_tb)
        # In context manager mode, we automatically return to pool on exit
        self.close()

    def close(self):
        if not self._returned:
            self._pool.release_connection(self._conn)
            self._returned = True

class SQLiteConnectionPool:
    def __init__(self, max_connections=15):
        self._pool = queue.Queue(max_connections)
        self._max_connections = max_connections
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        path = get_settings().sqlite_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for _ in range(self._max_connections):
            conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and other concurrency pragmas
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._pool.put(conn)
        self._initialized = True

    def get_connection(self):
        if not self._initialized:
            self.initialize()
        try:
            conn = self._pool.get(timeout=10.0)
        except queue.Empty:
            # Fallback to creating a new transient connection if pool is starved
            path = get_settings().sqlite_path
            conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        return PooledConnectionProxy(self, conn)

    def release_connection(self, conn):
        if hasattr(conn, 'close') and type(conn) is not sqlite3.Connection:
            # If it's a proxy, don't double release
            return
        self._pool.put(conn)

    @contextmanager
    def connection(self):
        proxy = self.get_connection()
        try:
            with proxy:
                yield proxy
        finally:
            proxy.close()

    def close_all(self):
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        self._initialized = False

# Global pool instance
_pool = SQLiteConnectionPool()

def get_db():
    return _pool.connection()

def get_raw_db_conn():
    return _pool.get_connection()

def init_db_pool():
    _pool.initialize()

def close_db_pool():
    _pool.close_all()
