【用户的问题】
这段重试逻辑是怎么工作的？线上偶尔还是会失败，我能把 max_attempts 调大吗？

【代码：client/retry.py】
```python
RETRY_STATUS = {502, 503, 504}

def call_with_retry(send, request, *, max_attempts=5, base_delay=0.5,
                    max_delay=8.0, deadline_s=10.0):
    """max_attempts 包含第一次调用。"""
    start = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        try:
            resp = send(request)
            if resp.status not in RETRY_STATUS:
                return resp          # 包括 429：不在这里重试
        except TimeoutError:
            resp = None
        if attempt == max_attempts:
            break
        if request.method == "POST" and not request.idempotency_key:
            break                    # 没有幂等键的 POST 不重试
        delay = min(max_delay, base_delay * 2 ** (attempt - 1))
        delay *= random.uniform(0.8, 1.2)
        if time.monotonic() - start + delay > deadline_s:
            break                    # 等完就超过总时限，放弃
        time.sleep(delay)
    raise RetryExhausted(request, last=resp)
```

【维护者备注（docs/retry.md 摘录）】
- 429 不在这一层重试。429 由上层的限流器处理（client/limiter.py）。
- 默认 5 次尝试时，等待时间依次是 0.5、1、2、4 秒，合计 7.5 秒（不算抖动）。
- 总时限 deadline_s 默认 10 秒，由调用方 client/api.py 第 88 行传入，目前所有调用方都用默认值。
- 注意：只把 max_attempts 调到 6 没有用。第 6 次尝试之前要等 8 秒，7.5 + 8 = 15.5 秒，超过 10 秒总时限，第 6 次不会发生。要多重试，必须同时调大 deadline_s。
- deadline_s 调大会让用户请求的最长等待时间变长。页面的前端请求超时是 12 秒（web/src/http.ts 第 20 行）。deadline_s 超过 12 秒没有意义。
- 也就是说，在不改前端超时的前提下，第 6 次尝试没有办法发生。
