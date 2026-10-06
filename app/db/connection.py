import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from flask import current_app, request, has_request_context
from contextlib import contextmanager
import time
_db_pool = None

def _get_request_info():
    """
    Helper function to get current request information for logging.
    Returns empty string if not in request context.
    """
    if has_request_context():
        try:
            endpoint = request.endpoint or 'unknown'
            method = request.method
            path = request.path
            return f"[{method} {path} - {endpoint}]"
        except Exception:
            return "[request_context_error]"
    return "[no_request_context]"

def init_db_pool(app):
    """
    Initialize the database connection pool.
    Should be called once during app startup.
    """
    global _db_pool
    
    config = app.config
    
    minconn = config.get('DB_POOL_MIN_CONN', 4)
    maxconn = config.get('DB_POOL_MAX_CONN', 12)
    
    try:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            host=config["DB_HOST"],
            port=config["DB_PORT"],
            database=config["DB_NAME"],
            user=config["DB_USER"],
            password=config["DB_PASSWORD"],
            cursor_factory=RealDictCursor,
            # Connection parameters for better reliability
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            sslmode="require",
            # options="-c statement_timeout=30000"
        )
        app.logger.info(f"Database connection pool initialized (min={minconn}, max={maxconn})")
    except Exception as e:
        app.logger.error(f"Failed to initialize database connection pool: {str(e)}")
        raise

def close_db_pool():
    """
    Close all connections in the pool.
    Should be called during app shutdown.
    """
    global _db_pool
    if _db_pool:
        _db_pool.closeall()
        current_app.logger.info("Database connection pool closed")
        
def get_db_connection():
    """
    Get a connection from the pool.
    The caller is responsible for returning it using return_db_connection().
    
    For better resource management, use get_db_connection_context() instead.
    """
    if _db_pool is None:
        raise Exception("Database pool not initialized. Call init_db_pool() first.")
    
    max_retries = 3
    retry_delay = 0.1  # 100ms
    
    for attempt in range(max_retries):
        try:
            conn = _db_pool.getconn()
            if conn:
                return conn
            else:
                raise Exception("Unable to get connection from pool")
        except pool.PoolError as e:
            if attempt < max_retries - 1:
                current_app.logger.warning(
                    f"Pool exhausted, attempt {attempt + 1}/{max_retries}, "
                    f"retrying in {retry_delay}s... {_get_request_info()}"
                )
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                # Log pool status for debugging
                status = check_db_pool_status()
                current_app.logger.error(
                    f"Pool error getting connection: {str(e)}. "
                    f"Pool status: {status} {_get_request_info()}"
                )
                raise

def return_db_connection(conn):
    """
    Return a connection back to the pool.
    Call this instead of conn.close() when using get_db_connection().
    """
    if _db_pool and conn:
        try:
            # Rollback any uncommitted transactions before returning to pool
            if not conn.closed:
                if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    request_info = _get_request_info()
                    current_app.logger.warning(
                        f"Connection returned with uncommitted transaction! Rolling back. {request_info}"
                    )
                    conn.rollback()
            _db_pool.putconn(conn)
        except Exception as e:
            request_info = _get_request_info()
            current_app.logger.error(f"Error returning connection to pool: {str(e)} {request_info}")
        

@contextmanager
def get_db_connection_context():
    """
    Context manager for database connections.
    Automatically returns connection to pool when done.
    
    Usage:
        with get_db_connection_context() as conn:
            cur = conn.cursor()
            # ... do work ...
            conn.commit()
    """
    conn = get_db_connection()
    try:
        yield conn
    except Exception as e:
        if conn and not conn.closed:
            try:
                conn.rollback()
            except Exception as rollback_error:
                request_info = _get_request_info()
                current_app.logger.error(f"Error during rollback: {str(rollback_error)} {request_info}")
        raise
    finally:
        if conn and not conn.closed:
            try:
                # Check for uncommitted transaction (psycopg2 connection status)
                # STATUS_BEGIN (2) means transaction in progress
                # STATUS_READY (1) means no transaction
                if conn.status == 2:
                    request_info = _get_request_info()
                    current_app.logger.warning(
                        f"Connection returned with uncommitted transaction! Rolling back. {request_info}"
                    )
                    conn.rollback()
            except Exception as cleanup_error:
                request_info = _get_request_info()
                current_app.logger.error(f"Error during connection cleanup: {cleanup_error} {request_info}")
        return_db_connection(conn)
        
def check_db_pool_status():
    """
    Get current pool status for monitoring/debugging.
    Returns dict with pool statistics.
    """
    if _db_pool is None:
        return {"error": "Pool not initialized"}
    
    try:
        available = len(_db_pool._pool)
        in_use = len(_db_pool._used)
        
        return {
            "minconn": _db_pool.minconn,
            "maxconn": _db_pool.maxconn,
            "available": available,
            "in_use": in_use,
            "utilization_percent": round((in_use / _db_pool.maxconn) * 100, 2)
        }
    except Exception as e:
        return {"error": str(e)}