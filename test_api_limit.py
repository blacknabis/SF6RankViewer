import requests

try:
    print("Testing /api/matches?limit=10 ...")
    response = requests.get("http://localhost:8000/api/matches?limit=10")
    if response.status_code == 200:
        data = response.json()
        print(f"Status: {response.status_code}")
        print(f"Count: {len(data)}")
        if len(data) <= 10:
             print("PASS: Count is within limit.")
        else:
             print("FAIL: Count exceeds limit.")
    else:
        print(f"Error: {response.status_code} {response.text}")
except Exception as e:
    print(f"Connection failed: {e}")
