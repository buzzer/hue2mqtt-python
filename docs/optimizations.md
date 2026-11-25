# Potential Optimisations for Hue2MQTT

## 1. Dedicated Event Loop per Instance
- **Current**: Uses a global event loop (`asyncio.get_event_loop()`).
- **Issue**: Global loop can be shared across multiple instances or tests, leading to interference.
- **Fix**: Create `self.loop = asyncio.new_event_loop()` in the constructor and set it with `asyncio.set_event_loop(self.loop)`.

## 2. Platform‑Safe Signal Handling
- **Current**: Registers signal handlers directly on the loop.
- **Issue**: Windows does not support `loop.add_signal_handler`.
- **Fix**: Wrap registration in a try/except and skip on unsupported platforms or use `signal.signal` when needed.

## 3. Logging Configuration Order
- **Current**: Logger for third‑party libraries (`gmqtt`) is set after the basic config.
- **Issue**: Early logs from those libs may use default settings.
- **Fix**: Configure the global logger first, then adjust specific loggers.

## 4. Persistent MQTT Client
- **Current**: Wrapper might reconnect on every `publish()` call.
- **Issue**: Frequent reconnects increase latency and network load.
- **Fix**: Maintain a single persistent client inside `MQTTWrapper` and reuse it for all publishes.

## 5. Caching Alias Lookups
- **Current**: `_topic_names()` rebuilds lists on each call.
- **Issue**: Minor performance hit when many lights/groups are processed.
- **Fix**: Cache the alias mapping or pre‑compute topic names.

## 6. Clean HTTP Session Handling
- **Current**: `ClientSession` is opened in a context but may not close on errors.
- **Issue**: Leaks in exceptional paths.
- **Fix**: Enclose the entire run logic inside an `async with aiohttp.ClientSession()` block.

## 7. Payload Validation Logging
- **Current**: JSON decode errors are swallowed silently.
- **Issue**: Invalid payloads remain unnoticed by users.
- **Fix**: Log a warning when a payload cannot be parsed.

## 8. Type Annotations for Internal Attributes
- **Current**: Attributes like `_mqtt` and `_bridge` lack type hints.
- **Issue**: Reduces clarity for static analysis tools.
- **Fix**: Add explicit annotations, e.g., `self._mqtt: MQTTWrapper`.

---

These changes are small, focused, and can be applied incrementally to improve performance, maintainability, and robustness.
