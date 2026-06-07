from __future__ import annotations
from x1_all_tools.registry import ToolRegistry

from .meta import TOOLS as META
from .env_tools import TOOLS as ENV_TOOLS
from .shell import TOOLS as SHELL
from .terminal import TOOLS as TERMINAL
from .processes import TOOLS as PROCESSES
from .files import TOOLS as FILES
from .python_code import TOOLS as PYTHON_CODE
from .web_browser import TOOLS as WEB_BROWSER
from .documents import TOOLS as DOCUMENTS
from .data_sql import TOOLS as DATA_SQL
from .media import TOOLS as MEDIA
from .ai_agent import TOOLS as AI_AGENT
from .git_project import TOOLS as GIT_PROJECT
from .api_server import TOOLS as API_SERVER
from .security_tools import TOOLS as SECURITY
from .deployment import TOOLS as DEPLOYMENT

def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for group in [
        META, ENV_TOOLS, SHELL, TERMINAL, PROCESSES, FILES, PYTHON_CODE, WEB_BROWSER, DOCUMENTS,
        DATA_SQL, MEDIA, AI_AGENT, GIT_PROJECT, API_SERVER, SECURITY, DEPLOYMENT
    ]:
        for spec in group:
            registry.register(spec)
    return registry
