import os

class Config:
    CELERY_APP_NAME = os.getenv('CELERY_APP_NAME', 'media_worker')
    
    CELERY_BROKER_HOST = os.getenv('CELERY_BROKER_HOST')
    CELERY_BROKER_PORT = os.getenv('CELERY_BROKER_PORT')
    CELERY_BROKER_PASSWORD = os.getenv('CELERY_BROKER_PASSWORD')
    
    CELERY_CONCURRENCY = int(os.getenv('CELERY_CONCURRENCY', '2'))
    
    
    DBHOST = os.getenv("DB_HOST") or os.getenv("DBHOST", "localhost")
    DBPORT = int(os.getenv("DB_PORT") or os.getenv("DBPORT", "5432"))
    DBNAME = os.getenv("DB_NAME") or os.getenv("DBNAME")
    DBUSER = os.getenv("DB_USER") or os.getenv("DBUSER")
    DBPASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DBPASSWORD")

    STATUS = os.getenv('STATUS')

    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = os.getenv('REDIS_PORT', '6379')
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
    REDIS_DB = int(os.getenv('REDIS_DB', '0'))
    REDIS_BROKER_DB = int(os.getenv('REDIS_BROKER_DB', '2'))

    LOG_FILE = os.getenv("LOG_FILE")

    MESHY_API_KEY = os.getenv("MESHY_API_KEY")
    MESHY_BASE_URL = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai")
    MESHY_WEBHOOK_SECRET = os.getenv("MESHY_WEBHOOK_SECRET")
    
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID") or None
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY") or None
    S3_REGION = os.getenv("S3_REGION") or os.getenv("AWS_REGION") or "us-east-1"
    S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "true").lower() == "true"
    
    KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "movenet_topic_sandbox")
