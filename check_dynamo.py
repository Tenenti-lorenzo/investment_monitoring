import os
from dotenv import load_dotenv
load_dotenv()
import boto3

region = os.getenv("AWS_REGION", "eu-central-1")
table_name = os.getenv("DYNAMODB_TABLE", "portfoliolab_users")
print(f"Region: {region}")
print(f"Table:  {table_name}")

client = boto3.client("dynamodb", region_name=region)
try:
    desc = client.describe_table(TableName=table_name)
    t = desc["Table"]
    print(f"Status:     {t['TableStatus']}")
    print(f"ItemCount:  {t['ItemCount']}")
    print(f"TableArn:   {t['TableArn']}")
except client.exceptions.ResourceNotFoundException:
    print("Tabella NON trovata in questa regione")
except Exception as e:
    print(f"Errore: {type(e).__name__}: {e}")

# Scan all items
try:
    dyn = boto3.resource("dynamodb", region_name=region)
    table = dyn.Table(table_name)
    resp = table.scan()
    items = resp.get("Items", [])
    print(f"\nItems nel DB: {len(items)}")
    for item in items:
        print(" -", {k: v for k, v in item.items() if k != "hashed_password"})
except Exception as e:
    print(f"Scan error: {type(e).__name__}: {e}")
