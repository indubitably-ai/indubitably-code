from agent import run_agent, Tool
from tools_read import read_file_tool_def, read_file_impl
from tools_list import list_files_tool_def, list_files_impl
from tools_edit import edit_file_tool_def, edit_file_impl


if __name__ == "__main__":
    tools = [
        Tool(**read_file_tool_def(), fn=read_file_impl),
        Tool(**list_files_tool_def(), fn=list_files_impl),
        Tool(**edit_file_tool_def(), fn=edit_file_impl),
    ]
    run_agent(tools)


