import os
import dotenv

dotenv.load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES'))
    JWT_REFRESH_TOKEN_EXPIRES = int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES'))
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = int(os.getenv('DB_PORT'))
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    JWT_BLOCKLIST_ENABLED = True
    JWT_TOKEN_LOCATION = ["headers"]
    POST_ENABLED_REACTIONS = ("LIKE",)
    COMMENT_REPLIES_ENABLED = (
        os.getenv("COMMENT_REPLIES_ENABLED", "true").lower() == "true"
    )
    # Must point to the same table/region as feed-worker.
    AWS_REGION = os.getenv("AWS_REGION")
    DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "user_feeds")
    FEED_QUERY_PAGE_SIZE = int(os.getenv("FEED_QUERY_PAGE_SIZE", "100"))
    FEED_MAX_QUERY_PAGES = int(os.getenv("FEED_MAX_QUERY_PAGES", "10"))
    MEDIA_BUCKET = os.getenv("MEDIA_BUCKET", "user-media")
    MEDIA_EXPIRES_IN = int(os.getenv("MEDIA_EXPIRES_IN", "600"))
    STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "S3").upper()
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID") or None
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY") or None
    S3_REGION = os.getenv("S3_REGION") or AWS_REGION or "us-east-1"
    S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "true").lower() == "true"
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    REDIS_BROKER_DB = int(os.getenv("REDIS_BROKER_DB", "2"))