from __future__ import annotations

import inspect
import re

import agency.views.command as command_view
import agency.views.execution as execution_view
import agency.views.risk as risk_view


def test_async_views_load_data_status_off_event_loop() -> None:
    command_source = inspect.getsource(command_view.paper_review_status_context)
    scheduler_source = inspect.getsource(command_view.scheduler_work_queue_raw_context)
    execution_source = inspect.getsource(execution_view.execution_preview_context)
    risk_source = inspect.getsource(risk_view.risk_context)

    for source in (command_source, scheduler_source, execution_source, risk_source):
        assert re.search(r"asyncio\.to_thread\s*\(\s*load_data_load_status", source)
