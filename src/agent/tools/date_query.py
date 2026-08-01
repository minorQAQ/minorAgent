from __future__ import annotations

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, create_model


class DateQuery(BaseTool):

    # 定义工具的输入参数结构，这里没有输入参数，所以是一个空的模型
    args_schema : type[BaseModel] = create_model("NoneInput")
    name : str = "date_query"
    description : str = "一个日期查询工具，可以返回当前的日期信息。仅当需要查询当前时间时调用，其余任何情况严禁调用。"    

    def _run(self) -> str:
        try:
            from datetime import datetime
            now = datetime.now()
            return now.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            return f"执行日期查询时出错: {str(e)}"
        
    async def _arun(self) -> str:
        return self._run()
