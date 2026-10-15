import requests
import json
import os


DEBEZIUM_HOST = os.getenv("DEBEZIUM_HOST", "localhost")

def upsert_connector(config_name: str):
    url = f"http://{DEBEZIUM_HOST}:8083/connectors/{config_name}/config"
    
    try:
        with open(f"./registers/{config_name}.json") as f:
            config_data = json.load(f)
        

        response = requests.put(url, json=config_data)
        
        if response.status_code in [200, 201]:
            print(f"✅ {config_name}: Updated/Created successfully!")
        else:
            print(f"❌ {config_name} Error: {response.status_code} - {response.text}")
            
    except FileNotFoundError:
        print(f"⚠️ File ./registers/{config_name}.json not found!")

if __name__ == "__main__":
    for conn in ["postgres", "mongo"]:
        upsert_connector(conn)