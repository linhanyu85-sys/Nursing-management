# audit-service

## Run

```
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

默认支持：
- `GET /health`
- `GET /ready`
- `GET /version`
