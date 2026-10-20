import os

class Config:
    CELERY_APP_NAME = os.getenv('CELERY_APP_NAME')
    
    CELERY_BROKER_HOST = os.getenv('CELERY_BROKER_HOST')
    CELERY_BROKER_PORT = os.getenv('CELERY_BROKER_PORT')
    CELERY_BROKER_PASSWORD = os.getenv('CELERY_BROKER_PASSWORD')
    
    CELERY_CONCURRENCY = int(os.getenv('CELERY_CONCURRENCY'))
    
    
    DBHOST = os.getenv("DBHOST")
    DBPORT = int(os.getenv("DBPORT"))
    DBNAME = os.getenv("DBNAME")
    DBUSER = os.getenv("DBUSER")
    DBPASSWORD = os.getenv("DBPASSWORD")

    STATUS = os.getenv('STATUS')

    REDIS_HOST = os.getenv('REDIS_HOST')
    REDIS_PORT = os.getenv('REDIS_PORT', '6379')
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
    REDIS_DB = int(os.getenv('REDIS_DB', '0'))
    REDIS_BROKER_DB = int(os.getenv('REDIS_BROKER_DB', '2'))

    LOG_FILE = os.getenv("LOG_FILE")

    MESHY_API_KEY = os.getenv("MESHY_API_KEY")
    MESHY_BASE_URL = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai")
    MESHY_WEBHOOK_SECRET = os.getenv("MESHY_WEBHOOK_SECRET")
    
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
    S3_REGION = os.getenv("S3_REGION")
    S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "true").lower() == "true"
    
    KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "movenet_topic_sandbox")