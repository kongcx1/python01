import asyncio
import sys


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        from asyncio import proactor_events

        _original_del = proactor_events._ProactorBasePipeTransport.__del__
        _original_call_connection_lost = (
            proactor_events._ProactorBasePipeTransport._call_connection_lost
        )

        def _quiet_proactor_del(self):
            try:
                _original_del(self)
            except RuntimeError as exc:
                if "Event loop is closed" not in str(exc):
                    raise

        def _quiet_call_connection_lost(self, exc):
            try:
                _original_call_connection_lost(self, exc)
            except OSError as error:
                if getattr(error, "winerror", None) != 10038:
                    raise

        proactor_events._ProactorBasePipeTransport.__del__ = _quiet_proactor_del
        proactor_events._ProactorBasePipeTransport._call_connection_lost = (
            _quiet_call_connection_lost
        )
    except Exception:
        pass
