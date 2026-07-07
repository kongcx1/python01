import asyncio
import sys


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        from asyncio import proactor_events

        _original_del = proactor_events._ProactorBasePipeTransport.__del__

        def _quiet_proactor_del(self):
            try:
                _original_del(self)
            except RuntimeError as exc:
                if "Event loop is closed" not in str(exc):
                    raise

        proactor_events._ProactorBasePipeTransport.__del__ = _quiet_proactor_del
    except Exception:
        pass

import uvicorn


if __name__ == "__main__":
    uvicorn.run("server_app:app", host="0.0.0.0", port=8787, loop="asyncio")
