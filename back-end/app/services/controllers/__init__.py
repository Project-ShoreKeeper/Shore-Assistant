"""Service controllers — backends that the dashboard service-control feature
dispatches start/stop/state to. Each kind (process, docker, internal) has its
own controller class implementing the Controller ABC.
"""
from app.services.controllers.base import Controller, ServiceState, ServiceKind
from app.services.controllers.process import ProcessController
from app.services.controllers.docker import DockerController
from app.services.controllers.internal import InternalController

__all__ = [
    "Controller",
    "ServiceState",
    "ServiceKind",
    "ProcessController",
    "DockerController",
    "InternalController",
]
