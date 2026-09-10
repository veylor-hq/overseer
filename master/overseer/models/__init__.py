"""Beanie Document Models registration."""

from overseer.models.workspace import Workspace, WorkspaceMember
from overseer.models.node import Node, NodeActivation, NodeCredential, NodeMetric
from overseer.models.service import MonitoredService, ServiceCheck
from overseer.models.event import Event
from overseer.models.alert import AlertDestination, AlertIncident

ALL_DOCUMENT_MODELS = [
    Workspace,
    WorkspaceMember,
    Node,
    NodeActivation,
    NodeCredential,
    NodeMetric,
    MonitoredService,
    ServiceCheck,
    Event,
    AlertDestination,
    AlertIncident,
]

__all__ = [
    "Workspace",
    "WorkspaceMember",
    "Node",
    "NodeActivation",
    "NodeCredential",
    "NodeMetric",
    "MonitoredService",
    "ServiceCheck",
    "Event",
    "AlertDestination",
    "AlertIncident",
    "ALL_DOCUMENT_MODELS",
]
