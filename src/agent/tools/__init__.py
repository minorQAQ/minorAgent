from .web_search import WebSearch
from .date_query import DateQuery
from .browser_control import BrowserControl
from .human_interaction import HumanInteraction
from .directory_listing import DirectoryListing
from .todo_list import TodoList
from .software_control import SoftwareControl
from .gui import GUITool
from .rag import RAGTool
from .agent_call import CallSubAgentTool
from .doc import DocTool
from .skill_router import SkillRouter
from .send_file import SendFileTool
from .terminal_execute import TerminalExecute
from .email import MailTool
from .image_gen import ImageGen
from .cron_manager import CronManagerTool
from .text2sql import Text2SQLTool
from .hard_excel_read import HardExcelReadTool
from .excel2sql import Excel2SQLTool

_all_tools = [
    WebSearch(),
    DateQuery(),
    BrowserControl(),
    HumanInteraction(),
    SoftwareControl(),
    RAGTool(),
    DirectoryListing(),
    TodoList(),
    GUITool(),
    CallSubAgentTool(),
    DocTool(),
    SkillRouter(),
    SendFileTool(),
    TerminalExecute(),
    MailTool(),
    ImageGen(),
    CronManagerTool(),
    Text2SQLTool(),
    HardExcelReadTool(),
    Excel2SQLTool(),
]

# 注册所有可用工具名称（供前端配置面板展示），从 _all_tools 实例推导
_ALL_AVAILABLE_TOOL_CLASSES = {tool.name: type(tool) for tool in _all_tools}


def get_tools():
    """返回当前 Agent 注册的全部 LangChain 工具列表。"""
    return _all_tools


def get_all_available_tool_names():
    """返回所有可用工具名称（含数据库工具，不管当前是否实例化）。"""
    return list(_ALL_AVAILABLE_TOOL_CLASSES.keys())


def get_all_available_tool_descriptions():
    """返回所有可用工具的名称和描述映射（用于前端展示）。"""
    result = {}
    for name, cls in _ALL_AVAILABLE_TOOL_CLASSES.items():
        inst = cls()
        desc = getattr(inst, "description", "")
        result[name] = (cls.__name__, (desc or "").split("\n")[0][:200])
    return result
