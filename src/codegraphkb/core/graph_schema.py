"""Graph schema v4 names and precision levels.

The store still accepts string kinds/edge types for backward compatibility, but
new production-engine code should import these enums instead of spelling graph
terms ad hoc.
"""
from __future__ import annotations

from enum import IntEnum, StrEnum


GRAPH_SCHEMA_VERSION = 5


class PrecisionLevel(IntEnum):
    SYNTAX = 1
    CODEGRAPH_RESOLVER = 2
    LANGUAGE_SEMANTIC = 3
    EXTERNAL_INDEX = 4
    RUNTIME_SECURITY = 5


class NodeKind(StrEnum):
    REPOSITORY = "repository"
    FOLDER = "folder"
    FILE = "file"
    FILE_SUMMARY = "file_summary"
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    STRUCT = "struct"
    VARIABLE = "variable"
    PROPERTY = "property"
    CONSTRUCTOR = "constructor"
    MODULE = "module"
    NAMESPACE = "namespace"
    ROUTE = "route"
    TOOL = "tool"
    JOB = "job"
    EVENT_HANDLER = "event_handler"
    QUEUE_CONSUMER = "queue_consumer"
    CRON_TASK = "cron_task"
    TEST = "test"
    TEST_BLOCK = "test_block"
    FIXTURE = "fixture"
    MOCK = "mock"
    PROCESS = "process"
    COMMUNITY = "community"
    DATABASE_TABLE = "database_table"
    ORM_MODEL = "orm_model"
    EXTERNAL_SERVICE = "external_service"
    CONFIG_KEY = "config_key"
    SECRET_REF = "secret_ref"
    API_CONTRACT = "api_contract"
    REQUEST_SHAPE = "request_shape"
    RESPONSE_SHAPE = "response_shape"
    DATA_FIELD = "data_field"


class EdgeType(StrEnum):
    CONTAINS = "CONTAINS"
    DEFINES = "DEFINES"
    EXPORTS = "EXPORTS"
    IMPORTS = "IMPORTS"
    RE_EXPORTS = "RE_EXPORTS"
    CALLS = "CALLS"
    ACCESSES = "ACCESSES"
    READS = "READS"
    WRITES = "WRITES"
    THROWS = "THROWS"
    CATCHES = "CATCHES"
    AWAITED_BY = "AWAITED_BY"
    INSTANTIATES = "INSTANTIATES"
    EXTENDS = "EXTENDS"
    IMPLEMENTS = "IMPLEMENTS"
    HAS_METHOD = "HAS_METHOD"
    HAS_PROPERTY = "HAS_PROPERTY"
    METHOD_OVERRIDES = "METHOD_OVERRIDES"
    METHOD_IMPLEMENTS = "METHOD_IMPLEMENTS"
    HANDLES_ROUTE = "HANDLES_ROUTE"
    HANDLES_TOOL = "HANDLES_TOOL"
    HANDLES_EVENT = "HANDLES_EVENT"
    HANDLES_JOB = "HANDLES_JOB"
    HANDLES_CRON = "HANDLES_CRON"
    ROUTES_TO = "ROUTES_TO"
    ROUTE_HANDLED_BY = "ROUTE_HANDLED_BY"
    QUERIES = "QUERIES"
    PUBLISHES = "PUBLISHES"
    SUBSCRIBES = "SUBSCRIBES"
    USES_CONFIG = "USES_CONFIG"
    USES_SECRET = "USES_SECRET"
    READS_CONSTANT = "READS_CONSTANT"
    READS_CONFIG_KEY = "READS_CONFIG_KEY"
    READS_ENV_VAR = "READS_ENV_VAR"
    CALLS_EXTERNAL = "CALLS_EXTERNAL"
    TESTS = "TESTS"
    TESTS_SYMBOL = "TESTS_SYMBOL"
    ASSERTS = "ASSERTS"
    MOCKS = "MOCKS"
    USES_FIXTURE = "USES_FIXTURE"
    COVERS_ROUTE = "COVERS_ROUTE"
    STEP_IN_PROCESS = "STEP_IN_PROCESS"
    ENTRY_POINT_OF = "ENTRY_POINT_OF"
    TERMINAL_OF = "TERMINAL_OF"
    MEMBER_OF = "MEMBER_OF"
    DEPENDS_ON_COMMUNITY = "DEPENDS_ON_COMMUNITY"
    FLOWS_TO = "FLOWS_TO"
    TAINTS = "TAINTS"
    SANITIZES = "SANITIZES"
    VALIDATES = "VALIDATES"
    SERIALIZES = "SERIALIZES"
    DESERIALIZES = "DESERIALIZES"
    RETURNS_FIELD = "RETURNS_FIELD"
    CONSUMES_FIELD = "CONSUMES_FIELD"
    REQUEST_SHAPE_OF = "REQUEST_SHAPE_OF"
    RESPONSE_SHAPE_OF = "RESPONSE_SHAPE_OF"
    LIKELY_EDIT = "LIKELY_EDIT"
    LIKELY_READ = "LIKELY_READ"
    RELATED_TEST = "RELATED_TEST"
    RISK_SOURCE = "RISK_SOURCE"
    EXCLUDED_BY_BUDGET = "EXCLUDED_BY_BUDGET"
