# Telegram Downloader Server API

Base URL example: `http://54.46.103.244:8787`

All timestamps are UTC ISO (e.g. `2026-01-20T15:52:33Z`).

## Auth (optional)
If `api_token` is set in `server_config.json` or `SERVER_API_TOKEN` is set in env:
- Header: `Authorization: Bearer YOUR_TOKEN`
- Or Header: `X-Token: YOUR_TOKEN`
- Or Query: `?token=YOUR_TOKEN`

## Endpoints

### POST /tasks
Submit a task.

Request JSON:
```json
{
  "channel": "@sosocw",
  "message_ids": [13968, 13969],
  "auto_upload": true,
  "upload_meta": true
}
```

Response:
```json
{ "id": 17, "status": "pending" }
```

### GET /tasks
List tasks with filters, pagination, sorting.

Query params:
- `limit` (default 100)
- `offset` (default 0)
- `status` (comma-separated: `running,failed,pending,done,cancelled,cancel_requested,stale`)
- `channel` (substring match)
- `q` (search in channel/message_ids/error)
- `created_from`, `created_to` (UTC ISO string)
- `updated_from`, `updated_to` (UTC ISO string)
- `sort_by` = `id|created_at|updated_at|status|channel`
- `sort_order` = `asc|desc`

Example:
```
GET /tasks?status=running,failed&channel=sosocw&q=13968&sort_by=updated_at&sort_order=desc&limit=20&offset=0
```

Response:
```json
{
  "items": [ { "...": "..." } ],
  "total": 123,
  "limit": 20,
  "offset": 0
}
```

### GET /tasks/{task_id}
Get task detail.

### GET /tasks/{task_id}/files
Get per-file download progress.

Response:
```json
{ "items": [ { "file_name": "xxx.mp4", "bytes_total": 123, "bytes_downloaded": 45 } ] }
```

### GET /tasks/{task_id}/log
Get task log (paged + search).

Query params:
- `limit` (default 200)
- `offset` (default 0)
- `search` (string)

### POST /tasks/{task_id}/retry
Retry task.

### POST /tasks/{task_id}/cancel
Cancel task.

### DELETE /tasks/{task_id}
Delete task record (must not be running).

### POST /tasks/clean_stale
Mark stale tasks. Uses `SERVER_STALE_SECONDS` (default 3600).

### GET /tasks/summary
Task counts by status.

Response:
```json
{
  "total": 12,
  "by_status": {
    "running": 2,
    "done": 8,
    "failed": 1,
    "pending": 1
  }
}
```

## WebSocket

### WS /ws/tasks
Connect to receive live task updates.

Example:
```
ws://54.46.103.244:8787/ws/tasks?token=YOUR_TOKEN
```

Events:
- `task_created`
- `task_update`
- `task_log`

Example payload:
```json
{ "type": "task_update", "task_id": 17, "patch": { "status": "running" } }
```

## Curl Examples

Create task:
```bash
curl -X POST "http://54.46.103.244:8787/tasks" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"channel":"@sosocw","message_ids":[13968,13969],"auto_upload":true,"upload_meta":true}'
```

List tasks:
```bash
curl "http://54.46.103.244:8787/tasks?limit=20&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Task summary:
```bash
curl "http://54.46.103.244:8787/tasks/summary" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Cancel task:
```bash
curl -X POST "http://54.46.103.244:8787/tasks/17/cancel" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

