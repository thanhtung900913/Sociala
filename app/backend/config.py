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
