"""Native Windows service entrypoint for PitLane Agent."""

from __future__ import annotations

import logging
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil


class PitLaneAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PitLaneAgent"
    _svc_display_name_ = "PitLane Agent"
    _svc_description_ = "PitLane game server agent for AC EVO servers."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None
        self.log_file = Path(__file__).resolve().parent / "logs" / "service.log"

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        logging.info("Stop requested")
        win32event.SetEvent(self.stop_event)
        if self.server is not None:
            self.server.close()

    def SvcDoRun(self):
        self._configure_logging()

        from waitress.server import create_server
        from app import app
        from core import config_store

        servicemanager.LogInfoMsg("PitLane Agent service started")
        logging.info("Service started")

        host = config_store.HTTP_CFG["host"]
        port = config_store.HTTP_CFG["port"]
        logging.info("Starting Waitress on %s:%s", host, port)

        self.server = create_server(app, host=host, port=port)

        try:
            self.server.run()
        finally:
            logging.info("Service stopped")
            servicemanager.LogInfoMsg("PitLane Agent service stopped")

    def _configure_logging(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(self.log_file),
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PitLaneAgentService)
