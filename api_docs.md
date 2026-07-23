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

### POST /external/video-library/ingest
Submit an external JSON video library for asynchronous upload. This is the recommended public integration endpoint.

Compatibility endpoint: `POST /external/video-library/upload` has identical behavior.

The endpoint returns immediately after creating a task; downloading the remote video, calculating MD5, uploading the video/cover, and creating the movie record continue in the background. Use the returned `job_id` or `task_id` to track the result.

Query params:
- `category` (optional): movie category. If omitted, uses `movie_category_default`; falls back to `纪录片`.
- `limit` (optional): maximum number of JSON entries to process. `0` creates an empty task.

Recommended request body: send the original JSON directly. The service reads `tasks`; a JSON array is also accepted.

```json
{
  "tasks": [
    {
      "title": "Example video title",
      "tags": [
        { "text": "tag-one" },
        { "text": "tag-two" }
      ],
      "capturedDownload": {
        "url": "https://cdn.example.com/videos/example.mp4"
      },
      "cover": {
        "url": "https://cdn.example.com/covers/example.jpg"
      }
    }
  ]
}
```

Field mapping:

| Input field | Required | Upload behavior |
| --- | --- | --- |
| `title` | No | Used for both movie `title` and `content`. If empty, `pageKey`, `pageUrl`, or `video-{index}` is used. |
| `tags[].text` | No | Converted to the movie `tags` array. String tags are also accepted. |
| `capturedDownload.url` | Yes | Remote video URL. If absent, `downloads[]` with `kind: "download"` is used as a fallback. |
| `cover.url` | No | Remote cover URL. It is uploaded as the movie cover. A cover upload failure does not block video/movie submission. |

Optional wrapper format, useful when `category` and `limit` should be included in the JSON body:

```json
{
  "payload": {
    "tasks": [
      {
        "title": "Example video title",
        "tags": [{ "text": "tag-one" }],
        "capturedDownload": { "url": "https://cdn.example.com/videos/example.mp4" },
        "cover": { "url": "https://cdn.example.com/covers/example.jpg" }
      }
    ]
  },
  "category": "纪录片",
  "limit": 20
}
```

If the same option appears both in the query string and wrapper body, the query string wins.

Success response:

```json
{
  "job_id": "c27da3a7f19b4d619ec5ac5d91652a15",
  "task_id": 158,
  "status": "running"
}
```

Possible request errors:
- `400`: body is not JSON, `limit` is not numeric, or the upload service is not configured.
- `401`: missing or invalid API token when authentication is enabled.

### GET /external/video-library/jobs/{job_id}
Get the in-memory processing result of an external JSON upload job.

Response fields:
- `status`: `running`, `done`, or `failed`.
- `total`, `success`, `failed`: item counts.
- `items`: per-entry results. Successful entries include `video_id`, `thumbnail_id`, `content_md5`, `file_size`, and `category`; failed entries include `error`.

`job_id` status is kept in server memory. For durable task history, logs, and per-file progress, use the returned `task_id` with `GET /tasks/{task_id}`, `GET /tasks/{task_id}/files`, and `GET /tasks/{task_id}/log`.

### GET /external/video-library/progress
Query aggregate progress for all JSON video upload tasks. No `task_id` is required.

Response fields:
- `task_total`: number of JSON video upload tasks.
- `total`: total video entries across all tasks.
- `completed`: entries that are successful, skipped, or failed.
- `pending`, `uploading`, `success`, `skipped`, `failed`: counts by current item status.

```bash
curl "https://YOUR_DOMAIN/api/external/video-library/progress" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### GET /external/video-library/tasks/{task_id}/progress
Optional per-task durable JSON video upload progress. Use the `task_id` returned by `POST /external/video-library/ingest` when individual file details are required.

This endpoint reads the task database, so it remains available after a server restart. It only accepts tasks created by JSON video upload.

Response fields:
- `status`: task status, such as `running`, `done`, `failed`, or `cancelled`.
- `message`: current processing message.
- `total`, `completed`, `pending`, `uploading`, `success`, `skipped`, `failed`: item counts.
- `files`: per-video progress and result records, including `status`, `upload_id`, `content_md5`, `error`, and `local_deleted` where applicable.

```bash
curl "https://YOUR_DOMAIN/api/external/video-library/tasks/158/progress" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Submit an original JSON file:

```bash
curl -X POST "https://YOUR_DOMAIN/api/external/video-library/ingest" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  --data-binary @video-task-library.json
```

Submit with category and item limit:

```bash
curl -X POST "https://YOUR_DOMAIN/api/external/video-library/ingest?category=%E7%BA%AA%E5%BD%95%E7%89%87&limit=20" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  --data-binary @video-task-library.json
```

Poll a job result:

```bash
curl "https://YOUR_DOMAIN/api/external/video-library/jobs/JOB_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
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
