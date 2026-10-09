【用户的问题】
`parse_ttl("15m")` 返回什么？

【代码：util/ttl.py】
```python
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

def parse_ttl(text: str) -> int:
    """把 '15m' 这样的写法换算成秒。"""
    value, unit = int(text[:-1]), text[-1]
    return value * UNITS[unit]
```
