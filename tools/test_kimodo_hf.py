"""测试调用 KIMODO Hugging Face Space"""
from gradio_client import Client
import time

print("Connecting to nvidia/Kimodo Hugging Face Space...")
start = time.time()

client = Client("nvidia/Kimodo")
print(f"Connected in {time.time()-start:.1f}s")

# 查看可用的接口
print("\nAvailable endpoints:")
for endpoint in client.endpoints:
    print(f"  - {endpoint}")

# 尝试调用生成接口
print("\nTrying to generate: 'walk forward 3 steps'...")
try:
    result = client.predict(
        "walk forward 3 steps",
        api_name="/generate"
    )
    print(f"Result type: {type(result)}")
    print(f"Result: {result[:200] if isinstance(result, str) else result}")
except Exception as e:
    print(f"Error: {e}")
